"""The streaming tool-use loop."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import CONFIG
from .db import Database
from .prompt import system_prompt
from .providers import (
    CuratedModel,
    ProviderError,
    StreamClient,
    extract_delta,
    resolve_provider,
)
from .tools.base import ToolContext, execute, schemas

Emit = Callable[[dict], Awaitable[None]]


def _extract_user_text(history: list[dict]) -> str:
    """Get the latest user message text from history."""
    for message in reversed(history):
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
    return ""


async def _generate_title(
    client: StreamClient,
    model: CuratedModel,
    user_content: str,
    assistant_content: str,
) -> str:
    """Generate a short, descriptive chat title (3-6 words) from the conversation."""
    prompt = (
        "Generate a short, descriptive chat title for this conversation. "
        "Rules: 3-6 words, no quotes, no punctuation at the end, no labels like "
        "'Title:', just the title text. Use sentence case.\n\n"
        f"User: {user_content[:400]}\n"
        f"Nexus: {assistant_content[:400]}"
    )
    chunks: list[str] = []
    try:
        async for chunk in client.stream(
            [{"role": "user", "content": prompt}], None, tool_choice=None
        ):
            text, _reasoning, _deltas, _finish, _usage = extract_delta(chunk)
            if text:
                chunks.append(text)
    except Exception:
        return "New chat"
    title = "".join(chunks).strip()
    title = title.strip('"').strip("'").strip()
    title = title.split("\n")[0].strip()
    if len(title) > 80:
        title = title[:80].strip()
    return title or "New chat"


@dataclass
class RunState:
    chat_id: str
    cancel: asyncio.Event = field(default_factory=asyncio.Event)


RUNS: dict[str, RunState] = {}


def start_run(chat_id: str) -> RunState:
    state = RunState(chat_id=chat_id)
    RUNS[chat_id] = state
    return state


def finish_run(chat_id: str) -> None:
    RUNS.pop(chat_id, None)


def cancel_run(chat_id: str) -> bool:
    state = RUNS.get(chat_id)
    if state is None:
        return False
    state.cancel.set()
    return True


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


async def build_context(db: Database, chat_id: str, skip_ids: set[str] | None = None) -> list[dict]:
    skip_ids = skip_ids or set()
    rows = await db.list_messages(chat_id)
    messages: list[dict] = []
    images_left = 6

    for row in rows:
        if row["id"] in skip_ids or row["role"] not in {"user", "assistant"}:
            continue
        if row["role"] == "assistant":
            if row["content"].strip():
                messages.append({"role": "assistant", "content": row["content"]})
            continue

        text = row["content"].strip()
        parts: list[dict] = []
        notes: list[str] = []
        for attachment in row.get("attachments") or []:
            upload = await db.get_upload(str(attachment.get("id", "")))
            if upload is None:
                continue
            mime = upload.get("mime") or "application/octet-stream"
            name = upload.get("filename") or "file"
            if mime.startswith("image/") and images_left > 0:
                path = CONFIG.chat_uploads_dir(chat_id) / name
                if not path.is_file():
                    path = CONFIG.uploads_dir / name  # legacy attachment
                try:
                    raw = path.read_bytes()
                    if len(raw) <= 15_000_000:
                        encoded = base64.b64encode(raw).decode("ascii")
                        parts.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{encoded}"},
                            }
                        )
                        images_left -= 1
                except OSError:
                    notes.append(f"[Attached image {name} could not be read.]")
            elif mime.startswith("image/"):
                notes.append(f"[Attached image {name} omitted to keep the request small.]")
            else:
                excerpt = (upload.get("text_excerpt") or "").strip()
                if excerpt:
                    notes.append(
                        f"[Attached file: {name} ({mime})]\n{excerpt[:20_000]}\n[End of file]"
                    )
                else:
                    notes.append(
                        f"[Attached file: {name} ({mime}); no text preview is available. "
                        "It is in the uploads folder if you need to inspect it.]"
                    )

        full_text = text
        if notes:
            full_text = (full_text + "\n\n" if full_text else "") + "\n\n".join(notes)
        if parts:
            parts.insert(0, {"type": "text", "text": full_text or "Please look at the attached image."})
            messages.append({"role": "user", "content": parts})
        elif full_text.strip():
            messages.append({"role": "user", "content": full_text})

    # Keep the recent window. 350k characters is well inside the model's 1M-token context
    # and avoids sending a whole novel on every turn.
    selected: list[dict] = []
    chars = 0
    for message in reversed(messages):
        size = len(_text_of(message.get("content")))
        if len(selected) >= 70 or (chars + size > 350_000 and len(selected) >= 6):
            break
        selected.append(message)
        chars += size
    selected.reverse()

    # At most six images total, newest first.
    remaining = 6
    for message in reversed(selected):
        if isinstance(message.get("content"), list):
            rebuilt = []
            for part in message["content"]:
                if part.get("type") == "image_url":
                    if remaining > 0:
                        rebuilt.append(part)
                        remaining -= 1
                else:
                    rebuilt.append(part)
            message["content"] = rebuilt
    return selected


def _compact_data(name: str, data: dict) -> dict:
    if name == "web_search":
        return {"results": (data.get("results") or [])[:8], "query": data.get("query", "")}
    if name == "web_fetch":
        return {"url": data.get("url", ""), "title": data.get("title", "")}
    if name in {"sandbox", "run_python"}:
        return {
            "files": (data.get("files") or [])[:10],
            "exit_code": data.get("exit_code"),
            "stdout": data.get("stdout", "")[:6000],
            "stderr": data.get("stderr", "")[:6000],
        }
    if name == "write_file":
        return {
            "files": [
                {
                    "name": data.get("name", "file"),
                    "path": data.get("path", ""),
                    "url": data.get("url", ""),
                }
            ],
            "content": data.get("content", "")[:12_000],
        }
    if name == "read_file":
        return {
            "files": [
                {
                    "name": data.get("name", "file"),
                    "path": data.get("path", ""),
                    "url": data.get("url", ""),
                }
            ]
        }
    if name in {"task_create", "task_update"}:
        return {"task": data.get("task") or {}}
    if name == "task_list":
        return {"tasks": (data.get("tasks") or [])[:25]}
    if name == "set_goal":
        return {"goal": data.get("goal", "")}
    return {}


async def run_turn(
    db: Database,
    chat_id: str,
    assistant_message_id: str,
    emit: Emit,
    state: RunState,
    model_id: str | None = None,
) -> None:
    all_content: list[str] = []
    all_reasoning: list[str] = []
    tool_events: list[dict] = []
    usage: dict | None = None
    error_message: str | None = None
    cancelled = False
    started = time.monotonic()

    try:
        chat = await db.get_chat(chat_id)
        if chat is None:
            raise ProviderError("This conversation no longer exists.")
        resolved = await resolve_provider(db, model_id or chat.get("model"), chat.get("provider"))
        history = await build_context(db, chat_id, {assistant_message_id})
        user_notes = await db.list_notes()
        custom_instructions = await db.get_setting("custom_instructions", "")
        messages: list[dict] = [
            {"role": "system", "content": system_prompt(user_notes, custom_instructions)},
            *history,
        ]
        tools = schemas()
        client = StreamClient(resolved.provider, resolved.key)
        ctx = ToolContext(chat_id=chat_id, db=db, emit=emit)

        await emit(
            {
                "type": "meta",
                "message_id": assistant_message_id,
                "provider": resolved.provider.id,
                "provider_label": resolved.provider.label,
                "model": resolved.name,
                "model_id": resolved.model_id,
            }
        )

        def step_add_text(text: str) -> None:
            if not text:
                return
            if all_content:
                all_content[-1] += text
            else:
                all_content.append(text)

        for step in range(CONFIG.max_tool_steps):
            if state.cancel.is_set():
                cancelled = True
                break

            step_text: list[str] = []
            step_reasoning: list[str] = []
            calls: dict[int, dict] = {}

            async for chunk in client.stream(messages, tools, model_id=resolved.model_id):
                if state.cancel.is_set():
                    cancelled = True
                    break
                text, reasoning, deltas, _finish, chunk_usage = extract_delta(chunk)
                if chunk_usage:
                    usage = chunk_usage
                if text:
                    step_text.append(text)
                    await emit({"type": "delta", "text": text})
                if reasoning:
                    step_reasoning.append(reasoning)
                    await emit({"type": "reasoning", "text": reasoning})
                for delta in deltas:
                    index = int(delta.get("index", 0))
                    entry = calls.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    if delta.get("id"):
                        entry["id"] = delta["id"]
                    function = delta.get("function") or {}
                    if function.get("name") and not entry["name"]:
                        entry["name"] = function["name"]
                    if function.get("arguments"):
                        entry["arguments"] += function["arguments"]

            if step_text:
                step_add_text("".join(step_text))
            if step_reasoning:
                all_reasoning.append("".join(step_reasoning))
            if cancelled or state.cancel.is_set():
                cancelled = True
                break

            if not calls:
                break

            ordered = [calls[index] for index in sorted(calls)]
            assistant_calls = []
            for index, call in enumerate(ordered):
                call_id = call["id"] or f"call_{step}_{index}"
                call["id"] = call_id
                assistant_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"] or "{}",
                        },
                    }
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": "".join(step_text) or None,
                    "tool_calls": assistant_calls,
                }
            )

            for index, call in enumerate(ordered):
                name = call["name"]
                raw_args = call["arguments"] or "{}"
                try:
                    parsed_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed_args = raw_args

                await emit(
                    {
                        "type": "tool_call",
                        "id": call["id"],
                        "name": name,
                        "args": parsed_args,
                    }
                )
                tool_started = time.monotonic()
                result = await execute(name, raw_args, ctx)
                event = {
                    "id": call["id"],
                    "name": name,
                    "args": parsed_args if isinstance(parsed_args, dict) else {"raw": str(parsed_args)[:1000]},
                    "ok": result.ok,
                    "summary": result.summary,
                    "duration": round(time.monotonic() - tool_started, 2),
                    "data": _compact_data(name, result.data),
                }
                tool_events.append(event)
                await emit({"type": "tool_result", **{k: event[k] for k in ("id", "name", "ok", "summary", "duration", "data")}})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": name,
                        "content": result.content,
                    }
                )
                if state.cancel.is_set():
                    cancelled = True
                    break
            if cancelled:
                break
        else:
            # Tool budget exhausted: ask for a final answer with tools disabled.
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "The tool budget for this turn is exhausted. Answer now using everything "
                        "you have learned. Do not call more tools."
                    ),
                }
            )
            async for chunk in client.stream(messages, None, tool_choice=None):
                if state.cancel.is_set():
                    cancelled = True
                    break
                text, reasoning, _deltas, _finish, chunk_usage = extract_delta(chunk)
                if chunk_usage:
                    usage = chunk_usage
                if text:
                    await emit({"type": "delta", "text": text})
                    step_add_text(text)
                if reasoning:
                    await emit({"type": "reasoning", "text": reasoning})
                    all_reasoning.append(reasoning)

    except ProviderError as exc:
        error_message = str(exc)
        await emit({"type": "error", "message": error_message})
    except asyncio.CancelledError:
        cancelled = True
        raise
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        await emit({"type": "error", "message": error_message})
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        content = "".join(all_content).strip()
        reasoning = "\n\n".join(all_reasoning).strip()
        if not content and error_message:
            content = f"_Could not generate a response: {error_message}_"
        if not content and cancelled:
            content = "_Stopped._"
        try:
            await db.update_message(
                assistant_message_id, content, reasoning, tool_events, duration_ms=duration_ms
            )
            await db.touch_chat(chat_id)
        except Exception:
            pass

        # Generate a topic-based chat title on the first nexus turn.
        try:
            chat = await db.get_chat(chat_id)
            if chat and chat.get("title") in {"", "New chat"}:
                messages = await db.list_messages(chat_id)
                assistant_count = sum(1 for m in messages if m["role"] == "assistant")
                if assistant_count == 1:
                    user_content = _extract_user_text(history)
                    new_title = await _generate_title(
                        client, model, user_content, content
                    )
                    if new_title and new_title != "New chat":
                        await db.update_chat(chat_id, title=new_title)
                        await emit(
                            {
                                "type": "title",
                                "chat_id": chat_id,
                                "title": new_title,
                            }
                        )
        except Exception:
            pass

        try:
            await emit(
                {
                    "type": "done",
                    "message_id": assistant_message_id,
                    "content": content,
                    "reasoning": reasoning,
                    "tool_events": tool_events,
                    "duration_ms": duration_ms,
                    "usage": usage,
                    "cancelled": cancelled,
                }
            )
        except Exception:
            pass
        finish_run(chat_id)
