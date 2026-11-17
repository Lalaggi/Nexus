"""Settings, provider keys, health, and auth endpoints."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..config import CONFIG
from ..db import Database
from ..providers import MODELS, NEMOTRON, api_keys, preferred_provider, resolve_provider
from ..tools.sandbox import sandbox_status

router = APIRouter(prefix="/api", tags=["settings"])


def db_of(request: Request) -> Database:
    return request.app.state.db


class SettingsBody(BaseModel):
    provider: str | None = None
    user_name: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=1.5)
    nim_api_key: str | None = None
    openrouter_api_key: str | None = None
    custom_instructions: str | None = None
    custom_model_id: str | None = None
    clear_nim: bool = False
    clear_openrouter: bool = False


class TestBody(BaseModel):
    provider: str | None = None


class LoginBody(BaseModel):
    password: str


def _hint(key: str) -> str:
    if not key:
        return ""
    return "…" + key[-4:] if len(key) > 8 else "saved"


# Small in-process throttle. Single-user app, so this is about slowing down a
# scripted brute-force attempt rather than distributed rate limiting.
LOGIN_WINDOW = 300
LOGIN_MAX_FAILURES = 10
_failures: dict[str, deque[float]] = defaultdict(deque)


def _login_blocked(ip: str) -> bool:
    now = time.monotonic()
    bucket = _failures[ip]
    while bucket and now - bucket[0] > LOGIN_WINDOW:
        bucket.popleft()
    return len(bucket) >= LOGIN_MAX_FAILURES


async def _snapshot(request: Request) -> dict:
    db = db_of(request)
    keys = await api_keys(db)
    provider = await preferred_provider(db)
    user_name = await db.get_setting("user_name", CONFIG.user_name)
    temperature = float(await db.get_setting("temperature", str(CONFIG.temperature)))
    custom_instructions = await db.get_setting("custom_instructions", "")
    custom_model_id = await db.get_setting("custom_model_id", "")
    providers = []
    for spec in NEMOTRON.providers.values():
        providers.append(
            {
                "id": spec.id,
                "label": spec.label,
                "model_id": spec.model_id,
                "available": bool(keys.get(spec.id)),
                "key_hint": _hint(keys.get(spec.id, "")),
                "docs": spec.docs,
            }
        )
    return {
        "provider": provider,
        "providers": providers,
        "model": {
            "id": NEMOTRON.id,
            "name": NEMOTRON.name,
            "subtitle": NEMOTRON.subtitle,
            "description": NEMOTRON.description,
        },
        "models": [{"id": m.id, "name": m.name} for m in MODELS],
        "keys": {
            "nim": {"set": bool(keys.get("nim")), "hint": _hint(keys.get("nim", ""))},
            "openrouter": {
                "set": bool(keys.get("openrouter")),
                "hint": _hint(keys.get("openrouter", "")),
            },
        },
        "user_name": user_name,
        "assistant_name": CONFIG.assistant_name,
        "temperature": temperature,
        "custom_instructions": custom_instructions,
        "custom_model_id": custom_model_id,
        "max_tool_steps": CONFIG.max_tool_steps,
        "sandbox": sandbox_status(),
        "paths": {
            "uploads": str(CONFIG.uploads_dir),
            "outputs": str(CONFIG.outputs_dir),
            "data": str(CONFIG.data_dir),
        },
        "searxng_url": CONFIG.searxng_url,
        "auth_required": bool(CONFIG.password),
    }


@router.get("/settings")
async def get_settings(request: Request) -> dict:
    return await _snapshot(request)


@router.put("/settings")
async def put_settings(request: Request, body: SettingsBody) -> dict:
    db = db_of(request)
    if body.provider is not None:
        if body.provider not in {"auto", "nim", "openrouter"}:
            raise HTTPException(400, "provider must be auto, nim, or openrouter")
        await db.set_setting("provider", body.provider)
    if body.user_name is not None:
        name = body.user_name.strip()[:60] or CONFIG.user_name
        await db.set_setting("user_name", name)
    if body.temperature is not None:
        await db.set_setting("temperature", str(max(0.0, min(1.5, body.temperature))))
    if body.custom_instructions is not None:
        await db.set_setting("custom_instructions", body.custom_instructions.strip())
    if body.custom_model_id is not None:
        await db.set_setting("custom_model_id", body.custom_model_id.strip())
    if body.clear_nim:
        await db.delete_setting("nim_api_key")
    if body.clear_openrouter:
        await db.delete_setting("openrouter_api_key")
    if body.nim_api_key and body.nim_api_key.strip():
        await db.set_setting("nim_api_key", body.nim_api_key.strip())
    if body.openrouter_api_key and body.openrouter_api_key.strip():
        await db.set_setting("openrouter_api_key", body.openrouter_api_key.strip())
    return await _snapshot(request)


@router.post("/settings/test")
async def test_provider(request: Request, body: TestBody) -> dict:
    db = db_of(request)
    requested = body.provider or await preferred_provider(db)
    try:
        model, provider, key = await resolve_provider(db, requested)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{provider.base_url}/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            response.raise_for_status()
            payload = response.json()
        ids = {item.get("id") for item in payload.get("data", [])}
        found = provider.model_id in ids
        return {
            "ok": True,
            "provider": provider.id,
            "label": provider.label,
            "model": model.name,
            "model_visible": found,
            "detail": (
                f"Connected to {provider.label}. {provider.model_id} is listed."
                if found
                else f"Connected to {provider.label}, but {provider.model_id} was not in /models. It may still work."
            ),
        }
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": f"Connection failed: {exc}", "provider": provider.id},
            status_code=400,
        )


@router.get("/health")
async def health(request: Request) -> dict:
    searxng_ok = False
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.get(
                f"{CONFIG.searxng_url.rstrip('/')}/healthz",
            )
            searxng_ok = response.status_code == 200
    except Exception:
        pass
    sandbox = sandbox_status()
    return {
        "ok": True,
        "searxng": searxng_ok,
        "sandbox": sandbox,
        "version": "0.1.0",
    }


@router.get("/auth")
async def auth_state(request: Request) -> dict:
    return {
        "required": bool(CONFIG.password),
        "authenticated": not bool(CONFIG.password) or request.state.authenticated,
    }


@router.post("/login")
async def login(request: Request, body: LoginBody) -> dict:
    if not CONFIG.password:
        return {"ok": True}
    ip = request.client.host if request.client else "unknown"
    if _login_blocked(ip):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    if not hmac.compare_digest(body.password, CONFIG.password):
        _failures[ip].append(time.monotonic())
        raise HTTPException(401, "Incorrect password")
    _failures.pop(ip, None)
    response = JSONResponse({"ok": True})
    response.set_cookie(
        "assistant_session",
        request.app.state.session_token,
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        samesite="lax",
        secure=CONFIG.cookie_secure,
    )
    return response


@router.post("/logout")
async def logout() -> dict:
    response = JSONResponse({"ok": True})
    response.delete_cookie("assistant_session")
    return response
