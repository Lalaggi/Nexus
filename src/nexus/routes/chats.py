"""Chat, message, and task endpoints."""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent import RUNS, run_turn, start_run
from ..config import CONFIG
from ..db import Database, now
from ..providers import DEFAULT_MODEL, ProviderError, resolve_provider

router = APIRouter(prefix="/api", tags=["chats"])


def db_of(request: Request) -> Database:
    return request.app.state.db


class ChatCreate(BaseModel):
    title: str | None = None
    model: str | None = None


class ChatPatch(BaseModel):
    title: str | None = None
    goal: str | None = None
    model: str | None = None


class SendMessage(BaseModel):
    content: str = ""
    attachment_ids: list[str] = Field(default_factory=list)
    model: str | None = None


class TaskPatch(BaseModel):
    status: str | None = None
    title: str | None = None
    detail: str | None = None


class MessagePatch(BaseModel):
    content: str | None = None


def _title_from(content: str, attachments: list[dict]) -> str:
    line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    if not line and attachments:
        line = f"Analyze {attachments[0]['name']}"
    if not line:
        return "New chat"
    return line[:70] + ("…" if len(line) > 70 else "")


@router.get("/chats")
async def list_chats(request: Request) -> list[dict]:
    return await db_of(request).list_chats()


@router.post("/chats")
async def create_chat(request: Request, body: ChatCreate | None = None) -> dict:
    db = db_of(request)
    title = ((body.title if body else None) or "New chat").strip()[:120]
    model = (body.model if body else None) or DEFAULT_MODEL
    return await db.create_chat(title, model=model)


@router.get("/chats/{chat_id}")
async def get_chat(request: Request, chat_id: str) -> dict:
    db = db_of(request)
    chat = await db.get_chat(chat_id)
    if chat is None:
        raise HTTPException(404, "Chat not found")
    return {
        "chat": chat,
        "messages": await db.list_messages(chat_id),
        "tasks": await db.list_tasks(chat_id),
    }


@router.patch("/chats/{chat_id}")
async def patch_chat(request: Request, chat_id: str, body: ChatPatch) -> dict:
    db = db_of(request)
    if await db.get_chat(chat_id) is None:
        raise HTTPException(404, "Chat not found")
    await db.update_chat(chat_id, **body.model_dump(exclude_none=True))
    return await db.get_chat(chat_id)  # type: ignore[return-value]


@router.delete("/chats/{chat_id}")
async def delete_chat(request: Request, chat_id: str) -> dict:
    db = db_of(request)
    if await db.get_chat(chat_id) is None:
        raise HTTPException(404, "Chat not found")
    await db.delete_chat(chat_id)
    for directory in (
        CONFIG.chat_workspace_dir(chat_id),
        CONFIG.chat_outputs_dir(chat_id),
        CONFIG.chat_uploads_dir(chat_id),
    ):
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
    return {"ok": True}


@router.get("/chats/{chat_id}/tasks")
async def list_tasks(request: Request, chat_id: str) -> dict:
    db = db_of(request)
    chat = await db.get_chat(chat_id)
    if chat is None:
        raise HTTPException(404, "Chat not found")
    return {"tasks": await db.list_tasks(chat_id), "goal": chat.get("goal", "")}


@router.patch("/tasks/{task_id}")
async def patch_task(request: Request, task_id: str, body: TaskPatch) -> dict:
    db = db_of(request)
    task = await db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    updated = await db.update_task(task_id, **body.model_dump(exclude_none=True))
    return {"task": updated, "tasks": await db.list_tasks(task["chat_id"])}


def _sse_stream(
    request: Request,
    chat_id: str,
    assistant_id: str,
    state,
    model_id: str | None = None,
    first_event: dict | None = None,
) -> StreamingResponse:
    async def generator():
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def emit(event: dict) -> None:
            await queue.put(event)

        task = asyncio.create_task(
            run_turn(db_of(request), chat_id, assistant_id, emit, state, model_id=model_id)
        )

        try:
            if first_event is not None:
                yield f"data: {json.dumps(first_event, ensure_ascii=False)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    if await request.is_disconnected():
                        state.cancel.set()
                        task.cancel()
                        break
                    yield ": ping\n\n"
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done":
                    break
        finally:
            if not task.done():
                state.cancel.set()
                task.cancel()
            try:
                await asyncio.shield(task)
            except (asyncio.CancelledError, Exception):
                pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _prepare_attachments(db: Database, ids: list[str], chat_id: str | None = None) -> list[dict]:
    attachments = []
    for upload_id in ids[:10]:
        upload = await db.get_upload(upload_id)
        if upload is None:
            continue
        upload_chat_id = upload.get("chat_id")

        # If the upload has no chat_id yet, it lives in the temp directory.
        # Move it to this chat's per-chat uploads dir and update the record.
        if upload_chat_id is None and chat_id is not None:
            src = CONFIG.tempuploads_dir / upload["filename"]
            dst_dir = CONFIG.chat_uploads_dir(chat_id)
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / upload["filename"]
            if src.is_file():
                src.replace(dst)
            await db.conn.execute(
                "UPDATE uploads SET chat_id = ? WHERE id = ?",
                (chat_id, upload_id),
            )
            await db.conn.commit()
            upload_chat_id = chat_id

        if upload_chat_id:
            url = f"/api/files/chats/{quote(str(upload_chat_id))}/uploads/{quote(upload['filename'])}"
        else:
            url = f"/api/files/uploads/{quote(upload['filename'])}"
        attachments.append(
            {
                "id": upload["id"],
                "name": upload["filename"],
                "mime": upload["mime"],
                "size": upload["size"],
                "url": url,
            }
        )
    return attachments


