"""Resilience wrapper for embedding providers (Phase 11G).

``EmbeddingResilientProvider`` wraps any ``EmbeddingProvider`` with the same
provider-agnostic primitives used by the Phase 11D LLM ``ProviderManager``
(error classification, exponential backoff + jitter, Retry-After honoring,
circuit breaker, health state, credential redaction) while remaining an
``EmbeddingProvider`` itself.

LLM and embedding providers stay fully decoupled: this adapter has no
relationship to ``LLMProvider``; it only imports the shared generic resilience
core from ``app.core.resilience``.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from app.core.config import settings
from app.core.resilience import (
    CircuitBreaker,
    CircuitState,
    HealthState,
    ProviderCallError,
    ProviderHealth,
    RetryPolicy,
    classify_error,
    redact_secrets,
)
from app.embeddings.base import EmbeddingProvider


class EmbeddingResilientProvider(EmbeddingProvider):
    """Bounded-retry, circuit-broken wrapper around an embedding provider.

    Behavior mirrors the LLM resilience contract:

      - transient errors (429 with Retry-After honored, 5xx, timeouts, network)
        retry up to ``max_attempts`` with exponential backoff + jitter;
      - permanent errors (auth, invalid model, bad request) fail immediately
        and open the circuit;
      - provider health/circuit state are exposed for diagnostics;
      - error messages are redacted so no credentials leak.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        *,
        max_attempts: int | None = None,
        retry_policy: RetryPolicy | None = None,
        breaker_failure_threshold: int = 2,
        breaker_cooldown_seconds: float = 15.0,
        sleep: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._provider = provider
        self._max_attempts = (
            max_attempts if max_attempts is not None else settings.EMBEDDING_MAX_RETRIES + 1
        )
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._breaker = CircuitBreaker(
            failure_threshold=breaker_failure_threshold,
            cooldown_seconds=breaker_cooldown_seconds,
            now=monotonic or time.monotonic,
        )
        self._health = ProviderHealth(self._breaker)
        self.last_error: str | None = None
        self.last_metadata: dict[str, Any] = {}

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        start = self._monotonic()
        if not self._breaker.allow_call():
            self.last_error = "Embedding circuit open; provider unavailable."
            raise ProviderCallError(self.last_error)

        attempts = 0
        last_error: BaseException | None = None
        last_category_value = "unknown"
        while True:
            try:
                vectors = self._provider.embed_texts(texts)
                self._breaker.record_success()
                self._health.note_success()
                self.last_error = None
                self._set_last_metadata(
                    provider=type(self._provider).__name__,
                    attempts=attempts + 1,
                    max_attempts=self._max_attempts,
                    final_status="completed",
                    retryable=True,
                    latency_ms=self._elapsed_ms(start),
                )
                return vectors
            except Exception as exc:  # noqa: BLE001 - resilience layer boundary
                attempts += 1
                classification = classify_error(exc)
                last_error = exc
                last_category_value = classification.category.value
                self._breaker.record_failure(classification)
                self._health.note_failure(classification)

                if not classification.transient:
                    self.last_error = redact_secrets(str(exc))[:500]
                    self._set_last_metadata(
                        provider=type(self._provider).__name__,
                        attempts=attempts,
                        max_attempts=self._max_attempts,
                        final_status="failed",
                        retryable=False,
                        latency_ms=self._elapsed_ms(start),
                        last_error_type=last_category_value,
                        last_error_message=self.last_error,
                    )
                    raise ProviderCallError(
                        f"Embedding failed permanently ({last_category_value}): "
                        f"{self.last_error}"
                    ) from exc

                if attempts >= self._max_attempts:
                    self.last_error = redact_secrets(str(exc))[:500]
                    self._set_last_metadata(
                        provider=type(self._provider).__name__,
                        attempts=attempts,
                        max_attempts=self._max_attempts,
                        final_status="failed",
                        retryable=True,
                        latency_ms=self._elapsed_ms(start),
                        last_error_type=last_category_value,
                        last_error_message=self.last_error,
                    )
                    raise ProviderCallError(
                        f"Embedding failed after {self._max_attempts} attempt(s) "
                        f"({last_category_value}): {self.last_error}"
                    ) from exc

                delay = self._retry_policy.delay_for(attempts - 1, classification)
                self._sleep(delay)

    # -- diagnostics -------------------------------------------------------

    def provider_health(self) -> HealthState:
        return self._health.state()

    def circuit_state(self) -> CircuitState:
        return self._breaker.state

    # -- internal helpers ---------------------------------------------------

    def _elapsed_ms(self, start: float) -> int:
        return int((self._monotonic() - start) * 1000)

    def _set_last_metadata(self, **fields: Any) -> None:
        fields["provider"] = fields.get("provider", type(self._provider).__name__)
        self.last_metadata = {k: v for k, v in fields.items() if v is not None}