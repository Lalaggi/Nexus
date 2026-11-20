"""SQLite persistence. Small, single-user, and deliberately boring."""
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

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from .crypto import PREFIX, Cipher, get_cipher

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA secure_delete=ON;

CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    goal TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT 'nemotron-3.5-super-vl',
    provider TEXT NOT NULL DEFAULT 'auto',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    reasoning TEXT NOT NULL DEFAULT '',
    tool_events TEXT NOT NULL DEFAULT '[]',
    attachments TEXT NOT NULL DEFAULT '[]',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    seq INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    active_version_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, seq);

CREATE TABLE IF NOT EXISTS message_versions (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    reasoning TEXT NOT NULL DEFAULT '',
    tool_events TEXT NOT NULL DEFAULT '[]',
    attachments TEXT NOT NULL DEFAULT '[]',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'complete',
    source TEXT NOT NULL DEFAULT 'original',
    reply_to_version_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_message_versions_number
    ON message_versions(message_id, version);
CREATE INDEX IF NOT EXISTS idx_message_versions_message
    ON message_versions(message_id);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_chat ON tasks(chat_id, position);

CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    chat_id TEXT,
    filename TEXT NOT NULL,
    mime TEXT NOT NULL DEFAULT 'application/octet-stream',
    size INTEGER NOT NULL DEFAULT 0,
    text_excerpt TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_notes (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_notes_key ON user_notes(key);

CREATE TABLE IF NOT EXISTS custom_models (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    model_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_custom_models_model_id ON custom_models(model_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(9).replace("-", "").replace("_", "")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


NOTE_KEY_MAX = 60
NOTE_VALUE_MAX = 1000
NOTE_KEY_PATTERN = re.compile(r"[a-z0-9_-]+")


class Database:
    def __init__(self, path: Path, cipher: Cipher | None = None):
        self.path = path
        self.cipher = cipher or get_cipher()
        self._conn: aiosqlite.Connection | None = None

    def _encrypt(self, value: str | None) -> str:
        return self.cipher.encrypt(value)

    def _decrypt(self, value: str | None) -> str:
        return self.cipher.decrypt(value)

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        await conn.executescript(SCHEMA)
        # Small forward-only migration for databases created before the timeline
        # started recording how long a turn took.
        cursor = await conn.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in await cursor.fetchall()}
        await cursor.close()
        if "duration_ms" not in columns:
            await conn.execute(
                "ALTER TABLE messages ADD COLUMN duration_ms INTEGER NOT NULL DEFAULT 0"
            )
        # Message editing and regeneration keep every version. Older databases
        # get a single version for each existing message, plus links between an
        # assistant reply and the user version it answered.
        if "active_version_id" not in columns:
            await conn.execute(
                "ALTER TABLE messages ADD COLUMN active_version_id TEXT NOT NULL DEFAULT ''"
            )
        await conn.commit()
        self._conn = conn
        await self._migrate_message_versions()
        await self._encrypt_plaintext()

    async def _migrate_message_versions(self) -> None:
        """Give every pre-versioning message a first version and reply links.

        This is idempotent: messages that already point at an active version are
        skipped, and empty reply links are only filled once a preceding user
        version exists.
        """
        rows = await self._fetchall(
            "SELECT * FROM messages WHERE active_version_id IS NULL OR active_version_id = ''"
            " ORDER BY chat_id ASC, seq ASC"
        )
        for row in rows:
            version_id = new_id("v")
            await self.conn.execute(
                """INSERT INTO message_versions
                   (id,message_id,version,content,reasoning,tool_events,attachments,
                    duration_ms,status,source,reply_to_version_id,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    version_id,
                    row["id"],
                    1,
                    row.get("content") or "",
                    row.get("reasoning") or "",
                    row.get("tool_events") or "[]",
                    row.get("attachments") or "[]",
                    row.get("duration_ms") or 0,
                    "complete",
                    "original",
                    "",
                    row.get("created_at") or now(),
                ),
            )
            await self.conn.execute(
                "UPDATE messages SET active_version_id = ? WHERE id = ?",
                (version_id, row["id"]),
            )

        # Link an assistant's original version to the user version it answered
        # so switching either side of an edited turn moves both sides together.
        messages = await self._fetchall(
            "SELECT id, chat_id, role, seq, active_version_id FROM messages"
            " ORDER BY chat_id ASC, seq ASC"
        )
        previous_user: dict[str, dict] = {}
        for row in messages:
            if row["role"] == "user":
                previous_user[row["chat_id"]] = row
                continue
            if row["role"] != "assistant":
                continue
            user_row = previous_user.get(row["chat_id"])
            if not user_row or not user_row.get("active_version_id"):
                continue
            await self.conn.execute(
                """UPDATE message_versions SET reply_to_version_id = ?
                   WHERE message_id = ? AND reply_to_version_id = ''""",
                (user_row["active_version_id"], row["id"]),
            )
        await self.conn.commit()

    async def _encrypt_plaintext(self) -> None:
        """Encrypt values written by versions that predate at-rest encryption.

        This is intentionally idempotent: already-encrypted values carry a
        prefix and are left alone, so it is safe to run on every startup.
        """
        targets = {
            "chats": ("title", "goal"),
            "messages": ("content", "reasoning", "tool_events", "attachments"),
            "message_versions": ("content", "reasoning", "tool_events", "attachments"),
            "tasks": ("title", "detail"),
            "uploads": ("filename", "text_excerpt"),
            "settings": ("value",),
            "user_notes": ("value",),
        }
        marker = f"{PREFIX}%"
        changed = 0
        for table, columns in targets.items():
            for column in columns:
                rows = await self._fetchall(
                    f"SELECT rowid, {column} AS value FROM {table} "  # noqa: S608 - fixed identifiers
                    f"WHERE {column} IS NOT NULL AND {column} != '' AND {column} NOT LIKE ?",
                    (marker,),
                )
                for row in rows:
                    await self.conn.execute(
                        f"UPDATE {table} SET {column} = ? WHERE rowid = ?",  # noqa: S608
                        (self._encrypt(row["value"]), row["rowid"]),
                    )
                    changed += 1
        await self.conn.commit()
        if changed:
            # Updating a row does not necessarily erase the old plaintext from
            # SQLite's free pages or WAL. Rebuild the file so a copied database
            # cannot still contain the pre-encryption values.
            await self._checkpoint()
            cursor = await self.conn.execute("VACUUM")
            await cursor.close()
            await self._checkpoint()

    async def _checkpoint(self) -> None:
        cursor = await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await cursor.fetchall()
        await cursor.close()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database is not connected")
        return self._conn

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(r) for r in rows]

    async def _fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        cursor = await self.conn.execute(sql, params)
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row else None

    # ------------------------------------------------------------------ chats
    async def list_chats(self) -> list[dict]:
        rows = await self._fetchall(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.id) AS message_count
            FROM chats c
            ORDER BY c.updated_at DESC
            """
        )
        latest_rows = await self._fetchall(
            """
            SELECT m.chat_id, m.content
            FROM messages m
            JOIN (
                SELECT chat_id, MAX(seq) AS seq
                FROM messages
                WHERE role = 'user'
                GROUP BY chat_id
            ) newest ON newest.chat_id = m.chat_id AND newest.seq = m.seq
            """
        )
        previews = {
            row["chat_id"]: self._decrypt(row["content"]) for row in latest_rows
        }
        for row in rows:
            preview = previews.get(row["id"], "")
            row["preview"] = preview.strip().replace("\n", " ")[:120]
            row["title"] = self._decrypt(row.get("title"))
            row["goal"] = self._decrypt(row.get("goal"))
        return rows

    async def create_chat(self, title: str, goal: str = "", model: str = "nemotron-3.5-super-vl") -> dict:
        chat_id = new_id("c")
        stamp = now()
        await self.conn.execute(
            "INSERT INTO chats (id,title,goal,model,provider,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (chat_id, self._encrypt(title), self._encrypt(goal), model, "auto", stamp, stamp),
        )
        await self.conn.commit()
        return await self.get_chat(chat_id)  # type: ignore[return-value]

    async def get_chat(self, chat_id: str) -> dict | None:
        row = await self._fetchone("SELECT * FROM chats WHERE id = ?", (chat_id,))
        if row is not None:
            row["title"] = self._decrypt(row.get("title"))
            row["goal"] = self._decrypt(row.get("goal"))
        return row

    async def update_chat(self, chat_id: str, **fields: Any) -> None:
        allowed = {"title", "goal", "model", "provider"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return
        for key in ("title", "goal"):
            if key in updates:
                updates[key] = self._encrypt(updates[key])
        updates["updated_at"] = now()
        clause = ", ".join(f"{k} = ?" for k in updates)
        await self.conn.execute(
            f"UPDATE chats SET {clause} WHERE id = ?",  # noqa: S608 - keys are whitelisted
            (*updates.values(), chat_id),
        )
        await self.conn.commit()

    async def touch_chat(self, chat_id: str) -> None:
        await self.conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now(), chat_id))
        await self.conn.commit()

    async def delete_chat(self, chat_id: str) -> None:
        # Explicitly remove child rows instead of relying solely on ON DELETE
        # CASCADE, so the chat is fully removed even if FK enforcement is off.
        await self.conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        await self.conn.execute("DELETE FROM tasks WHERE chat_id = ?", (chat_id,))
        await self.conn.execute("DELETE FROM uploads WHERE chat_id = ?", (chat_id,))
        await self.conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        await self.conn.commit()

    # --------------------------------------------------------------- messages
    def _decrypt_message(self, row: dict | None) -> dict | None:
        if row is not None:
            row["content"] = self._decrypt(row.get("content"))
            row["reasoning"] = self._decrypt(row.get("reasoning"))
            row["tool_events"] = _loads(self._decrypt(row.get("tool_events")), [])
            row["attachments"] = _loads(self._decrypt(row.get("attachments")), [])
            row.setdefault("versions", [])
            row.setdefault("active_version_id", "")
        return row

    def _decrypt_version(self, row: dict | None) -> dict | None:
        if row is not None:
            row["content"] = self._decrypt(row.get("content"))
            row["reasoning"] = self._decrypt(row.get("reasoning"))
            row["tool_events"] = _loads(self._decrypt(row.get("tool_events")), [])
            row["attachments"] = _loads(self._decrypt(row.get("attachments")), [])
        return row

    async def _versions_for(self, message_ids: list[str]) -> dict[str, list[dict]]:
        if not message_ids:
            return {}
        placeholders = ",".join("?" for _ in message_ids)
        rows = await self._fetchall(
            f"SELECT * FROM message_versions WHERE message_id IN ({placeholders})"
            " ORDER BY message_id ASC, version ASC",  # noqa: S608 - placeholders only
            tuple(message_ids),
        )
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            version = self._decrypt_version(row)
            if version is not None:
                grouped.setdefault(version["message_id"], []).append(version)
        return grouped

    async def list_messages(self, chat_id: str) -> list[dict]:
        rows = await self._fetchall(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY seq ASC", (chat_id,)
        )
        for row in rows:
            self._decrypt_message(row)
        versions = await self._versions_for([row["id"] for row in rows])
        for row in rows:
            row["versions"] = versions.get(row["id"], [])
        return rows

    async def get_message(self, message_id: str) -> dict | None:
        row = await self._fetchone("SELECT * FROM messages WHERE id = ?", (message_id,))
        if row is None:
            return None
        self._decrypt_message(row)
        versions = await self._versions_for([message_id])
        row["versions"] = versions.get(message_id, [])
        return row

    async def add_message(
        self,
        chat_id: str,
        role: str,
        content: str = "",
        reasoning: str = "",
        tool_events: list[dict] | None = None,
        attachments: list[dict] | None = None,
        source: str = "original",
        reply_to_version_id: str = "",
        status: str = "complete",
    ) -> dict:
        row = await self._fetchone(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM messages WHERE chat_id = ?", (chat_id,)
        )
        seq = int(row["next"] if row else 1)
        message_id = new_id("m")
        version_id = new_id("v")
        stamp = now()
        if source not in {"original", "edit", "regenerate", "draft"}:
            source = "original"
        if status not in {"complete", "streaming", "error"}:
            status = "complete"
        await self.conn.execute(
            """INSERT INTO messages
               (id,chat_id,role,content,reasoning,tool_events,attachments,
                duration_ms,seq,created_at,active_version_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                message_id,
                chat_id,
                role,
                self._encrypt(content),
                self._encrypt(reasoning),
                self._encrypt(_json(tool_events or [])),
                self._encrypt(_json(attachments or [])),
                0,
                seq,
                stamp,
                version_id,
            ),
        )
        await self.conn.execute(
            """INSERT INTO message_versions
               (id,message_id,version,content,reasoning,tool_events,attachments,
                duration_ms,status,source,reply_to_version_id,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                version_id,
                message_id,
                1,
                self._encrypt(content),
                self._encrypt(reasoning),
                self._encrypt(_json(tool_events or [])),
                self._encrypt(_json(attachments or [])),
                0,
                status,
                source,
                reply_to_version_id,
                stamp,
            ),
        )
        await self.conn.commit()
        await self.touch_chat(chat_id)
        return await self.get_message(message_id)  # type: ignore[return-value]

    async def update_message(
        self,
        message_id: str,
        content: str,
        reasoning: str = "",
        tool_events: list[dict] | None = None,
        duration_ms: int = 0,
    ) -> None:
        """Write the finished turn into the message's active version."""
        row = await self._fetchone(
            "SELECT active_version_id FROM messages WHERE id = ?", (message_id,)
        )
        version_id = (row or {}).get("active_version_id") or ""
        encrypted_content = self._encrypt(content)
        encrypted_reasoning = self._encrypt(reasoning)
        encrypted_tools = self._encrypt(_json(tool_events or []))
        if version_id:
            await self.conn.execute(
                """UPDATE message_versions
                   SET content = ?, reasoning = ?, tool_events = ?, duration_ms = ?,
                       status = 'complete'
                   WHERE id = ?""",
                (
                    encrypted_content,
                    encrypted_reasoning,
                    encrypted_tools,
                    duration_ms,
                    version_id,
                ),
            )
        await self.conn.execute(
            "UPDATE messages SET content = ?, reasoning = ?, tool_events = ?, duration_ms = ? WHERE id = ?",
            (
                encrypted_content,
                encrypted_reasoning,
                encrypted_tools,
                duration_ms,
                message_id,
            ),
        )
        await self.conn.commit()

    async def set_message_content(self, message_id: str, content: str) -> None:
        row = await self._fetchone(
            "SELECT active_version_id FROM messages WHERE id = ?", (message_id,)
        )
        version_id = (row or {}).get("active_version_id") or ""
        encrypted = self._encrypt(content)
        await self.conn.execute(
            "UPDATE messages SET content = ? WHERE id = ?", (encrypted, message_id)
        )
        if version_id:
            await self.conn.execute(
                "UPDATE message_versions SET content = ? WHERE id = ?",
                (encrypted, version_id),
            )
        await self.conn.commit()

    async def create_message_version(
        self,
        message_id: str,
        content: str = "",
        reasoning: str = "",
        tool_events: list[dict] | None = None,
        attachments: list[dict] | None = None,
        duration_ms: int = 0,
        source: str = "edit",
        reply_to_version_id: str = "",
        status: str = "complete",
        activate: bool = True,
    ) -> dict | None:
        """Append a new version to a message and optionally make it active."""
        message = await self.get_message(message_id)
        if message is None:
            return None
        if attachments is None:
            attachments = message.get("attachments") or []
        if source not in {"original", "edit", "regenerate", "draft"}:
            source = "edit"
        if status not in {"complete", "streaming", "error"}:
            status = "complete"
        version_id = new_id("v")
        stamp = now()
        # Allocate the next version number inside the same INSERT so concurrent
        # edits to one message cannot race on MAX(version) and collide on the
        # (message_id, version) uniqueness constraint. SQLite serializes writers,
        # so the second concurrent insert sees the first's row and bumps the
        # version instead of duplicating it.
        await self.conn.execute(
            """INSERT INTO message_versions
               (id,message_id,version,content,reasoning,tool_events,attachments,
                duration_ms,status,source,reply_to_version_id,created_at)
               SELECT ?, ?,
                      COALESCE((SELECT MAX(version) FROM message_versions
                                WHERE message_id = ?), 0) + 1,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?""",
            (
                version_id,
                message_id,
                message_id,
                self._encrypt(content),
                self._encrypt(reasoning),
                self._encrypt(_json(tool_events or [])),
                self._encrypt(_json(attachments)),
                duration_ms,
                status,
                source,
                reply_to_version_id,
                stamp,
            ),
        )
        if activate:
            await self.conn.execute(
                """UPDATE messages SET content = ?, reasoning = ?, tool_events = ?,
                       attachments = ?, duration_ms = ?, active_version_id = ?
                   WHERE id = ?""",
                (
                    self._encrypt(content),
                    self._encrypt(reasoning),
                    self._encrypt(_json(tool_events or [])),
                    self._encrypt(_json(attachments)),
                    duration_ms,
                    version_id,
                    message_id,
                ),
            )
        await self.conn.commit()
        await self.touch_chat(message["chat_id"])
        return await self.get_message(message_id)

    async def activate_message_version(self, message_id: str, version_id: str) -> dict | None:
        """Make one stored version the message's active content."""
        version = await self.get_message_version(version_id)
        if version is None or version["message_id"] != message_id:
            return None
        await self.conn.execute(
            """UPDATE messages SET content = ?, reasoning = ?, tool_events = ?,
                   attachments = ?, duration_ms = ?, active_version_id = ?
               WHERE id = ?""",
            (
                self._encrypt(version.get("content") or ""),
                self._encrypt(version.get("reasoning") or ""),
                self._encrypt(_json(version.get("tool_events") or [])),
                self._encrypt(_json(version.get("attachments") or [])),
                version.get("duration_ms") or 0,
                version_id,
                message_id,
            ),
        )
        await self.conn.commit()
        return await self.get_message(message_id)

    async def list_message_versions(self, message_id: str) -> list[dict]:
        versions = await self._versions_for([message_id])
        return versions.get(message_id, [])

    async def get_message_version(self, version_id: str) -> dict | None:
        row = await self._fetchone(
            "SELECT * FROM message_versions WHERE id = ?", (version_id,)
        )
        return self._decrypt_version(row)

    async def latest_version_for_reply(
        self, message_id: str, reply_to_version_id: str
    ) -> dict | None:
        row = await self._fetchone(
            """SELECT * FROM message_versions
               WHERE message_id = ? AND reply_to_version_id = ?
               ORDER BY version DESC LIMIT 1""",
            (message_id, reply_to_version_id),
        )
        return self._decrypt_version(row)

    async def next_message(self, chat_id: str, seq: int) -> dict | None:
        row = await self._fetchone(
            "SELECT * FROM messages WHERE chat_id = ? AND seq > ? ORDER BY seq ASC LIMIT 1",
            (chat_id, seq),
        )
        if row is None:
            return None
        self._decrypt_message(row)
        versions = await self._versions_for([row["id"]])
        row["versions"] = versions.get(row["id"], [])
        return row

    async def delete_messages_after(self, chat_id: str, seq: int) -> None:
        await self.conn.execute(
            "DELETE FROM messages WHERE chat_id = ? AND seq > ?", (chat_id, seq)
        )
        await self.conn.commit()

    async def last_assistant(self, chat_id: str) -> dict | None:
        row = await self._fetchone(
            "SELECT * FROM messages WHERE chat_id = ? AND role = 'assistant' ORDER BY seq DESC LIMIT 1",
            (chat_id,),
        )
        if row is None:
            return None
        self._decrypt_message(row)
        versions = await self._versions_for([row["id"]])
        row["versions"] = versions.get(row["id"], [])
        return row

    async def delete_message(self, message_id: str) -> None:
        await self.conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        await self.conn.commit()

    # ------------------------------------------------------------------ tasks
    async def list_tasks(self, chat_id: str) -> list[dict]:
        rows = await self._fetchall(
            "SELECT * FROM tasks WHERE chat_id = ? ORDER BY position ASC, created_at ASC",
            (chat_id,),
        )
        for row in rows:
            row["title"] = self._decrypt(row.get("title"))
            row["detail"] = self._decrypt(row.get("detail"))
        return rows

    async def create_task(
        self, chat_id: str, title: str, detail: str = "", status: str = "pending"
    ) -> dict:
        if status not in {"pending", "in_progress", "done", "blocked"}:
            status = "pending"
        row = await self._fetchone(
            "SELECT COALESCE(MAX(position), 0) + 1 AS next FROM tasks WHERE chat_id = ?",
            (chat_id,),
        )
        position = int(row["next"] if row else 1)
        task_id = new_id("t")
        stamp = now()
        await self.conn.execute(
            """INSERT INTO tasks (id,chat_id,title,detail,status,position,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                task_id,
                chat_id,
                self._encrypt(title.strip()[:300]),
                self._encrypt(detail.strip()[:2000]),
                status,
                position,
                stamp,
                stamp,
            ),
        )
        await self.conn.commit()
        return await self.get_task(task_id)  # type: ignore[return-value]

    async def get_task(self, task_id: str) -> dict | None:
        row = await self._fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row is not None:
            row["title"] = self._decrypt(row.get("title"))
            row["detail"] = self._decrypt(row.get("detail"))
        return row

    async def update_task(self, task_id: str, **fields: Any) -> dict | None:
        allowed = {"title", "detail", "status"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "status" in updates and updates["status"] not in {
            "pending",
            "in_progress",
            "done",
            "blocked",
        }:
            updates.pop("status")
        if not updates:
            return await self.get_task(task_id)
        for key in ("title", "detail"):
            if key in updates:
                updates[key] = self._encrypt(str(updates[key]))
        updates["updated_at"] = now()
        clause = ", ".join(f"{k} = ?" for k in updates)
        await self.conn.execute(
            f"UPDATE tasks SET {clause} WHERE id = ?",  # noqa: S608 - keys are whitelisted
            (*updates.values(), task_id),
        )
        await self.conn.commit()
        return await self.get_task(task_id)

    # ---------------------------------------------------------------- uploads
    async def add_upload(
        self,
        filename: str,
        mime: str,
        size: int,
        text_excerpt: str,
        chat_id: str | None = None,
    ) -> dict:
        upload_id = new_id("u")
        stamp = now()
        await self.conn.execute(
            """INSERT INTO uploads (id,chat_id,filename,mime,size,text_excerpt,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                upload_id,
                chat_id,
                self._encrypt(filename),
                mime,
                size,
                self._encrypt(text_excerpt[:100_000]),
                stamp,
            ),
        )
        await self.conn.commit()
        return {
            "id": upload_id,
            "name": filename,
            "mime": mime,
            "size": size,
            "created_at": stamp,
        }

    def _decrypt_upload(self, row: dict | None) -> dict | None:
        if row is not None:
            row["filename"] = self._decrypt(row.get("filename"))
            row["text_excerpt"] = self._decrypt(row.get("text_excerpt"))
        return row

    async def get_upload(self, upload_id: str) -> dict | None:
        return self._decrypt_upload(
            await self._fetchone("SELECT * FROM uploads WHERE id = ?", (upload_id,))
        )

    async def get_upload_by_name(self, filename: str) -> dict | None:
        for row in await self.list_uploads():
            if row.get("filename") == filename:
                return row
        return None

    async def list_uploads(self) -> list[dict]:
        rows = await self._fetchall("SELECT * FROM uploads ORDER BY created_at DESC")
        return [self._decrypt_upload(row) for row in rows]  # type: ignore[misc]

    # --------------------------------------------------------------- settings
    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self._fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        return self._decrypt(row["value"]) if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.conn.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, self._encrypt(value)),
        )
        await self.conn.commit()

    async def delete_setting(self, key: str) -> None:
        await self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        await self.conn.commit()

    async def all_settings(self) -> dict[str, str]:
        rows = await self._fetchall("SELECT key, value FROM settings")
        return {row["key"]: self._decrypt(row["value"]) for row in rows}

    # ---------------------------------------------------------------- user notes
    async def list_notes(self) -> list[dict]:
        rows = await self._fetchall("SELECT * FROM user_notes ORDER BY key ASC")
        for row in rows:
            row["value"] = self._decrypt(row.get("value"))
        return rows

    async def get_note(self, key: str) -> dict | None:
        row = await self._fetchone(
            "SELECT * FROM user_notes WHERE key = ?", (key.strip().lower(),)
        )
        if row is not None:
            row["value"] = self._decrypt(row.get("value"))
        return row

    async def set_note(self, key: str, value: str) -> dict:
        key = key.strip().lower()
        value = value.strip()
        if not key or not value:
            raise ValueError("Key and value are required.")
        if len(key) > NOTE_KEY_MAX:
            raise ValueError(f"Key is too long (max {NOTE_KEY_MAX} characters).")
        if len(value) > NOTE_VALUE_MAX:
            raise ValueError(f"Value is too long (max {NOTE_VALUE_MAX} characters).")
        if not NOTE_KEY_PATTERN.fullmatch(key):
            raise ValueError(
                "Keys must be lowercase with only letters, numbers, dashes, and underscores."
            )
        stamp = now()
        existing = await self.get_note(key)
        if existing:
            await self.conn.execute(
                "UPDATE user_notes SET value = ?, updated_at = ? WHERE key = ?",
                (self._encrypt(value), stamp, key),
            )
        else:
            note_id = new_id("n")
            await self.conn.execute(
                """INSERT INTO user_notes (id,key,value,created_at,updated_at)
                   VALUES (?,?,?,?,?)""",
                (note_id, key, self._encrypt(value), stamp, stamp),
            )
        await self.conn.commit()
        return await self.get_note(key)  # type: ignore[return-value]

    async def delete_note(self, key: str) -> None:
        await self.conn.execute(
            "DELETE FROM user_notes WHERE key = ?", (key.strip().lower(),)
        )
        await self.conn.commit()

    # ---------------------------------------------------------------- custom models
    async def list_custom_models(self) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM custom_models ORDER BY name ASC"
        )

    async def get_custom_model(self, model_id: str) -> dict | None:
        return await self._fetchone(
            "SELECT * FROM custom_models WHERE model_id = ?", (model_id,)
        )

    async def add_custom_model(self, name: str, model_id: str) -> dict | None:
        existing = await self.get_custom_model(model_id)
        if existing:
            return None
        model_id_clean = model_id.strip()
        name_clean = name.strip()
        if not model_id_clean or not name_clean:
            return None
        stamp = now()
        model_record_id = new_id("cm")
        await self.conn.execute(
            """INSERT INTO custom_models (id,name,model_id,created_at)
               VALUES (?,?,?,?)""",
            (model_record_id, name_clean, model_id_clean, stamp),
        )
        await self.conn.commit()
        return await self.get_custom_model(model_id_clean)

    async def delete_custom_model(self, model_id: str) -> None:
        await self.conn.execute(
            "DELETE FROM custom_models WHERE model_id = ?", (model_id,)
        )
        await self.conn.commit()
