"""Build an LLM provider from application settings.

The default provider ("openai") requires an API key; when credentials are
absent the factory falls back to the deterministic FakeLLMProvider so the
application stays runnable offline and in tests.  Explicitly passing a
provider name always attempts that provider.

``build_resilient_provider`` wraps the selected provider in a Phase 11D
``ProviderManager`` so retries, backoff, circuit breaking, health and an
optional fallback are enabled in one place while keeping the provider contract
backward compatible.
"""

from __future__ import annotations

from app.core.config import settings
from app.transformation.llm.fake import FakeLLMProvider
from app.transformation.llm.openai_provider import OpenAILLMProvider
from app.transformation.llm.provider import LLMProvider
from app.transformation.llm.resilience import ProviderManager, RetryPolicy


def build_llm_provider(provider: str | None = None) -> LLMProvider:
    """Return an LLM provider instance based on settings."""
    name = (provider or settings.LLM_PROVIDER or "openai").strip().lower()
    if name == "fake":
        return FakeLLMProvider()
    if name != "openai":
        raise ValueError(f"Unsupported LLM provider: {name!r}")
    if not (settings.LLM_API_KEY or "").strip():
        return FakeLLMProvider()
    return OpenAILLMProvider()


def build_resilient_provider() -> ProviderManager:
    """Return a resilient ProviderManager around the configured primary provider.

    An optional fallback provider is used only when ``LLM_FALLBACK_PROVIDER`` is
    configured AND a safe provider can be built for it.  No fallback, and no
    additional API keys, are required for resilience.
    """
    primary = build_llm_provider()
    fallback: LLMProvider | None = None
    fallback_name = (settings.LLM_FALLBACK_PROVIDER or "").strip().lower()
    if fallback_name:
        fallback = _build_fallback_provider(fallback_name)

    return ProviderManager(
        primary,
        fallback=fallback,
        max_attempts=settings.LLM_RETRY_MAX_ATTEMPTS,
        retry_policy=RetryPolicy(
            base_delay=settings.LLM_RETRY_BASE_DELAY,
            max_delay=settings.LLM_RETRY_MAX_DELAY,
            jitter=settings.LLM_RETRY_JITTER,
            max_429_wait=settings.LLM_RETRY_MAX_429_WAIT,
        ),
    )


def _build_fallback_provider(name: str) -> LLMProvider:
    """Build an optional fallback provider atomically or raise a clear error."""
    if name == "fake":
        return FakeLLMProvider()
    if name == "openai":
        # A real OpenAI fallback requires a key; if absent, there is no safe
        # fallback to use, so we do not silently inject one.
        if not (settings.LLM_API_KEY or "").strip():
            raise ValueError(
                "LLM_FALLBACK_PROVIDER='openai' requires LLM_API_KEY to be set."
            )
        return OpenAILLMProvider()
    raise ValueError(f"Unsupported fallback LLM provider: {name!r}")
