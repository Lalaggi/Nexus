"""User notes CRUD endpoints used by Settings and the assistant tools."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/notes", tags=["notes"])


def db_of(request: Request):
    return request.app.state.db


class NoteBody(BaseModel):
    key: str
    value: str


class NoteValueBody(BaseModel):
    value: str


def _clean_key(key: str) -> str:
    return key.strip().lower()


@router.get("")
async def list_notes(request: Request):
    return await db_of(request).list_notes()


@router.get("/{key:path}")
async def get_note(key: str, request: Request):
    note = await db_of(request).get_note(_clean_key(key))
    if note is None:
        raise HTTPException(404, "Note not found.")
    return note


@router.post("", status_code=201)
async def create_note(request: Request, body: NoteBody):
    try:
        return await db_of(request).set_note(body.key, body.value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/{key:path}")
async def update_note(key: str, request: Request, body: NoteValueBody):
    db = db_of(request)
    cleaned = _clean_key(key)
    if await db.get_note(cleaned) is None:
        raise HTTPException(404, "Note not found.")
    try:
        return await db.set_note(cleaned, body.value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/{key:path}")
async def delete_note(key: str, request: Request):
    db = db_of(request)
    cleaned = _clean_key(key)
    if await db.get_note(cleaned) is None:
        raise HTTPException(404, "Note not found.")
    await db.delete_note(cleaned)
    return {"ok": True}
