"""Deterministic executive summary generator for Phase 6."""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext
from app.transformation.generators.base import Generator


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
            "key_points": key_bullets,
            "recommendations": rec_bullets,
            "text": "\n".join(lines),
        }
