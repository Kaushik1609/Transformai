"""Executive summary generator.

Produces a concise structured executive summary from canonical content.

When an LLM provider is injected it generates via prompts + schema
validation.  When no provider is supplied it falls back to the deterministic
Phase 6 rendering so existing behavior and tests are preserved.
"""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext
from app.transformation.generators.base import Generator
from app.transformation.generators.common import generate_structured_output
from app.transformation.output_schemas import ExecutiveSummary


class SummaryGenerator(Generator):
    """Produce a concise structured executive summary from canonical content."""

    output_type = "summary"

    def generate(
        self,
        *,
        canonical: dict[str, Any],
        config: dict[str, Any],
        rag_context: RAGContext | None = None,
    ) -> dict[str, Any]:
        if self.llm_provider is not None:
            return generate_structured_output(
                output_type="summary",
                schema_cls=ExecutiveSummary,
                output_name="Executive Summary",
                canonical=canonical,
                config=config,
                rag_context=rag_context,
                llm_provider=self.llm_provider,
            )
        return self._generate_deterministic(
            canonical=canonical, config=config, rag_context=rag_context
        )

    def _generate_deterministic(
        self,
        *,
        canonical: dict[str, Any],
        config: dict[str, Any],
        rag_context: RAGContext | None,
    ) -> dict[str, Any]:
        title = canonical.get("title") or "Untitled source"
        summary = canonical.get("summary") or ""
        key_points = canonical.get("key_points") or []
        recommendations = canonical.get("recommendations") or []

        key_bullets = [kp.get("text", "") for kp in key_points if kp.get("text")]
        rec_bullets = [r.get("text", "") for r in recommendations if r.get("text")]

        lines = [f"# Executive Summary: {title}", "", summary or "(no summary available)"]
        if key_bullets:
            lines.append("")
            lines.append("## Key findings")
            lines.extend(f"- {b}" for b in key_bullets)
        if rec_bullets:
            lines.append("")
            lines.append("## Recommendations")
            lines.extend(f"- {b}" for b in rec_bullets)
        if rag_context is not None and rag_context.assembled_text:
            lines.append("")
            lines.append("## Source context")
            lines.append(rag_context.assembled_text)

        return {
            "title": title,
            "type": "summary",
            "summary": summary,
            "key_findings": key_bullets,
            "recommendations": rec_bullets,
            "text": "\n".join(lines),
        }
