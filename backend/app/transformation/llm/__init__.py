"""Provider-neutral LLM layer for Phase 7 output generators.

Exposes a small `LLMProvider` abstraction so generators can call an LLM
without being coupled to one vendor.  A deterministic `FakeLLMProvider`
keeps tests and offline/local development working without network access,
mirroring the pattern already used by Phase 4 content intelligence.
"""

from __future__ import annotations

from app.transformation.llm.fake import FakeLLMProvider
from app.transformation.llm.factory import build_llm_provider
from app.transformation.llm.openai_provider import OpenAILLMProvider
from app.transformation.llm.provider import LLMProvider

__all__ = [
    "LLMProvider",
    "FakeLLMProvider",
    "OpenAILLMProvider",
    "build_llm_provider",
]
