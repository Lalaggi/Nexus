"""Curated model registry and OpenAI-compatible streaming client."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from typing import Any, AsyncIterator

import httpx

from .config import CONFIG
from .db import Database


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    base_url: str
    model_id: str
    key_name: str
    docs: str


@dataclass(frozen=True)
class CuratedModel:
    id: str
    name: str
    subtitle: str
    description: str
    providers: dict[str, ProviderSpec]


@dataclass(frozen=True)
class ResolvedModel:
    """A model fully resolved to a provider, model id, and API key."""

    name: str          # display name
    model_id: str      # actual model id sent to the API
    provider: ProviderSpec
    key: str


NEMOTRON = CuratedModel(
    id="nemotron-3.5-super-vl",
    name="Nemotron 3.5 VL Super",
    subtitle="NVIDIA · vision + tools",
    description=(
        "NVIDIA's 120B vision-language model with a 1M-token context, native tool "
        "calling, and strong document, chart, and UI understanding. Free on both NIM "
        "and OpenRouter."
    ),
    providers={
        "nim": ProviderSpec(
            id="nim",
            label="NVIDIA NIM",
            base_url="https://integrate.api.nvidia.com/v1",
            model_id="nvidia/nemotron-3.5-super-vl-120b-a12b",
            key_name="nim_api_key",
            docs="https://build.nvidia.com/nvidia/nemotron-3-5-super-vl-120b-a12b",
        ),
        "openrouter": ProviderSpec(
            id="openrouter",
            label="OpenRouter",
            base_url="https://openrouter.ai/api/v1",
            model_id="nvidia/nemotron-3.5-super-vl:free",
            key_name="openrouter_api_key",
            docs="https://openrouter.ai/nvidia/nemotron-3.5-super-vl:free",
        ),
    },
)

MODELS: list[CuratedModel] = [NEMOTRON]
DEFAULT_MODEL = NEMOTRON.id


def get_model(model_id: str) -> CuratedModel | None:
    for model in MODELS:
        if model.id == model_id:
            return model
    return None


async def api_keys(db: Database) -> dict[str, str]:
    stored = await db.all_settings()
    return {
        "nim": (stored.get("nim_api_key") or CONFIG.nim_key).strip(),
        "openrouter": (stored.get("openrouter_api_key") or CONFIG.openrouter_key).strip(),
    }


async def preferred_provider(db: Database) -> str:
    value = (await db.get_setting("provider", CONFIG.provider)).strip().lower()
    return value if value in {"auto", "nim", "openrouter"} else "auto"


async def resolve_provider(
    db: Database,
    model_id: str | None = None,
    requested: str | None = None,
) -> ResolvedModel:
    """Resolve a model + provider choice to a concrete ProviderSpec and API key.

    ``model_id`` is the model the user selected (curated model id or a custom
    model_id such as ``inclusionai/ling-3.2-flash:free``). ``requested`` is the
    provider preference ("nim", "openrouter", "auto", or a chat's stored provider).

    Custom models always route through OpenRouter. Curated models (Nemotron) can
    route through NIM or OpenRouter depending on the preference.
    """
    keys = await api_keys(db)
    settings_pref = await preferred_provider(db)

    # A chat's explicit provider ("nim"/"openrouter") takes precedence.
    # "auto" defers to the settings-level preference.
    preference = requested if requested and requested != "auto" else settings_pref
    preference = (preference or "").strip().lower()
    if preference not in {"auto", "nim", "openrouter"}:
        preference = "auto"

    model = get_model(model_id) if model_id else None

    # Custom models (not in the curated registry) always go through OpenRouter.
    if model is None:
        if not model_id:
            model_id = DEFAULT_MODEL
            model = NEMOTRON
        else:
            # Custom model: route via OpenRouter with the user's model id.
            key = keys.get("openrouter", "")
            if not key:
                raise ProviderError(
                    "Custom models require an OpenRouter API key. Add one in "
                    "Settings → Provider."
                )
            spec = ProviderSpec(
                id="openrouter",
                label="OpenRouter",
                base_url=(
                    CONFIG.openrouter_base_url.rstrip("/")
                    if CONFIG.openrouter_base_url.strip()
                    else "https://openrouter.ai/api/v1"
                ),
                model_id=model_id,
                key_name="openrouter_api_key",
                docs="https://openrouter.ai/models",
            )
            return ResolvedModel(
                name=model_id,
                model_id=model_id,
                provider=spec,
                key=key,
            )

    # Curated model (Nemotron): choose provider based on preference.
    if preference == "auto":
        order = ["nim", "openrouter"]
    else:
        order = [preference]

    for provider_id in order:
        key = keys.get(provider_id, "")
        if not key:
            continue
        spec = model.providers[provider_id]
        override = (
            CONFIG.nim_base_url if provider_id == "nim" else CONFIG.openrouter_base_url
        ).strip()
        if override:
            spec = replace(spec, base_url=override.rstrip("/"))
        return ResolvedModel(
            name=model.name,
            model_id=spec.model_id,
            provider=spec,
            key=key,
        )

    # No key available for any provider in the order.
    if model is NEMOTRON:
        raise ProviderError(
            "No API key configured. Open Settings and add an NVIDIA NIM or "
            "OpenRouter key. NIM keys are free at build.nvidia.com; OpenRouter "
            "has a free Nemotron endpoint."
        )
    raise ProviderError(
        f"No API key configured for {provider.label}. Add one in "
        "Settings → Provider."
    )


def _headers(provider: ProviderSpec, key: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "Assistant/0.1 (self-hosted)",
    }
    if provider.id == "openrouter":
        headers["HTTP-Referer"] = "http://localhost:8848"
        headers["X-Title"] = "Assistant"
    return headers


class StreamClient:
    def __init__(self, provider: ProviderSpec, key: str):
        self.provider = provider
        self.key = key

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tool_choice: str | None = "auto",
        model_id: str | None = None,
    ) -> AsyncIterator[dict]:
        payload: dict[str, Any] = {
            "model": model_id or self.provider.model_id,
            "messages": messages,
            "stream": True,
            "temperature": CONFIG.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or CONFIG.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        timeout = httpx.Timeout(
            connect=20.0, read=CONFIG.request_timeout, write=60.0, pool=20.0
        )
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    request = client.build_request(
                        "POST",
                        f"{self.provider.base_url}/chat/completions",
                        headers=_headers(self.provider, self.key),
                        json=payload,
                    )
                    response = await client.send(request, stream=True)
                    try:
                        if response.status_code >= 400:
                            body = (await response.aread()).decode("utf-8", "replace")
                            detail = _error_detail(body)
                            if (
                                response.status_code in {429, 500, 502, 503, 504}
                                and attempt < 2
                            ):
                                await asyncio.sleep(1.5 * (attempt + 1))
                                continue
                            raise ProviderError(
                                f"{self.provider.label} returned HTTP "
                                f"{response.status_code}: {detail}"
                            )

                        async for line in response.aiter_lines():
                            line = line.strip()
                            if not line or line.startswith(":"):
                                continue
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                return
                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            yield chunk
                    finally:
                        await response.aclose()
                    return
            except ProviderError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise ProviderError(
                    f"Could not reach {self.provider.label}: {exc}. Check your network."
                ) from exc

        raise ProviderError(f"{self.provider.label} request failed: {last_error}")


def _error_detail(body: str) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body[:600]
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)[:600]
        if error:
            return str(error)[:600]
        if parsed.get("detail"):
            return str(parsed["detail"])[:600]
    return body[:600]


def extract_delta(chunk: dict) -> tuple[str, str, list[dict], str | None, dict | None]:
    """Return (text, reasoning, tool_call_deltas, finish_reason, usage)."""
    choices = chunk.get("choices") or []
    if not choices:
        return "", "", [], None, chunk.get("usage")
    choice = choices[0] or {}
    delta = choice.get("delta") or {}
    text = delta.get("content") or ""
    if isinstance(text, list):
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
    tool_calls = delta.get("tool_calls") or []
    return text, reasoning, tool_calls, choice.get("finish_reason"), chunk.get("usage")
