"""Build an LLM provider from application settings.

Provider selection is explicit:

* ``fake``   — deterministic, offline, no credentials required.
* ``openai`` / ``gemini`` — real providers that REQUIRE ``LLM_API_KEY``.

When a real provider is configured but ``LLM_API_KEY`` is missing, the factory
raises a clear ``ValueError`` instead of silently falling back to
``FakeLLMProvider`` (Phase 11J-A).  This matches the embedding provider
contract and prevents offline "fake" output from ever being mistaken for real
LLM generation; there is intentionally no implicit fallback.

``build_resilient_provider`` wraps the selected provider in a Phase 11D
``ProviderManager`` so retries, backoff, circuit breaking, health and an
optional fallback are enabled in one place while keeping the provider contract
backward compatible.
"""

from __future__ import annotations

from app.core.config import settings
from app.transformation.llm.fake import FakeLLMProvider
from app.transformation.llm.gemini_provider import GeminiLLMProvider
from app.transformation.llm.openai_provider import OpenAILLMProvider
from app.transformation.llm.provider import LLMProvider
from app.transformation.llm.resilience import ProviderManager, RetryPolicy


def build_llm_provider(provider: str | None = None) -> LLMProvider:
    """Return an LLM provider instance based on settings.

    Raises:
        ValueError: Unknown provider name, or an explicitly selected real
            provider (``openai``/``gemini``) missing its ``LLM_API_KEY``.
            Error messages never contain credential values.
    """
    name = (provider or settings.LLM_PROVIDER or "openai").strip().lower()
    api_key = (settings.LLM_API_KEY or "").strip()
    if name == "fake":
        return FakeLLMProvider()
    if name == "openai":
        if not api_key:
            raise ValueError(
                "LLM_PROVIDER=\"openai\" requires LLM_API_KEY to be set. "
                "Set LLM_API_KEY or configure LLM_PROVIDER=\"fake\" for offline/tests."
            )
        return OpenAILLMProvider()
    if name == "gemini":
        if not api_key:
            raise ValueError(
                "LLM_PROVIDER=\"gemini\" requires LLM_API_KEY to be set. "
                "Set LLM_API_KEY or configure LLM_PROVIDER=\"fake\" for offline/tests."
            )
        return GeminiLLMProvider()
    raise ValueError(f"Unsupported LLM provider: {name!r}")


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
    if name == "gemini":
        if not (settings.LLM_API_KEY or "").strip():
            raise ValueError(
                "LLM_FALLBACK_PROVIDER='gemini' requires LLM_API_KEY to be set."
            )
        return GeminiLLMProvider()
    raise ValueError(f"Unsupported fallback LLM provider: {name!r}")
