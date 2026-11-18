"""Tool registry and the shared execution context."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..db import Database


@dataclass
class ToolResult:
    content: str
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    ok: bool = True

    def as_message(self) -> str:
        return self.content


@dataclass
class ToolContext:
    chat_id: str
    db: Database
    emit: Callable[[dict], Awaitable[None]] | None = None

    async def notify(self, event: dict) -> None:
        if self.emit is not None:
            await self.emit(event)

    async def notify_tasks(self) -> None:
        tasks = await self.db.list_tasks(self.chat_id)
        chat = await self.db.get_chat(self.chat_id)
        await self.notify({"type": "tasks", "tasks": tasks, "goal": (chat or {}).get("goal", "")})


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict], Awaitable[ToolResult]]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _REGISTRY[tool.name] = tool
    return tool


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def schemas(enabled: set[str] | None = None) -> list[dict]:
    return [t.schema() for t in _REGISTRY.values() if enabled is None or t.name in enabled]


async def execute(name: str, raw_args: str | dict, ctx: ToolContext) -> ToolResult:
    tool = _REGISTRY.get(name)
    if tool is None:
        return ToolResult(
            content=f"Unknown tool: {name}. Available tools: {', '.join(sorted(_REGISTRY))}",
            ok=False,
            summary="Unknown tool",
        )
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError as exc:
            return ToolResult(
                content=f"Invalid JSON arguments for {name}: {exc}", ok=False, summary="Bad arguments"
            )
    else:
        args = raw_args
    if not isinstance(args, dict):
        return ToolResult(content=f"Arguments for {name} must be an object.", ok=False)

    try:
        return await tool.handler(ctx, args)
    except Exception as exc:  # tool failures must never kill the stream
        return ToolResult(
            content=f"{name} failed: {type(exc).__name__}: {exc}",
            ok=False,
            summary="Tool failed",
        )


def load_builtin_tools() -> None:
    from . import files, notes, sandbox, search, tasks, webfetch  # noqa: F401
