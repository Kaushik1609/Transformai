"""Phase 11D — LLM / provider resilience layer.

Centralized resilience for the LLM provider boundary.  This module owns ALL
application-level retry behavior:

    ProviderManager
      ├── classify exception (transient vs permanent)
      ├── retry policy (exponential backoff + jitter)
      ├── Retry-After honoring for 429
      ├── per-provider circuit breaker
      ├── per-provider health state
      └── optional fallback provider

The manager wraps the existing `LLMProvider.generate_text(...)` contract and is
itself an `LLMProvider`, so generators remain retry-unaware and backward
compatible.  Prompt construction, RAG context and source evidence are NEVER
modified here; the exact same ``system_prompt`` and ``user_content`` handed to
the manager are forwarded to the underlying provider.
"""

from __future__ import annotations

import enum
import re
import time
from typing import Any, Callable

from app.transformation.llm.provider import LLMProvider


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
# ProviderManager
# ---------------------------------------------------------------------------

class ProviderCallError(Exception):
    """Raised when a resilient provider call ultimately fails.

    Mirrors the provider's exception message without leaking credentials.
    """


class ProviderManager(LLMProvider):
    """Resilient wrapper around one or two LLM providers.

    Owns retry, backoff, Retry-After handling, circuit breaking, health and
    optional fallback.  Is itself an ``LLMProvider`` so it can be injected
    wherever a provider is expected without disturbing generators.

    Also exposes:

      - ``generate_text_with_metadata(...)`` -> returns ``{"text", "metadata"}``
      - ``last_metadata`` -> the resilience metadata of the most recent call

    for persistence without changing the ``LLMProvider.generate_text`` contract.
    """

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider | None = None,
        *,
        max_attempts: int = 3,
        retry_policy: RetryPolicy | None = None,
        breaker_failure_threshold: int = 2,
        breaker_cooldown_seconds: float = 15.0,
        sleep: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.max_attempts = max_attempts
        self.retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._breakers: dict[int, CircuitBreaker] = {}
        self.last_metadata: dict[str, Any] = {}

        now = monotonic or time.monotonic
        self._breaker_map = {
            id(primary): CircuitBreaker(
                failure_threshold=breaker_failure_threshold,
                cooldown_seconds=breaker_cooldown_seconds,
                now=now,
            )
        }
        providers = [primary]
        if fallback is not None:
            self._breaker_map[id(fallback)] = CircuitBreaker(
                failure_threshold=breaker_failure_threshold,
                cooldown_seconds=breaker_cooldown_seconds,
                now=now,
            )
            providers.append(fallback)
        self._health_map = {
            provider: ProviderHealth(self._breaker_map[id(provider)])
            for provider in providers
        }

    # -- public contract ---------------------------------------------------

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        result = self.generate_text_with_metadata(
            system_prompt=system_prompt, user_content=user_content
        )
        return result["text"]

    def generate_text_with_metadata(
        self, *, system_prompt: str, user_content: str
    ) -> dict[str, Any]:
        """Run the resilient call and return text plus bounded resilience metadata.

        Provider selection:

          - The circuit breaker is only consulted when a provider is selected
            (start of the call and when switching to the fallback).  Within a
            single call, retry attempts are governed by ``max_attempts`` and the
            backoff policy, so the breaker does not preempt the retry budget.
          - A permanent (non-retryable) error on the primary fails immediately;
            it only falls back if a fallback is explicitly configured.
          - Transient errors retry up to ``max_attempts``; if the primary's
            budget is exhausted a configured fallback is tried with its own
            budget.
        """
        start = self._monotonic()
        retried: list[dict[str, Any]] = []
        used_fallback = False
        last_error: BaseException | None = None
        last_class: ErrorClassification | None = None
        final_provider = self.primary

        chain = [self.primary]
        if self.fallback is not None:
            chain.append(self.fallback)

        fail_call = False
        for provider in chain:
            is_fallback = provider is self.fallback
            breaker = self._breaker(provider)
            health = self._health(provider)

            # Circuit gate evaluated at provider-selection time only.  A CLOSED
            # primary that becomes unhealthy via this call's retries records
            # failures that will open the circuit for subsequent calls, but the
            # current call still uses its full retry budget.
            if not breaker.allow_call():
                if is_fallback:
                    # Fallback also unhealthy: give up.
                    last_error = ProviderCallError("circuit open; no healthy provider")
                    final_provider = provider
                    fail_call = True
                    break
                used_fallback = True
                self._record_failure_attempt(
                    provider, ErrorClassification(ErrorCategory.UNKNOWN)
                )
                continue

            attempts = 0
            while True:
                try:
                    text = provider.generate_text(
                        system_prompt=system_prompt, user_content=user_content
                    )
                    breaker.record_success()
                    health.note_success()
                    final_provider = provider
                    self._set_last_metadata(
                        text=text,
                        provider=self._describe_provider(provider),
                        attempts=attempts + 1,
                        max_attempts=self.max_attempts,
                        retried=retried,
                        used_fallback=used_fallback,
                        retryable=True,
                        final_status="completed",
                        latency_ms=self._elapsed_ms(start),
                        last_error_type=None,
                        last_error_message=None,
                        last_attempt_at=self._iso_now(),
                    )
                    return {"text": text, "metadata": self.last_metadata}
                except Exception as exc:  # noqa: BLE001 - resilience layer boundary
                    last_error = exc
                    last_class = classify_error(exc)
                    breaker.record_failure(last_class)
                    health.note_failure(last_class)
                    attempts += 1

                    retried.append(
                        {
                            "attempt": attempts,
                            "error_type": last_class.category.value,
                            "http_status": last_class.http_status,
                            "retry_after": last_class.retry_after,
                            "message": _safe_message(exc),
                            "circuit_state": breaker.state.value,
                        }
                    )
                    retried = retried[-20:]  # bounded
                    final_provider = provider

                    if not last_class.transient:
                        # Permanent error: no retry and no fallback (a permanent
                        # failure such as auth or invalid model affects any
                        # provider sharing the same credentials/config). Fail.
                        self._set_last_metadata(
                            text=None,
                            provider=self._describe_provider(provider),
                            attempts=attempts,
                            max_attempts=self.max_attempts,
                            retried=retried,
                            used_fallback=used_fallback,
                            retryable=False,
                            final_status="failed",
                            latency_ms=self._elapsed_ms(start),
                            last_error_type=last_class.category.value,
                            last_error_message=_safe_message(exc),
                            last_attempt_at=self._iso_now(),
                        )
                        fail_call = True
                        break

                    if attempts < self.max_attempts:
                        delay = self.retry_policy.delay_for(attempts - 1, last_class)
                        self._sleep(delay)
                        continue

                    # Transient budget exhausted on the current provider.
                    if is_fallback or self.fallback is None:
                        self._set_last_metadata(
                            text=None,
                            provider=self._describe_provider(provider),
                            attempts=attempts,
                            max_attempts=self.max_attempts,
                            retried=retried,
                            used_fallback=used_fallback,
                            retryable=True,
                            final_status="failed",
                            latency_ms=self._elapsed_ms(start),
                            last_error_type=last_class.category.value,
                            last_error_message=_safe_message(exc),
                            last_attempt_at=self._iso_now(),
                        )
                        fail_call = True
                    else:
                        used_fallback = True
                    break  # exit inner retry loop -> next provider in chain

            if fail_call:
                break

        provider_name = self._describe_provider(final_provider)
        raise ProviderCallError(
            f"LLM call failed on provider {provider_name!r}"
            + (f": {_safe_message(last_error)}" if last_error is not None else "")
        ) from last_error

    # -- introspection helpers ----------------------------------------------

    def provider_health(self, provider: LLMProvider | None = None) -> HealthState:
        target = provider or self.primary
        return self._health(target).state()

    def circuit_state(self, provider: LLMProvider | None = None) -> CircuitState:
        target = provider or self.primary
        return self._breaker(target).state

    def primary_health(self) -> HealthState:
        return self._health(self.primary).state()

    def fallback_health(self) -> HealthState | None:
        if self.fallback is None:
            return None
        return self._health(self.fallback).state()

    # -- internal helpers ---------------------------------------------------

    def _breaker(self, provider: LLMProvider) -> CircuitBreaker:
        return self._breaker_map[id(provider)]

    def _health(self, provider: LLMProvider) -> ProviderHealth:
        return self._health_map[provider]

    def _describe_provider(self, provider: LLMProvider) -> str:
        return type(provider).__name__

    def _record_failure_attempt(
        self, provider: LLMProvider, classification: ErrorClassification
    ) -> dict[str, Any]:
        breaker = self._breaker(provider)
        health = self._health(provider)
        breaker.record_failure(classification)
        health.note_failure(classification)
        return {
            "attempt": self._breaker(provider).consecutive_failures,
            "error_type": classification.category.value,
            "http_status": classification.http_status,
            "retry_after": classification.retry_after,
            "message": "circuit open",
            "circuit_state": breaker.state.value,
        }

    def _elapsed_ms(self, start: float) -> int:
        return int((self._monotonic() - start) * 1000)

    def _iso_now(self) -> str:
        try:
            from datetime import datetime, timezone

            return datetime.now(timezone.utc).isoformat()
        except Exception:  # pragma: no cover - defensive
            return ""

    def _set_last_metadata(self, **fields: Any) -> None:
        meta: dict[str, Any] = {}
        for key, value in fields.items():
            if value is not None:
                meta[key] = value
        meta["provider"] = fields.get("provider", self._describe_provider(self.primary))
        self.last_metadata = meta


_SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]+"
    r"|bearer\s+\S+"
    r"|(?:api[_-]?key|apikey|token|authorization|password|secret)\s*[:=]\s*\S+)"
)


def _redact(message: str) -> str:
    return _SECRET_RE.sub("<redacted>", message)


def _safe_message(exc: BaseException) -> str:
    """Return a bounded, credential-safe error message."""
    message = str(exc) or exc.__class__.__name__
    return _redact(message)[:500]