@router.post("/chats/{chat_id}/messages")
async def send_message(request: Request, chat_id: str, body: SendMessage):
    db = db_of(request)
    chat = await db.get_chat(chat_id)
    if chat is None:
        raise HTTPException(404, "Chat not found")
    if chat_id in RUNS:
        raise HTTPException(409, "This conversation is already generating a response.")
    attachments = await _prepare_attachments(db, body.attachment_ids, chat_id)
    if not body.content.strip() and not attachments:
        raise HTTPException(400, "Message is empty.")

    # Remember the model choice on the chat so it persists across turns.
    selected_model = body.model or chat.get("model") or DEFAULT_MODEL
    if selected_model != chat.get("model"):
        await db.update_chat(chat_id, model=selected_model)

    try:
        resolved = await resolve_provider(db, selected_model, chat.get("provider"))
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc

    user_message = await db.add_message(
        chat_id, "user", body.content.strip(), attachments=attachments
    )
    if chat.get("title") in {"", "New chat"}:
        await db.update_chat(chat_id, title=_title_from(body.content, attachments))
        chat = await db.get_chat(chat_id)
    nexus = await db.add_message(chat_id, "nexus", "")
    state = start_run(chat_id)
    return _sse_stream(
        request,
        chat_id,
        nexus["id"],
        state,
        model_id=selected_model,
        first_event={
            "type": "user_message",
            "message": user_message,
            "chat": chat,
            "provider": resolved.provider.id,
            "provider_label": resolved.provider.label,
            "model": resolved.name,
            "model_id": resolved.model_id,
        },
    )


@router.post("/chats/{chat_id}/regenerate")
async def regenerate(request: Request, chat_id: str):
    db = db_of(request)
    chat = await db.get_chat(chat_id)
    if chat is None:
        raise HTTPException(404, "Chat not found")
    if chat_id in RUNS:
        raise HTTPException(409, "This conversation is already generating a response.")
    messages = await db.list_messages(chat_id)
    if not messages:
        raise HTTPException(400, "Nothing to regenerate.")

    last_user_index = None
    for index in range(len(messages) - 1, -1, -1):
        if messages[index]["role"] == "user":
            last_user_index = index
            break
    if last_user_index is None:
        raise HTTPException(400, "No user message to regenerate from.")
    for message in messages[last_user_index + 1 :]:
        await db.delete_message(message["id"])

    nexus = await db.add_message(chat_id, "nexus", "")
    state = start_run(chat_id)
    return _sse_stream(
        request,
        chat_id,
        nexus["id"],
        state,
        model_id=chat.get("model") or DEFAULT_MODEL,
    )


@router.patch("/messages/{message_id}")
async def patch_message(message_id: str, body: MessagePatch, request: Request):
    db = db_of(request)
    message = await db.get_message(message_id)
    if message is None:
        raise HTTPException(404, "Message not found")
    if message["role"] != "nexus":
        raise HTTPException(400, "Only nexus messages can be edited.")
    if body.content is None:
        raise HTTPException(400, "Content is required.")
    await db.set_message_content(message_id, body.content.strip())
    await db.touch_chat(message["chat_id"])
    return {"ok": True, "message_id": message_id}


@router.post("/chats/{chat_id}/stop")
async def stop_chat(chat_id: str):
    from ..agent import cancel_run

    return {"stopped": cancel_run(chat_id)}


@router.get("/models")
async def models(request: Request) -> dict:
    from ..providers import MODELS, api_keys

    db = db_of(request)
    keys = await api_keys(db)
    return {
        "models": [
            {
                "id": model.id,
                "name": model.name,
                "subtitle": model.subtitle,
                "description": model.description,
                "providers": [
                    {
                        "id": spec.id,
                        "label": spec.label,
                        "model_id": spec.model_id,
                        "available": bool(keys.get(spec.id)),
                    }
                    for spec in model.providers.values()
                ],
            }
            for model in MODELS
        ]
    }
