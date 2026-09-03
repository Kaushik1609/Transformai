"""Advisory generator.

Produces structured advisory content from canonical content.

When an LLM provider is injected it generates via prompts + schema validation.
When no provider is supplied it falls back to the deterministic Phase 6
rendering so existing behavior and tests are preserved.
"""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext
from app.transformation.generators.base import Generator
from app.transformation.generators.common import generate_structured_output
from app.transformation.output_schemas import Advisory


class AdvisoryGenerator(Generator):
    """Produce a structured advisory from canonical content."""

    output_type = "advisory"

    def generate(
        self,
        *,
        canonical: dict[str, Any],
        config: dict[str, Any],
        rag_context: RAGContext | None = None,
        brief: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.llm_provider is not None:
            return generate_structured_output(
                output_type="advisory",
                schema_cls=Advisory,
                output_name="Advisory",
                canonical=canonical,
                config=config,
                rag_context=rag_context,
                brief=brief,
                llm_provider=self.llm_provider,
            )
        return self._generate_deterministic(
            canonical=canonical, config=config, rag_context=rag_context, brief=brief
        )

    def _generate_deterministic(
        self,
        *,
        canonical: dict[str, Any],
        config: dict[str, Any],
        rag_context: RAGContext | None,
        brief: dict[str, Any] | None = None,
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
            "key_findings": findings,
            "recommended_actions": actions,
            "text": "\n".join(lines),
        }
