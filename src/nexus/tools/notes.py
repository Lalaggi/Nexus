"""User notes: a small, durable memory the nexus can use to remember
preferences (e.g. a preferred editor) across conversations. Notes are user-level,
not per-chat, and should only be written for important, lasting facts."""

from __future__ import annotations

import re

from ..config import CONFIG
from .base import Tool, ToolContext, ToolResult, register

NOTE_KEY_MAX = 60
NOTE_VALUE_MAX = 1000

NOTE_LIST_PARAMETERS = {"type": "object", "properties": {}, "required": []}


async def note_list(ctx: ToolContext, args: dict) -> ToolResult:
    notes = await ctx.db.list_notes()
    if not notes:
        return ToolResult(content="No user notes yet.", summary="No notes")
    lines = [f"- {note['key']}: {note['value']}" for note in notes]
    return ToolResult(
        content="User notes:\n" + "\n".join(lines),
        summary=f"{len(notes)} note(s)",
        data={"notes": notes},
    )


NOTE_GET_PARAMETERS = {
    "type": "object",
    "properties": {
        "key": {
            "type": "string",
            "description": "The note key to read (lowercase, e.g. 'editor').",
        },
    },
    "required": ["key"],
}


async def note_get(ctx: ToolContext, args: dict) -> ToolResult:
    key = str(args.get("key", "")).strip().lower()
    if not key:
        return ToolResult(content="A note key is required.", ok=False)
    note = await ctx.db.get_note(key)
    if not note:
        return ToolResult(content=f"No note found for key '{key}'.", ok=False, summary="Not found")
    return ToolResult(
        content=f"{note['key']}: {note['value']}",
        summary=f"Note {note['key']}",
        data={"key": note["key"], "value": note["value"]},
    )


NOTE_SET_PARAMETERS = {
    "type": "object",
    "properties": {
        "key": {
            "type": "string",
            "description": (
                "A short lowercase key for the fact, e.g. 'editor', 'os', "
                "'preferred_editor'. Only letters, numbers, dashes, and underscores."
            ),
        },
        "value": {
            "type": "string",
            "description": "The durable fact to remember, in one short sentence.",
        },
    },
    "required": ["key", "value"],
}


async def note_set(ctx: ToolContext, args: dict) -> ToolResult:
    key = str(args.get("key", "")).strip().lower()
    value = str(args.get("value", "")).strip()
    if not key or not value:
        return ToolResult(content="Both key and value are required.", ok=False)
    if len(key) > NOTE_KEY_MAX:
        return ToolResult(content=f"Key is too long (max {NOTE_KEY_MAX} chars).", ok=False)
    if len(value) > NOTE_VALUE_MAX:
        return ToolResult(content=f"Value is too long (max {NOTE_VALUE_MAX} chars).", ok=False)
    if not re.fullmatch(r"[a-z0-9_-]+", key):
        return ToolResult(
            content="Keys must be lowercase with only letters, numbers, dashes, and underscores.",
            ok=False,
        )

    note = await ctx.db.set_note(key, value)
    return ToolResult(
        content=f"Remembered: {note['key']} = {note['value']}",
        summary=f"Note {note['key']} saved",
        data={"key": note["key"], "value": note["value"]},
    )


NOTE_DELETE_PARAMETERS = {
    "type": "object",
    "properties": {
        "key": {
            "type": "string",
            "description": "The note key to remove.",
        },
    },
    "required": ["key"],
}


async def note_delete(ctx: ToolContext, args: dict) -> ToolResult:
    key = str(args.get("key", "")).strip().lower()
    if not key:
        return ToolResult(content="A note key is required.", ok=False)
    existing = await ctx.db.get_note(key)
    if not existing:
        return ToolResult(content=f"No note found for key '{key}'.", ok=False, summary="Not found")
    await ctx.db.delete_note(key)
    return ToolResult(
        content=f"Removed note '{key}'.",
        summary=f"Note {key} removed",
    )


register(
    Tool(
        name="note_list",
        description="Read all saved user notes. Use this to recall preferences the nexus has learned.",
        parameters=NOTE_LIST_PARAMETERS,
        handler=note_list,
    )
)
register(
    Tool(
        name="note_get",
        description="Read a single saved user note by key.",
        parameters=NOTE_GET_PARAMETERS,
        handler=note_get,
    )
)
register(
    Tool(
        name="note_set",
        description=(
            "Save a durable user note. Only use this for important, lasting facts about the user "
            "(for example, a preferred editor or operating system). Do not save trivial or "
            "conversation-specific details."
        ),
        parameters=NOTE_SET_PARAMETERS,
        handler=note_set,
    )
)
register(
    Tool(
        name="note_delete",
        description="Remove a saved user note by key.",
        parameters=NOTE_DELETE_PARAMETERS,
        handler=note_delete,
    )
)
