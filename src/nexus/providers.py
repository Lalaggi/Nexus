"""Curated model registry and OpenAI-compatible streaming client."""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

from .config import CONFIG
from .db import Database
from .retry import RetryPolicy

RetryCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class _RetryRequest(Exception):
    """Internal signal: close this response and retry after the given delay."""

    def __init__(self, message: str, delay: float):
        super().__init__(message)
        self.message = message
        self.delay = delay


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
class ResolvedModel:
    """A model fully resolved to a provider, model id, and API key."""

    name: str          # display name
    model_id: str      # actual model id sent to the API
    provider: ProviderSpec
    key: str
    supports_vision: bool = True


# Fallback model id used when a chat has no explicit model selection. The
# catalog (seeded with Nemotron on NIM + OpenRouter) is the source of truth for
# available models; this is only a last-resort default.
DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"


async def api_keys(db: Database) -> dict[str, str]:
    stored = await db.all_settings()
    return {
        "nim": (stored.get("nim_api_key") or CONFIG.nim_key).strip(),
        "openrouter": (stored.get("openrouter_api_key") or CONFIG.openrouter_key).strip(),
    }


async def preferred_provider(db: Database) -> str:
    value = (await db.get_setting("provider", CONFIG.provider)).strip().lower()
    return value if value in {"auto", "nim", "openrouter"} else "auto"


_PROVIDER_DEFAULTS = {
    "nim": {
        "label": "NVIDIA NIM",
        "default_base_url": "https://integrate.api.nvidia.com/v1",
        "docs": "https://build.nvidia.com/",
    },
    "openrouter": {
        "label": "OpenRouter",
        "default_base_url": "https://openrouter.ai/api/v1",
        "docs": "https://openrouter.ai/models",
    },
}


async def resolve_provider(
    db: Database,
    provider: str,
    model_id: str,
) -> ResolvedModel:
    """Resolve a provider + model ID to a concrete ProviderSpec and API key.

    The model is expected to come from the enabled model catalog, so ``provider``
    is explicit ("nim" or "openrouter") and ``model_id`` is the actual ID sent
    to the provider API (e.g. ``nvidia/nemotron-3.5-super-vl-120b-a12b``).
    """
    provider = (provider or "").strip().lower()
    if provider not in _PROVIDER_DEFAULTS:
        raise ProviderError(f"Unknown provider: {provider or '<none>'}")

    # Back-compat: if a stored model id is a curated shorthand (no provider
    # prefix, e.g. "nemotron-3.5-super-vl"), resolve it to the default enabled
    # catalog model for this provider so older chats keep working.
    if "/" not in model_id:
        catalog_model = await db.get_enabled_model_id_for_provider(provider)
        if catalog_model:
            model_id = catalog_model

    keys = await api_keys(db)
    key = keys.get(provider, "").strip()
    if not key:
        raise ProviderError(
            f"No API key configured for {provider}. Add one in Settings → Provider."
        )

    meta = _PROVIDER_DEFAULTS[provider]
    override = (
        CONFIG.nim_base_url if provider == "nim" else CONFIG.openrouter_base_url
    ).strip()
    base_url = override.rstrip("/") if override else meta["default_base_url"]

    spec = ProviderSpec(
        id=provider,
        label=meta["label"],
        base_url=base_url,
        model_id=model_id,
        key_name=f"{provider}_api_key",
        docs=meta["docs"],
    )
    return ResolvedModel(
        name=model_id,
        model_id=model_id,
        provider=spec,
        key=key,
        supports_vision=True,
    )


def _headers(provider: ProviderSpec, key: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "Nexus/0.1 (self-hosted)",
    }
    if provider.id == "openrouter":
        headers["HTTP-Referer"] = "http://localhost:8848"
        headers["X-Title"] = "Nexus"
    return headers


