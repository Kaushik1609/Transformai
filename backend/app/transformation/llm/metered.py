"""Phase 11L-C — worker-side LLM metering wrapper.

``MeteredLLMProvider`` wraps any ``LLMProvider`` (proxy interface via
``__getattr__`` so resilience ``last_metadata`` keeps flowing) and records
LLM request count, latency and failures per provider label. These counters are
incremented in the worker process and pushed to the shared Redis metric keys by
the worker, then surfaced through the backend ``/metrics`` endpoint.

The wrapper is purely additive and fail-open: a metrics problem never affects
generation.
"""

from __future__ import annotations

import time

from app.core.metrics import metrics
from app.transformation.llm.provider import LLMProvider


class MeteredLLMProvider(LLMProvider):
    """Transparent LLM provider wrapper that records request metrics."""

    def __init__(
        self,
        provider: LLMProvider,
        provider_name: str | None = None,
    ) -> None:
        self._provider = provider
        self._provider_name = (
            provider_name or getattr(provider, "provider_name", None) or "unknown"
        )

    def __getattr__(self, name: str):  # pragma: no cover - trivial delegation
        return getattr(self._provider, name)

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        started = time.monotonic()
        try:
            result = self._provider.generate_text(
                system_prompt=system_prompt, user_content=user_content
            )
        except Exception:
            duration = time.monotonic() - started
            metrics.inc("llm_failures_total", {"provider": self._provider_name})
            metrics.observe(
                "llm_request_duration_seconds",
                duration,
                {"provider": self._provider_name},
            )
            raise
        duration = time.monotonic() - started
        metrics.inc("llm_requests_total", {"provider": self._provider_name})
        metrics.observe(
            "llm_request_duration_seconds",
            duration,
            {"provider": self._provider_name},
        )
        return result


__all__ = ["MeteredLLMProvider"]