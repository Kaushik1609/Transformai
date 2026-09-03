"""X / Twitter generator.

Produces a platform-optimized post or thread structure from canonical content.
The `thread` field carries the full post sequence; `text` is the human-readable
rendering.
"""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext
from app.transformation.generators.base import Generator
from app.transformation.generators.common import generate_structured_output
from app.transformation.output_schemas import XPost


class XGenerator(Generator):
    """Produce an X/Twitter post or thread structure."""

    output_type = "x"

    def generate(
        self,
        *,
        canonical: dict[str, Any],
        config: dict[str, Any],
        rag_context: RAGContext | None = None,
        brief: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return generate_structured_output(
            output_type="x",
            schema_cls=XPost,
            output_name="X/Twitter",
            canonical=canonical,
            config=config,
            rag_context=rag_context,
            brief=brief,
            llm_provider=self.llm_provider,
        )
