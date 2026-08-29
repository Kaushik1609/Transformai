"""Deterministic advisory generator for Phase 6."""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext
from app.transformation.generators.base import Generator


class AdvisoryGenerator(Generator):
    """Produce a structured advisory from canonical content."""

    output_type = "advisory"

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

        situation = summary or "(no situation summary available)"
        findings = [kp.get("text", "") for kp in key_points if kp.get("text")]
        actions = [r.get("text", "") for r in recommendations if r.get("text")]

        lines = [
            f"# Advisory: {title}",
            "",
            "## Situation",
            situation,
        ]
        if findings:
            lines.append("")
            lines.append("## Key findings")
            lines.extend(f"- {f}" for f in findings)
        if actions:
            lines.append("")
            lines.append("## Recommended actions")
            lines.extend(f"- {a}" for a in actions)

        return {
            "title": title,
            "type": "advisory",
            "situation": situation,
            "findings": findings,
            "recommendations": actions,
            "text": "\n".join(lines),
        }
