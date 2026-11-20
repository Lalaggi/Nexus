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

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from nexus.crypto import Cipher
from nexus.db import Database
from nexus.routes import chats


@pytest.fixture
async def client(tmp_path):
    app = FastAPI()
    app.include_router(chats.router)
    db = Database(tmp_path / "nexus.db", cipher=Cipher(Fernet.generate_key()))
    await db.connect()
    app.state.db = db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, db
    await db.close()


async def _seed(http, db, chat_id):
    user = await db.add_message(chat_id, "user", "ask A")
    assistant = await db.add_message(
        chat_id, "assistant", "reply A", reply_to_version_id=user["active_version_id"]
    )
    return user, assistant


async def test_version_list_create_and_activate(client):
    http, db = client
    chat = await http.post("/api/chats", json={"title": "c"})
    assert chat.status_code == 200, chat.text
    chat_id = chat.json()["id"]

    _user_msg, assistant = await _seed(http, db, chat_id)
    message_id = assistant["id"]
    active_version_id = assistant["active_version_id"]
    assert len(assistant["versions"]) == 1
    assert assistant["versions"][0]["version"] == 1
    assert assistant["versions"][0]["content"] == "reply A"

    listed = await http.get(
        f"/api/chats/{chat_id}/messages/{message_id}/versions"
    )
    assert listed.status_code == 200, listed.text
    data = listed.json()
    assert data["active_version_id"] == active_version_id
    assert [v["version"] for v in data["versions"]] == [1]

    created = await http.post(
        f"/api/chats/{chat_id}/messages/{message_id}/versions",
        json={"content": "edited reply"},
    )
    assert created.status_code == 200, created.text
    v2_id = created.json()["message"]["active_version_id"]
    assert v2_id != active_version_id
    assert len(created.json()["message"]["versions"]) == 2
    assert created.json()["message"]["content"] == "edited reply"

    activated = await http.post(
        f"/api/messages/{message_id}/versions/{active_version_id}/activate"
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["messages"][0]["active_version_id"] == active_version_id
    assert activated.json()["messages"][0]["content"] == "reply A"


async def test_editing_a_user_message_creates_a_version(client):
    http, db = client
    chat = await http.post("/api/chats", json={"title": "c"})
    chat_id = chat.json()["id"]
    user_msg, _assistant = await _seed(http, db, chat_id)
    message_id = user_msg["id"]

    edited = await http.patch(f"/api/messages/{message_id}", json={"content": "ask B"})
    assert edited.status_code == 200, edited.text
    message = edited.json()["message"]
    assert len(message["versions"]) == 2
    assert message["versions"][1]["source"] == "edit"
    assert message["versions"][1]["content"] == "ask B"
    assert message["content"] == "ask B"
    assert message["active_version_id"] == message["versions"][1]["id"]


async def test_unknown_message_returns_404(client):
    http, _db = client
    response = await http.get("/api/chats/nope/messages/nope/versions")
    assert response.status_code == 404

    response = await http.post("/api/messages/nope/versions/nope/activate")
    assert response.status_code == 404
