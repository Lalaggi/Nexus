from __future__ import annotations

from cryptography.fernet import Fernet

from assistant.crypto import Cipher, EncryptionError
from assistant.db import Database


async def test_sensitive_fields_are_encrypted_and_round_trip(tmp_path):
    path = tmp_path / "assistant.db"
    cipher = Cipher(Fernet.generate_key())
    db = Database(path, cipher=cipher)
    await db.connect()

    chat = await db.create_chat("My private chat", "private goal")
    user_message = await db.add_message(
        chat["id"], "user", "hello super secret", attachments=[{"name": "secret.txt"}]
    )
    await db.add_message(
        chat["id"],
        "assistant",
        "assistant secret reply",
        reasoning="private reasoning",
        tool_events=[{"name": "sandbox", "data": {"stdout": "secret stdout"}}],
    )
    task = await db.create_task(chat["id"], "secret task", "secret detail")
    await db.set_note("editor", "Neovim secret")
    await db.set_setting("nim_api_key", "nvapi-secret")
    upload = await db.add_upload("secret.txt", "text/plain", 10, "secret upload text", chat["id"])

    raw = path.read_bytes()
    for value in (
        b"My private chat",
        b"private goal",
        b"hello super secret",
        b"assistant secret reply",
        b"private reasoning",
        b"secret stdout",
        b"secret task",
        b"secret detail",
        b"Neovim secret",
        b"nvapi-secret",
        b"secret.txt",
        b"secret upload text",
    ):
        assert value not in raw

    chats = await db.list_chats()
    assert chats[0]["title"] == "My private chat"
    assert chats[0]["preview"] == "hello super secret"

    messages = await db.list_messages(chat["id"])
    assert messages[0]["content"] == "hello super secret"
    assert messages[0]["attachments"] == [{"name": "secret.txt"}]
    assert messages[1]["content"] == "assistant secret reply"
    assert messages[1]["reasoning"] == "private reasoning"
    assert messages[1]["tool_events"][0]["data"]["stdout"] == "secret stdout"

    assert (await db.get_task(task["id"]))["title"] == "secret task"
    assert (await db.get_note("EDITOR"))["value"] == "Neovim secret"
    assert await db.get_setting("nim_api_key") == "nvapi-secret"
    assert (await db.get_upload(upload["id"]))["filename"] == "secret.txt"

    await db.close()

    # Reopening with the same key still works.
    reopened = Database(path, cipher=cipher)
    await reopened.connect()
    assert (await reopened.get_chat(chat["id"]))["title"] == "My private chat"
    assert (await reopened.get_message(user_message["id"]))["content"] == "hello super secret"
    await reopened.close()


async def test_plaintext_rows_are_migrated_and_removed_from_the_file(tmp_path):
    path = tmp_path / "assistant.db"
    cipher = Cipher(Fernet.generate_key())
    db = Database(path, cipher=cipher)
    await db.connect()
    chat = await db.create_chat("chat", "")
    message = await db.add_message(chat["id"], "user", "initial")
    await db.close()

    # Simulate a row written by an older, unencrypted version.
    old = Database(path, cipher=cipher)
    await old.connect()
    await old.conn.execute(
        "UPDATE messages SET content = ? WHERE id = ?", ("legacy plaintext", message["id"])
    )
    await old.conn.commit()
    await old.close()

    migrated = Database(path, cipher=cipher)
    await migrated.connect()
    assert (await migrated.get_message(message["id"]))["content"] == "legacy plaintext"
    assert b"legacy plaintext" not in path.read_bytes()
    await migrated.close()


async def test_wrong_key_fails_loudly(tmp_path):
    path = tmp_path / "assistant.db"
    db = Database(path, cipher=Cipher(Fernet.generate_key()))
    await db.connect()
    chat = await db.create_chat("private", "")
    await db.add_message(chat["id"], "user", "cannot read without the key")
    await db.close()

    wrong = Database(path, cipher=Cipher(Fernet.generate_key()))
    await wrong.connect()
    try:
        try:
            await wrong.list_messages(chat["id"])
        except EncryptionError:
            pass
        else:
            raise AssertionError("decryption with the wrong key should fail")
    finally:
        await wrong.close()
