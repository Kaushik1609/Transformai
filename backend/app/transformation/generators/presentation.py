"""Presentation generator.

Produces slide structure, slide content, speaker notes and visual
recommendations from canonical content.  The structured output is designed to
be rendered into a real PPTX by `app.transformation.render.pptx`.

When an LLM provider is injected it generates via prompts + schema validation;
otherwise the deterministic FakeLLMProvider is used so offline/tests stay
reliable (and still produce a schema-valid structure).
"""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext
from app.transformation.generators.base import Generator
from app.transformation.generators.common import generate_structured_output
from app.transformation.output_schemas import PresentationStructure


class PresentationGenerator(Generator):
    """Produce a validated presentation structure."""

    output_type = "presentation"

    def generate(
        self,
        *,
        canonical: dict[str, Any],
        config: dict[str, Any],
        rag_context: RAGContext | None = None,
        brief: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return generate_structured_output(
            output_type="presentation",
            schema_cls=PresentationStructure,
            output_name="Presentation",
            canonical=canonical,
            config=config,
            rag_context=rag_context,
            brief=brief,
            llm_provider=self.llm_provider,
        )
