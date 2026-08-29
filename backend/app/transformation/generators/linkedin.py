"""Deterministic LinkedIn post generator for Phase 6."""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext
from app.transformation.generators.base import Generator


class LinkedInGenerator(Generator):
    """Produce a publication-ready LinkedIn post from canonical content."""

    output_type = "linkedin"

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

        hooks = [
            key_points[0].get("text", "") if key_points else "",
            summary,
        ]
        hook = next((h for h in hooks if h), summary or title)

        bullets = [kp.get("text", "") for kp in key_points if kp.get("text")]
        body_lines = [f"Just published: {title}", "", hook]
        for b in bullets:
            body_lines.append(f"• {b}")
        body_lines.extend(["", "What are your thoughts?", "#Insights"])

        return {
            "title": title,
            "type": "linkedin",
            "hook": hook,
            "body": "\n".join(body_lines),
            "text": "\n".join(body_lines),
        }
