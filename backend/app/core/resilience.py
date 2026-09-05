"""Provider-agnostic resilience primitives.

Shared retry / circuit-breaking / health machinery used by the LLM provider
manager (Phase 11D) and the embedding provider manager (Phase 11G). This module
owns NO provider-specific behavior: error classification maps well-known
transport/HTTP conditions to transient vs permanent, ``RetryPolicy`` computes
backoff delays, and ``CircuitBreaker``/``ProviderHealth`` track per-provider
health state.
"""

from __future__ import annotations

import enum
import re
import time
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

class ErrorCategory(str, enum.Enum):
    RATE_LIMIT = "rate_limit"          # HTTP 429 (transient)
    SERVER = "server"                  # HTTP 5xx (transient)
    TIMEOUT = "timeout"                # request timeout (transient, bounded)
    CONNECTION = "connection"          # connection / network failure (transient)
    AUTH = "auth"                      # invalid key / authentication (permanent)
    INVALID_MODEL = "invalid_model"    # model not found / unsupported (permanent)
    BAD_REQUEST = "bad_request"        # malformed request / config (permanent)
    UNKNOWN = "unknown"                # ambiguous -> treated as transient, bounded


_PERMANENT_CATEGORIES = {
    ErrorCategory.AUTH,
    ErrorCategory.INVALID_MODEL,
    ErrorCategory.BAD_REQUEST,
}


class ErrorClassification:
    """Result of classifying a provider exception."""

    __slots__ = ("category", "transient", "retry_after", "http_status")

    def __init__(
        self,
        category: ErrorCategory,
        *,
        retry_after: float | None = None,
        http_status: int | None = None,
    ) -> None:
        self.category = category
        self.transient = category not in _PERMANENT_CATEGORIES
        self.retry_after = retry_after
        self.http_status = http_status


def _extract_retry_after(exc: BaseException) -> float | None:
    """Extract a Retry-After value (in seconds) from an exception, if present."""
    for name in ("retry_after", "retryAfter", "retry-after"):
        raw = getattr(exc, name, None)
        if raw is None:
            continue
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
        if isinstance(raw, str):
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
    return None


def classify_error(exc: BaseException) -> ErrorClassification:
    """Deterministically classify a provider exception as transient or permanent."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return _classify_by_status(status, exc)
    # No HTTP status attribute: fall back to known type detected by class name.
    name = exc.__class__.__name__
    lower = name.lower()
    if any(term in lower for term in ("ratelimit", "rate_limit")):
        return ErrorClassification(
            ErrorCategory.RATE_LIMIT,
            retry_after=_extract_retry_after(exc),
            http_status=429,
        )
    if any(term in lower for term in ("timeout",)):
        return ErrorClassification(ErrorCategory.TIMEOUT, http_status=408)
    if any(term in lower for term in ("connection", "network", "resets")):
        return ErrorClassification(ErrorCategory.CONNECTION)
    if any(term in lower for term in ("authentication", "auth", "permission", "unauthorized")):
        return ErrorClassification(ErrorCategory.AUTH, http_status=401)
    if any(term in lower for term in ("notfound", "not_found", "modelnotfound")):
        return ErrorClassification(ErrorCategory.INVALID_MODEL, http_status=404)
    if any(term in lower for term in ("badrequest", "malformed", "invalid", "unprocessable", "valueerror")):
        return ErrorClassification(ErrorCategory.BAD_REQUEST, http_status=400)
    if isinstance(exc, TimeoutError):
        return ErrorClassification(ErrorCategory.TIMEOUT, http_status=408)
    if isinstance(exc, (ConnectionError, ConnectionResetError, OSError)):
        return ErrorClassification(ErrorCategory.CONNECTION)
    # Ambiguous exception: treat as transient but bounded so an unexpected
    # network/transient failure is retried within the configured budget.
    return ErrorClassification(ErrorCategory.UNKNOWN)


def _classify_by_status(status: int, exc: BaseException) -> ErrorClassification:
    if status == 429:
        return ErrorClassification(
            ErrorCategory.RATE_LIMIT,
            retry_after=_extract_retry_after(exc),
            http_status=429,
        )
    if status in (500, 502, 503, 504):
        return ErrorClassification(ErrorCategory.SERVER, http_status=status)
    if status == 408:
        return ErrorClassification(ErrorCategory.TIMEOUT, http_status=status)
    if status == 409:
        return ErrorClassification(ErrorCategory.SERVER, http_status=status)
    if status in (401, 403):
        return ErrorClassification(ErrorCategory.AUTH, http_status=status)
    if status == 404:
        return ErrorClassification(ErrorCategory.INVALID_MODEL, http_status=status)
    if status in (400, 402, 422):
        return ErrorClassification(ErrorCategory.BAD_REQUEST, http_status=status)
    return ErrorClassification(ErrorCategory.UNKNOWN, http_status=status)


# ---------------------------------------------------------------------------
# Circuit breaker + provider health
# ---------------------------------------------------------------------------

class CircuitState(str, enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class HealthState(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"
    AUTH_FAILURE = "auth_failure"


class CircuitBreaker:
    """Simple per-provider circuit breaker.

    CLOSED → repeated transient failures → OPEN
    OPEN   → after cooldown → HALF_OPEN
    HALF_OPEN → successful probe → CLOSED (or failure → OPEN)
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 2,
        cooldown_seconds: float = 15.0,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._now = now or time.monotonic
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self._opened_at: float | None = None

    def allow_call(self) -> bool:
        """Whether a call may be attempted for this provider right now."""
        if self.state == CircuitState.OPEN:
            now = self._now()
            if self._opened_at is not None and (now - self._opened_at) >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED

    def record_failure(self, classification: ErrorClassification) -> None:
        if classification.category == ErrorCategory.AUTH:
            # Permanent auth/config failure: open the circuit and never retry.
            self.state = CircuitState.OPEN
            self._opened_at = self._now()
            return
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self._opened_at = self._now()
            return
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self._opened_at = self._now()


