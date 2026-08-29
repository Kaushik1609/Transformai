"""Provider-independent output generator interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.rag.schemas import RAGContext


class Generator(ABC):
    """Produce one output artefact from canonical content and optional RAG context.

    Phase 6 generators are deterministic/basic implementations used to prove
    the one-source-to-many-outputs workflow.  The full Phase 7 prompt-engineering
    system is intentionally out of scope here.
    """

    output_type: str = ""

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
        should include a human-readable `text` representation plus optional
        metadata (e.g. `mime_type`, `title`).
        """
