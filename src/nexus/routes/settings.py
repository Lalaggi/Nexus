"""Settings, provider keys, health, and auth endpoints."""

from __future__ import annotations

import hmac
import re
import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..config import CONFIG
from ..db import Database
from ..providers import api_keys, preferred_provider, resolve_provider
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


class CustomModelBody(BaseModel):
    name: str
    model_id: str


class CatalogToggleBody(BaseModel):
    enabled: bool


class CatalogDefaultBody(BaseModel):
    pass


class CatalogAddBody(BaseModel):
    provider: str
    model_id: str
    name: str | None = None


class LoginBody(BaseModel):
    password: str


def _hint(key: str) -> str:
    if not key:
        return ""
    return "…" + key[-4:] if len(key) > 8 else "saved"


_SYNC_PROVIDER_LABELS = {"nim": "NVIDIA NIM", "openrouter": "OpenRouter"}

# Common acronyms in NIM model ids that should stay uppercase in the display name.
_MODEL_NAME_ACRONYMS = {
    "ai": "AI",
    "asr": "ASR",
    "dpo": "DPO",
    "gguf": "GGUF",
    "it": "IT",
    "llm": "LLM",
    "moe": "MoE",
    "ocr": "OCR",
    "pii": "PII",
    "qa": "QA",
    "rag": "RAG",
    "sft": "SFT",
    "tts": "TTS",
    "vl": "VL",
    "vlm": "VLM",
}


def _provider_base_url(provider: str) -> str:
    if provider == "nim":
        return (
            CONFIG.nim_base_url.strip() or "https://integrate.api.nvidia.com/v1"
        ).rstrip("/")
    return (
        CONFIG.openrouter_base_url.strip() or "https://openrouter.ai/api/v1"
    ).rstrip("/")


def _pretty_model_name(model_id: str) -> str:
    """Turn a raw model id like ``nvidia/nemotron-3.5-super-vl-120b-a12b`` into
    a readable name. The raw id is still what gets sent to the provider."""
    tail = model_id.rsplit("/", 1)[-1]
    words: list[str] = []
    for token in re.split(r"[-_]+", tail):
        if not token:
            continue
        lowered = token.lower()
        if lowered in _MODEL_NAME_ACRONYMS:
            words.append(_MODEL_NAME_ACRONYMS[lowered])
            continue
        version = re.fullmatch(r"(\d+(?:\.\d+)*)([a-z]*)", lowered)
        if version:
            words.append(version.group(1) + version.group(2).upper())
            continue
        # GPU-ish tokens such as "a12b" or "h100" read better fully uppercased.
        chip = re.fullmatch(r"([a-z])(\d+)([a-z]*)", lowered)
        if chip:
            words.append(
                chip.group(1).upper() + chip.group(2) + chip.group(3).upper()
            )
            continue
        words.append(token[:1].upper() + token[1:])
    return " ".join(words) or model_id


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
    custom_models = await db.list_custom_models()
    _provider_docs = {
        "nim": "https://build.nvidia.com/",
        "openrouter": "https://openrouter.ai/models",
    }
    _provider_labels = {
        "nim": "NVIDIA",
        "openrouter": "OpenRouter",
    }
    providers = []
    for pid in ("nim", "openrouter"):
        providers.append(
            {
                "id": pid,
                "label": _provider_labels[pid],
                "available": bool(keys.get(pid)),
                "key_hint": _hint(keys.get(pid, "")),
                "docs": _provider_docs[pid],
            }
        )
    catalog = await db.list_model_catalog()
    default_entry = await db.get_default_model_catalog_entry()
    return {
        "provider": provider,
        "providers": providers,
        "models": [
            {
                "id": row["id"],
                "provider": row["provider"],
                "model_id": row["model_id"],
                "name": row["name"],
                "enabled": bool(row["enabled"]),
                "is_default": bool(row["is_default"]),
                "source": row["source"],
            }
            for row in catalog
        ],
        "default_model": (
            {
                "id": default_entry["id"],
                "provider": default_entry["provider"],
                "model_id": default_entry["model_id"],
                "name": default_entry["name"],
            }
            if default_entry
            else None
        ),
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
        "custom_models": custom_models,
        "max_tool_steps": CONFIG.max_tool_steps,
        "sandbox": await sandbox_status(),
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
    requested = (body.provider or await preferred_provider(db)).strip().lower()
    if requested not in {"nim", "openrouter", "auto"}:
        requested = "auto"
    if requested == "auto":
        default_entry = await db.get_default_model_catalog_entry()
        requested = (default_entry or {}).get("provider") or "nim"

    model_id = None
    for row in await db.list_model_catalog(enabled_only=True):
        if row["provider"] == requested:
            model_id = row["model_id"]
            break
    if not model_id:
        return JSONResponse(
            {"ok": False, "error": f"No enabled models for {requested}."},
            status_code=400,
        )
    try:
        resolved = await resolve_provider(db, requested, model_id)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{resolved.provider.base_url}/models",
                headers={"Authorization": f"Bearer {resolved.key}"},
            )
            response.raise_for_status()
            payload = response.json()
        ids = {item.get("id") for item in payload.get("data", [])}
        found = resolved.model_id in ids
        return {
            "ok": True,
            "provider": resolved.provider.id,
            "label": resolved.provider.label,
            "model": resolved.name,
            "model_visible": found,
            "detail": (
                f"Connected to {resolved.provider.label}. {resolved.model_id} is listed."
                if found
                else f"Connected to {resolved.provider.label}, but {resolved.model_id} was not in /models. It may still work."
            ),
        }
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": f"Connection failed: {exc}", "provider": provider.id},
            status_code=400,
        )

