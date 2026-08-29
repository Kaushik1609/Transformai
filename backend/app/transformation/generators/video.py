"""Video package generator.

Produces a complete video package: title, script, storyboard, scene
descriptions, narration, subtitles and visual recommendations.  This is a
structured content package only — automated video rendering is explicitly out
of scope for the MVP (see DEVELOPMENT_PLAN and PRD).
"""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext
from app.transformation.generators.base import Generator
from app.transformation.generators.common import generate_structured_output
from app.transformation.output_schemas import VideoPackage


class VideoGenerator(Generator):
    """Produce a complete structured video package."""

    output_type = "video"

    def generate(
        self,
        *,
        canonical: dict[str, Any],
        config: dict[str, Any],
        rag_context: RAGContext | None = None,
    ) -> dict[str, Any]:
        return generate_structured_output(
            output_type="video",
            schema_cls=VideoPackage,
            output_name="Video Package",
            canonical=canonical,
            config=config,
            rag_context=rag_context,
            llm_provider=self.llm_provider,
        )
