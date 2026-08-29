"""Build an LLM provider from application settings.

The default provider ("openai") requires an API key; when credentials are
absent the factory falls back to the deterministic FakeLLMProvider so the
application stays runnable offline and in tests.  Explicitly passing a
provider name always attempts that provider.
"""

from __future__ import annotations

from app.core.config import settings
from app.transformation.llm.fake import FakeLLMProvider
from app.transformation.llm.openai_provider import OpenAILLMProvider
from app.transformation.llm.provider import LLMProvider


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