class StreamClient:
    def __init__(
        self,
        provider: ProviderSpec,
        key: str,
        *,
        policy: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.provider = provider
        self.key = key
        self.policy = policy or RetryPolicy.from_config()
        self.transport = transport

    async def _notify_retry(
        self,
        callback: RetryCallback | None,
        attempt: int,
        max_attempts: int,
        delay: float,
        message: str,
    ) -> None:
        if callback is None:
            return
        result = callback(
            {
                "type": "retry",
                "attempt": attempt + 1,
                "max_attempts": max_attempts,
                "delay_ms": int(round(delay * 1000)),
                "message": message,
            }
        )
        if inspect.isawaitable(result):
            await result

    async def _wait(
        self,
        delay: float,
        cancel: asyncio.Event | None,
    ) -> bool:
        """Sleep for ``delay`` seconds; return False if Stop was pressed."""
        if cancel is not None and cancel.is_set():
            return False
        if delay <= 0:
            return True
        if cancel is None:
            await asyncio.sleep(delay)
            return True
        try:
            await asyncio.wait_for(cancel.wait(), timeout=delay)
        except TimeoutError:
            return True
        return False

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tool_choice: str | None = "auto",
        model_id: str | None = None,
        *,
        cancel: asyncio.Event | None = None,
        on_retry: RetryCallback | None = None,
        max_attempts: int | None = None,
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
        attempts = max(1, max_attempts if max_attempts is not None else self.policy.max_attempts)
        timeout_attempts = max(1, self.policy.timeout_attempts)
        timeouts = 0
        yielded = False
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            if cancel is not None and cancel.is_set():
                return
            try:
                async with httpx.AsyncClient(
                    timeout=timeout, transport=self.transport
                ) as client:
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
                            message = (
                                f"{self.provider.label} returned HTTP "
                                f"{response.status_code}: {detail}"
                            )
                            if (
                                not yielded
                                and attempt < attempts
                                and self.policy.should_retry(
                                    response.status_code, body, response.headers
                                )
                            ):
                                delay = self.policy.delay(
                                    attempt - 1,
                                    self.policy.retry_after_ms(response.headers),
                                )
                                raise _RetryRequest(message, delay)
                            raise ProviderError(message)

                        retry_message: str | None = None
                        retry_delay = 0.0
                        async for line in response.aiter_lines():
                            if cancel is not None and cancel.is_set():
                                return
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
                            stream_error = _stream_error(chunk)
                            if stream_error is not None:
                                status, detail = stream_error
                                message = (
                                    f"{self.provider.label} stream error: {detail}"
                                )
                                if (
                                    not yielded
                                    and attempt < attempts
                                    and self.policy.should_retry(status, detail)
                                ):
                                    retry_message = message
                                    retry_delay = self.policy.delay(
                                        attempt - 1,
                                        self.policy.retry_after_ms(response.headers),
                                    )
                                    break
                                raise ProviderError(message)
                            yielded = True
                            yield chunk

                        if retry_message is not None:
                            raise _RetryRequest(retry_message, retry_delay)
                        return
                    finally:
                        await response.aclose()
            except _RetryRequest as retry:
                await self._notify_retry(
                    on_retry,
                    attempt,
                    attempts,
                    retry.delay,
                    retry.message,
                )
                if not await self._wait(retry.delay, cancel):
                    return
                continue
            except ProviderError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                message = (
                    f"Could not reach {self.provider.label}: {exc}. Check your network."
                )
                if yielded:
                    raise ProviderError(
                        f"{self.provider.label} stream was interrupted after "
                        f"partial output: {exc}"
                    ) from exc
                if isinstance(exc, httpx.TimeoutException):
                    timeouts += 1
                if attempt >= attempts or timeouts >= timeout_attempts:
                    raise ProviderError(message) from exc
                delay = self.policy.delay(attempt - 1)
                await self._notify_retry(
                    on_retry,
                    attempt,
                    attempts,
                    delay,
                    message,
                )
                if not await self._wait(delay, cancel):
                    return
                continue

        raise ProviderError(f"{self.provider.label} request failed: {last_error}")


def _stream_error(chunk: dict) -> tuple[int, str] | None:
    """Extract an error object delivered inside an otherwise-200 SSE stream."""
    if not isinstance(chunk, dict) or "error" not in chunk:
        return None
    error = chunk.get("error")
    if not error:
        return None
    if isinstance(error, dict):
        message = str(
            error.get("message") or error.get("detail") or error or "Provider error"
        )[:600]
        raw_status = error.get("status") or error.get("code") or error.get("type")
        status = 0
        if isinstance(raw_status, int):
            status = raw_status
        elif isinstance(raw_status, str) and raw_status.isdigit():
            status = int(raw_status)
        if status == 0:
            lowered = message.lower()
            if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
                status = 429
            elif any(word in lowered for word in ("quota", "billing", "credit")):
                status = 402
        return status, message
    return 0, str(error or "Provider error")[:600]



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
