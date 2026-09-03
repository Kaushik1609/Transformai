"""Build the user-content block handed to the LLM for generation.

Combines the canonical content representation with optional RAG context so
the generator is always source-grounded.  This is the single place that
formats source material for Phase 7 prompts.

Phase 11C: the formatting is driven by the shared canonical semantic brief
(``app.transformation.brief``).  ``build_user_content`` preserves its original
signature for backward compatibility, but internally builds the brief and
renders it, so a caller that passes an explicit ``brief`` reuses the shared
brief instead of re-formatting the raw canonical/RAG payload.
"""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext
from app.transformation.brief import build_canonical_brief, render_brief_text


def build_user_content(
    canonical: dict[str, Any],
    rag_context: RAGContext | None = None,
    brief: dict[str, Any] | None = None,
) -> str:
    """Return a compact, grounded source brief for the model.

    If ``brief`` is provided it is used directly (shared Phase 11C brief);
    otherwise one is built deterministically from ``canonical`` + ``rag_context``,
    preserving backward compatibility for existing callers that pass only
    canonical/rag_context.
    """
    if brief is None:
        brief = build_canonical_brief(canonical, rag_context)
    return render_brief_text(brief)


def output_spec(schema_fields: list[str]) -> str:
    """Render the field list for a schema as a prompt directive."""
    return "{" + ", ".join(field for field in schema_fields) + "}"
