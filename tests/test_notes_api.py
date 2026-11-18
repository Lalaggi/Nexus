from __future__ import annotations

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from nexus.crypto import Cipher
from nexus.db import Database
from nexus.routes import notes


@pytest.fixture
async def client(tmp_path):
    app = FastAPI()
    app.include_router(notes.router)
    db = Database(tmp_path / "nexus.db", cipher=Cipher(Fernet.generate_key()))
    await db.connect()
    app.state.db = db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    await db.close()


async def test_notes_crud(client):
    response = await client.get("/api/notes")
    assert response.status_code == 200
    assert response.json() == []

    response = await client.post("/api/notes", json={"key": "Editor", "value": "Neovim"})
    assert response.status_code == 201
    created = response.json()
    assert created["key"] == "editor"
    assert created["value"] == "Neovim"

    response = await client.get("/api/notes/editor")
    assert response.status_code == 200
    assert response.json()["value"] == "Neovim"

    response = await client.patch("/api/notes/editor", json={"value": "Helix"})
    assert response.status_code == 200
    assert response.json()["value"] == "Helix"

    response = await client.get("/api/notes")
    assert [note["key"] for note in response.json()] == ["editor"]

    response = await client.delete("/api/notes/editor")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert (await client.get("/api/notes")).json() == []


async def test_notes_validation_and_missing_keys(client):
    for key in ("", "bad key", "emoji-😀", "x" * 61):
        response = await client.post("/api/notes", json={"key": key, "value": "value"})
        assert response.status_code == 400

    response = await client.post("/api/notes", json={"key": "ok", "value": ""})
    assert response.status_code == 400

    response = await client.patch("/api/notes/missing", json={"value": "value"})
    assert response.status_code == 404

    response = await client.delete("/api/notes/missing")
    assert response.status_code == 404
