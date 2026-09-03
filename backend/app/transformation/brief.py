"""Shared canonical semantic brief for Phase 11C.

A single, output-agnostic, source-grounded representation of the trusted
canonical content plus bounded RAG evidence, derived deterministically (no LLM)
from already-canonicalized content.  All seven generators operate from one
reusable brief instead of each independently re-formatting / re-tokenizing the
full canonical + RAG payload.

Security contract (Phase 11A/11B preserved):
  * The brief is built once per job from the trusted canonical record and the
    server-produced RAG context; it never accepts client instructions.
  * Provided RAG evidence is bounded (``RAG_MAX_CONTEXT_CHARS``) and is treated
    as UNTRUSTED source data inside a dedicated evidence block, never as model
    instructions (prompt-injection boundary is preserved and surfaced).
  * No facts are invented: content is copied verbatim from canonical fields.

The ``render_brief_text(brief)`` helper produces the trusted user-content block
that generators present to the model (equivalent in spirit to the previous
``build_user_content`` but driven by the shared brief).
"""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext

# Downstream canonical "text"-oriented keys to propagate.
_CANONICAL_TEXT_FIELDS = (
    "title",
    "summary",
    "topics",
    "entities",
    "key_points",
    "claims",
    "statistics",
    "dates",
    "recommendations",
    "source_references",
)

_ITEM_KEYS = ("text", "value", "name")


def _flatten_items(items: Any, key: str = "text") -> list[str]:
    """Flatten canonical list items (dicts or scalars) into plain strings."""
    result: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            value = None
            for k in _ITEM_KEYS:
                if item.get(k):
                    value = item.get(k)
                    break
            if value:
                result.append(str(value))
        elif item:
            result.append(str(item))
    return result


def _bounded_evidence(rag_context: RAGContext | None, max_chars: int) -> str:
    """Return a bounded, trimmed evidence string from the RAG context.

    The evidence is bounded to ``max_chars`` so the brief never carries an
    unbounded payload, and it is kept as plain evidence text (not instructions).
    """
    if rag_context is None:
        return ""
    text = rag_context.assembled_text or ""
    if not text:
        return ""
    return text[:max_chars].strip()


def build_canonical_brief(
    canonical: dict[str, Any],
    rag_context: RAGContext | None = None,
    config: dict[str, Any] | None = None,
    *,
    max_evidence_chars: int | None = None,
) -> dict[str, Any]:
    """Build a deterministic, bounded, output-agnostic semantic brief.

    Returns a JSON-compatible dict that every generator can consume.  It
    preserves all key canonical information (title, summary, key points,
    claims, statistics, dates, recommendations, source references) plus bounded
    trusted RAG evidence and citations.  No facts are invented.

    ``config`` may be supplied to expose the resolved generation context inside
    the brief (audience/tone/objective); it is optional and never treated as a
    trusted source of unverified factual content.
    """
    brief: dict[str, Any] = {}

    for field in _CANONICAL_TEXT_FIELDS:
        value = canonical.get(field)
        if isinstance(value, list):
            brief[field] = _flatten_items(value)
        elif value is not None:
            brief[field] = value

    # Bounded RAG evidence + citation provenance (never instructions).
    max_chars = max_evidence_chars
    if max_chars is None:
        from app.core.config import settings

        max_chars = settings.RAG_MAX_CONTEXT_CHARS
    evidence = _bounded_evidence(rag_context, max_chars)
    brief["rag_evidence"] = evidence
    brief["rag_citations"] = [
        {
            "source_id": c.source_id,
            "chunk_id": c.chunk_id,
            "chunk_index": c.chunk_index,
            "evidence": c.evidence,
            "relevance_score": c.relevance_score,
        }
        for c in (rag_context.citations if rag_context else [])
    ] if rag_context is not None else []

    # Sanity guard: a brief without any title/summary is not usable.
    if not brief.get("title") and not brief.get("summary"):
        brief["title"] = canonical.get("title") or "Untitled source"

    return brief


def render_brief_text(brief: dict[str, Any]) -> str:
    """Render the shared brief into the trusted user-content block for the model.

    This mirrors the earlier ``build_user_content`` formatting but is driven by
    the shared brief so every generator presents identical grounded source
    material.  RAG evidence is always wrapped in a dedicated UNTRUSTED block.
    """
    lines: list[str] = []

    title = brief.get("title") or "Untitled source"
    summary = brief.get("summary") or ""
    lines.append(f"TITLE: {title}")
    if summary:
        lines.append(f"SUMMARY: {summary}")

    topics = brief.get("topics") or []
    if topics:
        lines.append("TOPICS: " + "; ".join(str(t) for t in topics))

    entities = brief.get("entities") or []
    if entities:
        lines.append("ENTITIES: " + "; ".join(str(e) for e in entities))

    key_points = brief.get("key_points") or []
    if key_points:
        lines.append("KEY POINTS:")
        lines.extend(f"- {p}" for p in key_points)

    claims = brief.get("claims") or []
    if claims:
        lines.append("CLAIMS:")
        lines.extend(f"- {c}" for c in claims)

    statistics = brief.get("statistics") or []
    if statistics:
        lines.append("STATISTICS:")
        lines.extend(f"- {s}" for s in statistics)

    dates = brief.get("dates") or []
    if dates:
        lines.append("DATES:")
        lines.extend(f"- {d}" for d in dates)

    recommendations = brief.get("recommendations") or []
    if recommendations:
        lines.append("RECOMMENDATIONS/ACTIONS:")
        lines.extend(f"- {r}" for r in recommendations)

    evidence = (brief.get("rag_evidence") or "").strip()
    if evidence:
        lines.append("")
        lines.append("ADDITIONAL RETRIEVED SOURCE CONTEXT (UNTRUSTED EVIDENCE):")
        lines.append("<source_evidence>")
        lines.append(evidence)
        lines.append("</source_evidence>")

    return "\n".join(lines)
