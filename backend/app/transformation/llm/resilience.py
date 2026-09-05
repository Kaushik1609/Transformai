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

The provider-agnostic primitives (error classification, retry policy, circuit
breaker, health, redaction) live in ``app.core.resilience`` and are shared with
the embedding resilience layer (Phase 11G).  Re-exporting them here keeps
every existing import path and the LLM ``ProviderManager`` behavior unchanged.

The manager wraps the existing `LLMProvider.generate_text(...)` contract and is
itself an `LLMProvider`, so generators remain retry-unaware and backward
compatible.  Prompt construction, RAG context and source evidence are NEVER
modified here; the exact same ``system_prompt`` and ``user_content`` handed to
the manager are forwarded to the underlying provider.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from app.core.resilience import (
    CircuitBreaker,
    CircuitState,
    ErrorCategory,
    ErrorClassification,
    HealthState,
    ProviderCallError,
    ProviderHealth,
    RetryPolicy,
    classify_error,
    redact_secrets,
)
from app.transformation.llm.provider import LLMProvider

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "ErrorCategory",
    "ErrorClassification",
    "HealthState",
    "ProviderCallError",
    "ProviderHealth",
    "ProviderManager",
    "RetryPolicy",
    "classify_error",
    "redact_secrets",
]


# Kept for backward compatibility with existing call sites (e.g. the
# transformation graph), identical to the shared core implementation.
_redact = redact_secrets


def _safe_message(exc: BaseException) -> str:
    """Return a bounded, credential-safe error message."""
    message = str(exc) or exc.__class__.__name__
    return redact_secrets(message)[:500]


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