@router.get("/models/custom")
async def list_custom_models_endpoint(request: Request) -> list[dict]:
    db = db_of(request)
    return await db.list_custom_models()


@router.post("/models/custom")
async def add_custom_model_endpoint(
    request: Request, body: CustomModelBody
) -> dict | None:
    db = db_of(request)
    result = await db.add_custom_model(body.name, body.model_id)
    if result is None:
        raise HTTPException(409, "A model with that ID already exists.")
    return result


@router.delete("/models/custom/{model_id:path}")
async def delete_custom_model_endpoint(request: Request, model_id: str) -> dict:
    db = db_of(request)
    existing = await db.get_custom_model(model_id)
    if existing is None:
        raise HTTPException(404, "Custom model not found.")
    await db.delete_custom_model(model_id)
    return {"ok": True}


# ---------------------------------------------------------------- model catalog
@router.get("/models/catalog")
async def list_model_catalog_endpoint(request: Request) -> list[dict]:
    db = db_of(request)
    return await db.list_model_catalog()


class SyncBody(BaseModel):
    provider: str | None = None


@router.post("/models/catalog/sync")
async def sync_model_catalog_endpoint(
    request: Request, body: SyncBody | None = None
) -> dict:
    """Fetch each provider's model list and upsert it into the catalog.

    Both NVIDIA NIM and OpenRouter expose an OpenAI-compatible ``/models``
    endpoint, so the same sync covers both. When ``provider`` is omitted, every
    provider with a configured API key is synced. Discovered models are added
    disabled; existing entries keep their enabled/default state.
    """
    db = db_of(request)
    keys = await api_keys(db)
    requested = (body.provider or "").strip().lower() if body else ""
    if requested and requested not in _SYNC_PROVIDER_LABELS:
        raise HTTPException(400, "Provider must be nim or openrouter.")
    providers = [requested] if requested else ["nim", "openrouter"]

    results: dict[str, dict] = {}
    total = 0
    for provider in providers:
        key = keys.get(provider, "").strip()
        if not key:
            results[provider] = {
                "ok": False,
                "synced": 0,
                "error": f"No {_SYNC_PROVIDER_LABELS[provider]} API key configured.",
            }
            continue
        try:
            synced = await _sync_provider_models(db, provider, key)
        except Exception as exc:
            results[provider] = {"ok": False, "synced": 0, "error": str(exc)}
            continue
        results[provider] = {"ok": True, "synced": synced}
        total += synced

    if total == 0 and all(not result["ok"] for result in results.values()):
        errors = "; ".join(
            f"{_SYNC_PROVIDER_LABELS[provider]}: {result['error']}"
            for provider, result in results.items()
            if not result["ok"]
        )
        raise HTTPException(400, f"Model sync failed. {errors}")

    return {"ok": True, "synced": total, "providers": results}


