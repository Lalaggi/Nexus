from __future__ import annotations
# Copyright (C) 2026 Ellie Wells <elilovescomputers@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from cryptography.fernet import Fernet

from nexus.crypto import Cipher
from nexus.db import Database


async def test_message_versions_chain_and_switch(tmp_path):
    path = tmp_path / "nexus.db"
    cipher = Cipher(Fernet.generate_key())
    db = Database(path, cipher=cipher)
    await db.connect()

    chat = await db.create_chat("chat", "")
    # A fresh message has version 1 marked complete/original and active.
    message = await db.add_message(chat["id"], "user", "first draft")
    assert message["active_version_id"]
    assert len(message["versions"]) == 1
    v1 = message["versions"][0]
    assert v1["version"] == 1
    assert v1["source"] == "original"
    assert v1["content"] == "first draft"

    # Edit appends version 2 and makes it active.
    updated = await db.create_message_version(message["id"], content="second draft", source="edit")
    assert updated["active_version_id"] != v1["id"]
    assert len(updated["versions"]) == 2
    versions = await db.list_message_versions(message["id"])
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["source"] == "original"
    assert versions[1]["source"] == "edit"
    assert versions[1]["content"] == "second draft"

    # Switching back to v1 makes v1 active again.
    switched = await db.activate_message_version(message["id"], v1["id"])
    assert switched["active_version_id"] == v1["id"]
    assert switched["content"] == "first draft"

    await db.close()


async def test_assistant_reply_links_to_active_user_version(tmp_path):
    path = tmp_path / "nexus.db"
    cipher = Cipher(Fernet.generate_key())
    db = Database(path, cipher=cipher)
    await db.connect()

    chat = await db.create_chat("chat", "")
    user = await db.add_message(chat["id"], "user", "ask A")
    assistant = await db.add_message(
        chat["id"], "assistant", "reply A", reply_to_version_id=user["active_version_id"]
    )

    # The assistant's v1 points at the user's active (v1) version.
    assert assistant["versions"][0]["reply_to_version_id"] == user["active_version_id"]

    # Edit the user message to "ask B" -> version 2 becomes active.
    edited_user = await db.create_message_version(user["id"], content="ask B", source="edit")

    # A new assistant reply links to the user's NEW active version v2.
    assistant2 = await db.add_message(
        chat["id"], "assistant", "reply B", reply_to_version_id=edited_user["active_version_id"]
    )
    assert assistant2["versions"][0]["reply_to_version_id"] == edited_user["active_version_id"]

    # The latest version replying to the user's active version is assistant2's.
    latest = await db.latest_version_for_reply(
        assistant2["id"], edited_user["active_version_id"]
    )
    assert latest["message_id"] == assistant2["id"]
    await db.close()


async def test_set_message_content_updates_active_version(tmp_path):
    path = tmp_path / "nexus.db"
    cipher = Cipher(Fernet.generate_key())
    db = Database(path, cipher=cipher)
    await db.connect()

    chat = await db.create_chat("chat", "")
    message = await db.add_message(chat["id"], "assistant", "original")
    version_id = message["active_version_id"]

    await db.set_message_content(message["id"], "rewritten")

    versions = await db.list_message_versions(message["id"])
    assert len(versions) == 1
    # active version row and message row both reflect rewrite
    assert versions[0]["content"] == "rewritten"
    got = await db.get_message(message["id"])
    assert got["content"] == "rewritten"
    assert got["active_version_id"] == version_id
    await db.close()
