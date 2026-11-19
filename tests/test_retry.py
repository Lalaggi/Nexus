from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timezone

import httpx
import pytest

from nexus.providers import ProviderError, ProviderSpec, StreamClient
from nexus.retry import (
    RetryPolicy,
    is_retryable,
    next_delay,
    parse_retry_after_ms,
)


def _provider() -> ProviderSpec:
    return ProviderSpec(
        id="test",
        label="Test Provider",
        base_url="https://example.test/v1",
        model_id="test/model",
        key_name="test_key",
        docs="https://example.test",
    )


def _policy(**overrides) -> RetryPolicy:
    values = {
        "max_attempts": 3,
        "base_delay": 0.0,
        "max_delay": 0.0,
        "retry_after_max": 900.0,
        "jitter": 0.0,
        "timeout_attempts": 3,
    }
    values.update(overrides)
    return RetryPolicy(**values)


def test_parse_retry_after_ms_reads_milliseconds():
    assert parse_retry_after_ms({"retry-after-ms": "750"}) == 750


def test_parse_retry_after_ms_reads_seconds():
    assert parse_retry_after_ms({"Retry-After": "30"}) == 30_000


def test_parse_retry_after_ms_reads_http_date_with_reference_time():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    headers = {"retry-after": "Thu, 01 Jan 2026 12:00:30 GMT"}
    assert parse_retry_after_ms(headers, now=now) == 30_000


def test_parse_retry_after_ms_clamps_and_ignores_invalid_values():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after_ms({"retry-after": "-5"}, max_ms=1000, now=now) == 0
    assert parse_retry_after_ms({"retry-after-ms": "999999"}, max_ms=1000, now=now) == 1000
    assert parse_retry_after_ms({"retry-after": "not-a-date"}, now=now) is None
    assert parse_retry_after_ms({}, now=now) is None


def test_parse_retry_after_ms_prefers_milliseconds_over_seconds():
    headers = {"retry-after-ms": "250", "retry-after": "30"}
    assert parse_retry_after_ms(headers) == 250


@pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 502, 503, 504, 529])
def test_transient_statuses_are_retryable(status):
    assert is_retryable(status) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_auth_and_invalid_request_failures_are_terminal(status):
    assert is_retryable(status) is False


def test_quota_and_billing_exhaustion_is_terminal():
    assert is_retryable(402) is False
    assert is_retryable(429, "You exceeded your current quota, please check billing") is False
    assert is_retryable(429, "insufficient_quota") is False
    assert is_retryable(403, "quota exhausted") is False


def test_x_should_retry_header_overrides_classification():
    assert is_retryable(429, headers={"x-should-retry": "false"}) is False
    assert is_retryable(400, headers={"X-Should-Retry": "true"}) is True


def test_next_delay_is_exponential_and_capped():
    assert [next_delay(n, base_delay=2, max_delay=10, jitter=0) for n in range(5)] == [
        2.0,
        4.0,
        8.0,
        10.0,
        10.0,
    ]


def test_next_delay_honours_provider_delay_when_longer():
    assert next_delay(0, 30_000, base_delay=2, max_delay=10, jitter=0) == 30.0
    assert next_delay(0, 1_000, base_delay=2, max_delay=10, jitter=0) == 2.0


def test_next_delay_jitter_stays_within_bounds_and_respects_cap():
    rng = random.Random(7)
    for _ in range(200):
        assert 1.6 <= next_delay(0, base_delay=2, max_delay=10, jitter=0.2, rng=rng) <= 2.4
    for _ in range(200):
        # The positive half of the jitter is clipped by the per-gap cap.
        assert 8.0 <= next_delay(8, base_delay=2, max_delay=10, jitter=0.2, rng=rng) <= 10.0


async def _collect(client: StreamClient, **kwargs):
    chunks = []
    async for chunk in client.stream(
        [{"role": "user", "content": "hello"}], **kwargs
    ):
        chunks.append(chunk)
    return chunks


async def test_stream_retries_a_429_and_honours_retry_after():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={"retry-after": "0"},
                json={"error": {"message": "rate limited"}},
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n',
        )

    events: list[dict] = []

    async def on_retry(event: dict) -> None:
        events.append(event)

    client = StreamClient(
        _provider(), "key", policy=_policy(), transport=httpx.MockTransport(handler)
    )
    chunks = await _collect(client, on_retry=on_retry)

    assert len(requests) == 2
    assert chunks == [{"choices": [{"delta": {"content": "hi"}}]}]
    assert events == [
        {
            "type": "retry",
            "attempt": 2,
            "max_attempts": 3,
            "delay_ms": 0,
            "message": "Test Provider returned HTTP 429: rate limited",
        }
    ]


async def test_stream_does_not_retry_after_partial_output():
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            raise httpx.ReadError("connection dropped")

        async def aclose(self) -> None:
            pass

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=BrokenStream(),
        )

    events: list[dict] = []

    async def on_retry(event: dict) -> None:
        events.append(event)

    client = StreamClient(
        _provider(), "key", policy=_policy(), transport=httpx.MockTransport(handler)
    )
    seen: list[dict] = []
    with pytest.raises(ProviderError, match="partial output"):
        async for chunk in client.stream(
            [{"role": "user", "content": "hello"}], on_retry=on_retry
        ):
            seen.append(chunk)

    assert len(requests) == 1
    assert seen == [{"choices": [{"delta": {"content": "partial"}}]}]
    assert events == []


async def test_stream_fails_fast_for_terminal_status():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    client = StreamClient(
        _provider(), "key", policy=_policy(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderError, match="HTTP 401: bad key"):
        await _collect(client)

    assert len(requests) == 1


async def test_stream_retries_a_retryable_error_delivered_inside_sse():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b'data: {"error":{"message":"rate limited","code":429}}\n\n',
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n',
        )

    events: list[dict] = []

    async def on_retry(event: dict) -> None:
        events.append(event)

    client = StreamClient(
        _provider(), "key", policy=_policy(), transport=httpx.MockTransport(handler)
    )
    chunks = await _collect(client, on_retry=on_retry)

    assert len(requests) == 2
    assert chunks == [{"choices": [{"delta": {"content": "hi"}}]}]
    assert events[0]["attempt"] == 2
    assert "stream error: rate limited" in events[0]["message"]


async def test_stream_raises_errors_delivered_inside_sse():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"error":{"message":"quota exceeded","code":429}}\n\n'
            ),
        )

    client = StreamClient(
        _provider(), "key", policy=_policy(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderError, match="stream error: quota exceeded"):
        await _collect(client)

    assert len(requests) == 1


async def test_stop_interrupts_a_long_retry_wait():
    requests: list[httpx.Request] = []
    cancel = asyncio.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            429,
            headers={"retry-after": "30"},
            json={"error": {"message": "slow down"}},
        )

    async def on_retry(_event: dict) -> None:
        # Simulate the user pressing Stop while the status is visible.
        asyncio.get_running_loop().call_later(0.05, cancel.set)

    client = StreamClient(
        _provider(), "key", policy=_policy(), transport=httpx.MockTransport(handler)
    )
    started = time.monotonic()
    chunks = await _collect(client, cancel=cancel, on_retry=on_retry)
    elapsed = time.monotonic() - started

    assert chunks == []
    assert len(requests) == 1
    assert elapsed < 1.5


def test_policy_loads_retry_after_with_its_own_cap():
    policy = RetryPolicy(retry_after_max=2.0)
    assert policy.retry_after_ms({"retry-after": "30"}) == 2_000
    assert policy.retry_after_ms({"retry-after-ms": "250"}) == 250
