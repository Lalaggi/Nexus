"""SQLite persistence. Small, single-user, and deliberately boring."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

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
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, seq);

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


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

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
        await conn.commit()
        self._conn = conn

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
                   (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.id) AS message_count,
                   (SELECT m.content FROM messages m
                     WHERE m.chat_id = c.id AND m.role = 'user'
                     ORDER BY m.seq DESC LIMIT 1) AS preview
            FROM chats c
            ORDER BY c.updated_at DESC
            """
        )
        for row in rows:
            row["preview"] = (row.get("preview") or "").strip().replace("\n", " ")[:120]
        return rows

    async def create_chat(self, title: str, goal: str = "", model: str = "nemotron-3.5-super-vl") -> dict:
        chat_id = new_id("c")
        stamp = now()
        await self.conn.execute(
            "INSERT INTO chats (id,title,goal,model,provider,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (chat_id, title, goal, model, "auto", stamp, stamp),
        )
        await self.conn.commit()
        return await self.get_chat(chat_id)  # type: ignore[return-value]

    async def get_chat(self, chat_id: str) -> dict | None:
        return await self._fetchone("SELECT * FROM chats WHERE id = ?", (chat_id,))

    async def update_chat(self, chat_id: str, **fields: Any) -> None:
        allowed = {"title", "goal", "model", "provider"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return
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
        await self.conn.execute("DELETE FROM uploads WHERE chat_id = ?", (chat_id,))
        await self.conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        await self.conn.commit()

    # --------------------------------------------------------------- messages
    async def list_messages(self, chat_id: str) -> list[dict]:
        rows = await self._fetchall(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY seq ASC", (chat_id,)
        )
        for row in rows:
            row["tool_events"] = _loads(row.get("tool_events"), [])
            row["attachments"] = _loads(row.get("attachments"), [])
        return rows

    async def add_message(
        self,
        chat_id: str,
        role: str,
        content: str = "",
        reasoning: str = "",
        tool_events: list[dict] | None = None,
        attachments: list[dict] | None = None,
    ) -> dict:
        row = await self._fetchone(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM messages WHERE chat_id = ?", (chat_id,)
        )
        seq = int(row["next"] if row else 1)
        message_id = new_id("m")
        stamp = now()
        await self.conn.execute(
            """INSERT INTO messages
               (id,chat_id,role,content,reasoning,tool_events,attachments,seq,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                message_id,
                chat_id,
                role,
                content,
                reasoning,
                _json(tool_events or []),
                _json(attachments or []),
                seq,
                stamp,
            ),
        )
        await self.conn.commit()
        await self.touch_chat(chat_id)
        return {
            "id": message_id,
            "chat_id": chat_id,
            "role": role,
            "content": content,
            "reasoning": reasoning,
            "tool_events": tool_events or [],
            "attachments": attachments or [],
            "seq": seq,
            "created_at": stamp,
        }

    async def update_message(
        self,
        message_id: str,
        content: str,
        reasoning: str = "",
        tool_events: list[dict] | None = None,
        duration_ms: int = 0,
    ) -> None:
        await self.conn.execute(
            "UPDATE messages SET content = ?, reasoning = ?, tool_events = ?, duration_ms = ? WHERE id = ?",
            (content, reasoning, _json(tool_events or []), duration_ms, message_id),
        )
        await self.conn.commit()

    async def delete_messages_after(self, chat_id: str, seq: int) -> None:
        await self.conn.execute(
            "DELETE FROM messages WHERE chat_id = ? AND seq > ?", (chat_id, seq)
        )
        await self.conn.commit()

    async def last_assistant(self, chat_id: str) -> dict | None:
        return await self._fetchone(
            "SELECT * FROM messages WHERE chat_id = ? AND role = 'assistant' ORDER BY seq DESC LIMIT 1",
            (chat_id,),
        )

    async def delete_message(self, message_id: str) -> None:
        await self.conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        await self.conn.commit()

    # ------------------------------------------------------------------ tasks
    async def list_tasks(self, chat_id: str) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM tasks WHERE chat_id = ? ORDER BY position ASC, created_at ASC",
            (chat_id,),
        )

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
            (task_id, chat_id, title.strip()[:300], detail.strip()[:2000], status, position, stamp, stamp),
        )
        await self.conn.commit()
        return await self.get_task(task_id)  # type: ignore[return-value]

    async def get_task(self, task_id: str) -> dict | None:
        return await self._fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))

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
            (upload_id, chat_id, filename, mime, size, text_excerpt[:100_000], stamp),
        )
        await self.conn.commit()
        return {
            "id": upload_id,
            "name": filename,
            "mime": mime,
            "size": size,
            "created_at": stamp,
        }

    async def get_upload(self, upload_id: str) -> dict | None:
        return await self._fetchone("SELECT * FROM uploads WHERE id = ?", (upload_id,))

    async def get_upload_by_name(self, filename: str) -> dict | None:
        return await self._fetchone("SELECT * FROM uploads WHERE filename = ?", (filename,))

    async def list_uploads(self) -> list[dict]:
        return await self._fetchall("SELECT * FROM uploads ORDER BY created_at DESC")

    # --------------------------------------------------------------- settings
    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self._fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.conn.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )
        await self.conn.commit()

    async def delete_setting(self, key: str) -> None:
        await self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        await self.conn.commit()

    async def all_settings(self) -> dict[str, str]:
        rows = await self._fetchall("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in rows}

    # ---------------------------------------------------------------- user notes
    async def list_notes(self) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM user_notes ORDER BY key ASC"
        )

    async def get_note(self, key: str) -> dict | None:
        return await self._fetchone("SELECT * FROM user_notes WHERE key = ?", (key,))

    async def set_note(self, key: str, value: str) -> dict:
        key = key.strip().lower()
        value = value.strip()
        stamp = now()
        existing = await self.get_note(key)
        if existing:
            await self.conn.execute(
                "UPDATE user_notes SET value = ?, updated_at = ? WHERE key = ?",
                (value, stamp, key),
            )
        else:
            note_id = new_id("n")
            await self.conn.execute(
                """INSERT INTO user_notes (id,key,value,created_at,updated_at)
                   VALUES (?,?,?,?,?)""",
                (note_id, key, value, stamp, stamp),
            )
        await self.conn.commit()
        return await self.get_note(key)  # type: ignore[return-value]

    async def delete_note(self, key: str) -> None:
        await self.conn.execute("DELETE FROM user_notes WHERE key = ?", (key,))
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