class ProviderHealth:
    """Lightweight, process-local per-provider health state."""

    def __init__(self, breaker: CircuitBreaker) -> None:
        self._breaker = breaker
        self._last_category: ErrorCategory | None = None

    def note_failure(self, classification: ErrorClassification) -> None:
        self._last_category = classification.category

    def note_success(self) -> None:
        self._last_category = None

    def state(self) -> HealthState:
        if self._breaker.state == CircuitState.OPEN:
            if self._last_category == ErrorCategory.AUTH:
                return HealthState.AUTH_FAILURE
            return HealthState.UNAVAILABLE
        if self._breaker.state == CircuitState.HALF_OPEN:
            return HealthState.RECOVERING
        if self._last_category == ErrorCategory.RATE_LIMIT:
            return HealthState.RATE_LIMITED
        if self._breaker.consecutive_failures > 0:
            return HealthState.DEGRADED
        return HealthState.HEALTHY

    @property
    def last_category(self) -> ErrorCategory | None:
        return self._last_category


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------

class RetryPolicy:
    """Exponential backoff with jitter, bounded by configured maximums."""

    def __init__(
        self,
        *,
        base_delay: float = 0.5,
        max_delay: float = 10.0,
        jitter: float = 0.2,
        max_429_wait: float = 30.0,
        random: Callable[[], float] | None = None,
    ) -> None:
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.max_429_wait = max_429_wait
        self._random = random or _default_random

    def delay_for(self, attempt: int, classification: ErrorClassification) -> float:
        """Return the sleep delay for a given attempt (0-based failed attempt count).

        ``attempt`` is the number of failures already observed (0 for the first
        retry after the first attempt).  Honors Retry-After for rate limits and
        clamps it to a safe configured maximum.
        """
        if classification.category == ErrorCategory.RATE_LIMIT and classification.retry_after is not None:
            wait = classification.retry_after
            if self.max_429_wait is not None and wait > self.max_429_wait:
                wait = self.max_429_wait
            if wait >= 0:
                return wait

        delay = self.base_delay * (2 ** attempt)
        if self.jitter > 0:
            factor = 1.0 + (self._random() * 2 - 1) * self.jitter
            delay *= factor
        if self.max_delay >= 0:
            delay = min(delay, self.max_delay)
        return max(0.0, delay)


def _default_random() -> float:
    import random

    return random.random()


# ---------------------------------------------------------------------------
# Shared error surface + secret redaction
# ---------------------------------------------------------------------------

class ProviderCallError(Exception):
    """Raised when a resilient provider call ultimately fails.

    Mirrors the provider's exception message without leaking credentials.
    """


_SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]+"
    r"|bearer\s+\S+"
    r"|(?:api[_-]?key|apikey|token|authorization|password|secret)\s*[:=]\s*\S+)"
)


def redact_secrets(message: str) -> str:
    """Return a bounded, credential-safe message with secret-shaped values removed."""
    return _SECRET_RE.sub("<redacted>", str(message))


def safe_message(exc: BaseException, *, limit: int = 500) -> str:
    """Return a bounded, credential-safe error message from an exception."""
    message = str(exc) or exc.__class__.__name__
    return redact_secrets(message)[:limit]