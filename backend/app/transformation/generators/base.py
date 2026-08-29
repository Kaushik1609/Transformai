"""Provider-independent output generator interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.rag.schemas import RAGContext
from app.transformation.llm.provider import LLMProvider


class Generator(ABC):
    """Produce one output artefact from canonical content and optional RAG context.

    Phase 6 used deterministic/basic implementations to prove the
    one-source-to-many-outputs workflow.  Phase 7 upgrades those generators to
    use the LLM layer, schema-validated structured output and (for
    presentations) a real PPTX renderer.

    The `generate` method signature is intentionally unchanged so existing
    Phase 6 call sites and tests continue to work.  An optional `llm_provider`
    is injected at construction time; when absent, generators fall back to a
    deterministic FakeLLMProvider so offline/test environments stay reliable.
    """

    output_type: str = ""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider

    @abstractmethod
    def generate(
        self,
        *,
        canonical: dict[str, Any],
        config: dict[str, Any],
        rag_context: RAGContext | None = None,
    ) -> dict[str, Any]:
        """Return a JSON-compatible structured output.

        The returned mapping is persisted as the output's structured_content and
        should include a non-empty human-readable `text` representation plus
        metadata (e.g. `mime_type`, `title`).
        """
