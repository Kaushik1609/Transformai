"""Infographic generator.

Produces key messages, sections, a layout recommendation and visual
suggestions from canonical content.  This is a content/structure package —
actual infographic image rendering is explicitly out of scope (Phase 10+).
"""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext
from app.transformation.generators.base import Generator
from app.transformation.generators.common import generate_structured_output
from app.transformation.output_schemas import Infographic


class InfographicGenerator(Generator):
    """Produce an infographic content and layout package."""

    output_type = "infographic"

    def generate(
        self,
        *,
        canonical: dict[str, Any],
        config: dict[str, Any],
        rag_context: RAGContext | None = None,
        brief: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return generate_structured_output(
            output_type="infographic",
            schema_cls=Infographic,
            output_name="Infographic",
            canonical=canonical,
            config=config,
            rag_context=rag_context,
            brief=brief,
            llm_provider=self.llm_provider,
        )