async def _sync_provider_models(db: Database, provider: str, key: str) -> int:
    base_url = _provider_base_url(provider)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()

    items = payload.get("data", []) if isinstance(payload, dict) else payload
    synced = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not model_id:
            continue
        existing = await db.get_model_catalog_entry_by_model(provider, model_id)
        if provider == "openrouter":
            # OpenRouter publishes a proper display name; prefer it.
            name = item.get("name") or _pretty_model_name(model_id)
        else:
            # NIM only returns ids. Keep curated names (e.g. the seeded
            # Nemotron entry) and derive a readable name for new models.
            name = (existing or {}).get("name") or _pretty_model_name(model_id)
        await db.upsert_model_catalog_entry(
            provider, model_id, name, source="discovered"
        )
        synced += 1
    return synced


@router.post("/models/catalog")
async def add_model_catalog_endpoint(
    request: Request, body: CatalogAddBody
) -> dict:
    """Manually add a model to the catalog.

    Useful for models that are not returned by a provider's ``/models``
    endpoint. The model is added disabled by default so it does not appear in
    the composer until the user enables it.
    """
    db = db_of(request)
    provider = body.provider.strip().lower()
    if provider not in {"nim", "openrouter"}:
        raise HTTPException(400, "Provider must be nim or openrouter.")
    name = body.name.strip() if body.name else body.model_id.split("/")[-1]
    entry = await db.upsert_model_catalog_entry(
        provider, body.model_id.strip(), name, source="custom"
    )
    return entry


@router.patch("/models/catalog/{catalog_id}/toggle")
async def toggle_model_catalog_endpoint(
    request: Request, catalog_id: str, body: CatalogToggleBody
) -> dict:
    db = db_of(request)
    entry = await db.get_model_catalog_entry(catalog_id)
    if entry is None:
        raise HTTPException(404, "Catalog entry not found.")
    await db.set_model_catalog_enabled(catalog_id, body.enabled)
    # If this was the default and it's being disabled, pick a new default.
    if body.enabled and entry.get("is_default"):
        pass  # remains default
    if not body.enabled and entry.get("is_default"):
        remaining = await db.list_model_catalog(enabled_only=True)
        if remaining:
            new_default = remaining[0]
            await db.set_model_catalog_default(new_default["id"])
    return await db.get_model_catalog_entry(catalog_id)  # type: ignore[return-value]


@router.patch("/models/catalog/{catalog_id}/default")
async def set_model_catalog_default_endpoint(
    request: Request, catalog_id: str
) -> dict:
    db = db_of(request)
    entry = await db.get_model_catalog_entry(catalog_id)
    if entry is None:
        raise HTTPException(404, "Catalog entry not found.")
    if not entry.get("enabled"):
        raise HTTPException(400, "Only enabled models can be the default.")
    await db.set_model_catalog_default(catalog_id)
    return await db.get_model_catalog_entry(catalog_id)  # type: ignore[return-value]


@router.delete("/models/catalog/{catalog_id}")
async def delete_model_catalog_endpoint(request: Request, catalog_id: str) -> dict:
    db = db_of(request)
    entry = await db.get_model_catalog_entry(catalog_id)
    if entry is None:
        raise HTTPException(404, "Catalog entry not found.")
    await db.delete_model_catalog_entry(catalog_id)
    return {"ok": True}


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
    sandbox = await sandbox_status()
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
    response = JSONResponse({"ok": True, "token": request.app.state.session_token})
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
