"""Retry and rate-limit handling for provider I/O.

The helpers here are deliberately pure (apart from the default config values) so
the retry policy can be tested without a network or a real provider.  The shape
is inspired by OpenCode's retry utilities: retry transient failures, honour a
provider's ``Retry-After`` headers, and stop immediately for terminal errors
such as authentication failures or exhausted quotas.
"""

from __future__ import annotations

import email.utils
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from .config import CONFIG

# Failures that may succeed if the request is sent again.  408/425 are request
# timeouts/too-early, 409 is a transient conflict, 429 is a rate limit, and
# 5xx/529 are provider-side failures or overload.
RETRYABLE_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})

# These messages mean the account cannot succeed until the user changes
# billing/plan settings, even when the HTTP status is normally retryable.
QUOTA_MARKERS = (
    "insufficient_quota",
    "insufficient quota",
    "exceeded your current quota",
    "quota exceeded",
    "quota exhausted",
    "billing hard limit",
    "billing quota",
    "credit balance",
    "insufficient credit",
    "out of credits",
    "no credits remaining",
    "payment required",
    "account is deactivated",
    "account has been disabled",
)


def _header(headers: Mapping[str, str] | None, name: str) -> str | None:
    """Read a header from either httpx.Headers or a plain mapping."""
    if not headers:
        return None
    value = headers.get(name)
    if value is not None:
        return value
    lowered = name.lower()
    for key, item in headers.items():
        if key.lower() == lowered:
            return item
    return None


def _clamp_ms(value: float, max_ms: float) -> int:
    if not math.isfinite(value):
        return 0
    return int(max(0.0, min(float(max_ms), round(value))))


def parse_retry_after_ms(
    headers: Mapping[str, str] | None,
    *,
    max_ms: float | None = None,
    now: datetime | None = None,
) -> int | None:
    """Return the provider-requested delay in milliseconds, or ``None``.

    Accepts ``retry-after-ms``, numeric ``retry-after`` seconds, or an HTTP
    date.  The result is clamped to ``0..max_ms`` (15 minutes by default) so a
    buggy or hostile header cannot stall a turn indefinitely.
    """
    limit = CONFIG.retry_after_max * 1000.0 if max_ms is None else max_ms

    raw_ms = _header(headers, "retry-after-ms")
    if raw_ms is not None:
        try:
            millis = float(raw_ms.strip())
        except ValueError:
            millis = math.nan
        if math.isfinite(millis):
            return _clamp_ms(millis, limit)

    raw = _header(headers, "retry-after")
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None

    try:
        seconds = float(value)
    except ValueError:
        seconds = math.nan
    if math.isfinite(seconds):
        return _clamp_ms(seconds * 1000.0, limit)

    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return _clamp_ms((parsed - current).total_seconds() * 1000.0, limit)


def is_retryable(
    status: int,
    body: str = "",
    headers: Mapping[str, str] | None = None,
) -> bool:
    """Classify an HTTP failure as temporary or terminal.

    ``x-should-retry`` is authoritative when present.  Otherwise known
    transient statuses are retryable, while obvious quota/billing exhaustion
    is terminal so the user sees the provider's message instead of a long wait.
    """
    override = (_header(headers, "x-should-retry") or "").strip().lower()
    if override in {"false", "0", "no", "off"}:
        return False
    if override in {"true", "1", "yes", "on"}:
        return True

    if status == 402:
        return False

    text = body.lower()
    if any(marker in text for marker in QUOTA_MARKERS):
        return False

    return status in RETRYABLE_STATUSES


def next_delay(
    attempt: int,
    retry_after_ms: int | None = None,
    *,
    base_delay: float = 2.0,
    max_delay: float = 10.0,
    jitter: float = 0.2,
    rng: random.Random | None = None,
) -> float:
    """Return the next wait in seconds for a zero-based retry ``attempt``.

    Backoff is exponential from ``base_delay`` and capped at ``max_delay``.
    A provider-requested delay wins when it is longer.  Jitter is multiplicative
    and symmetric (``±jitter``), so retries from multiple clients do not line up.
    """
    attempt = max(0, attempt)
    delay = min(base_delay * math.pow(2, attempt), max_delay)
    if jitter > 0 and delay > 0:
        random_fn = rng.random if rng is not None else random.random
        delay *= 1.0 + jitter * (2.0 * random_fn() - 1.0)
        # Keep the configured per-gap cap even with positive jitter.
        delay = min(delay, max_delay)
    if retry_after_ms:
        delay = max(delay, retry_after_ms / 1000.0)
    return max(0.0, delay)


@dataclass(frozen=True)
class RetryPolicy:
    """Concrete retry limits, normally loaded from :class:`Config`."""

    max_attempts: int = 10
    base_delay: float = 2.0
    max_delay: float = 10.0
    retry_after_max: float = 900.0
    jitter: float = 0.2
    timeout_attempts: int = 3

    @classmethod
    def from_config(cls) -> "RetryPolicy":
        return cls(
            max_attempts=CONFIG.retry_max_attempts,
            base_delay=CONFIG.retry_base_delay,
            max_delay=CONFIG.retry_max_delay,
            retry_after_max=CONFIG.retry_after_max,
            jitter=CONFIG.retry_jitter,
            timeout_attempts=CONFIG.retry_timeout_attempts,
        )

    def retry_after_ms(
        self,
        headers: Mapping[str, str] | None,
        *,
        now: datetime | None = None,
    ) -> int | None:
        return parse_retry_after_ms(
            headers,
            max_ms=self.retry_after_max * 1000.0,
            now=now,
        )

    def delay(
        self,
        attempt: int,
        retry_after_ms: int | None = None,
        *,
        rng: random.Random | None = None,
    ) -> float:
        return next_delay(
            attempt,
            retry_after_ms,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            jitter=self.jitter,
            rng=rng,
        )

    def should_retry(
        self,
        status: int,
        body: str = "",
        headers: Mapping[str, str] | None = None,
    ) -> bool:
        return is_retryable(status, body, headers)
