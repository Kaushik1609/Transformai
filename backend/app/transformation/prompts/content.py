"""Build the user-content block handed to the LLM for generation.

Combines the canonical content representation with optional RAG context so
the generator is always source-grounded.  This is the single place that
formats source material for Phase 7 prompts.
"""

from __future__ import annotations

from typing import Any

from app.rag.schemas import RAGContext


def _list_items(items: list[Any], key: str = "text") -> list[str]:
    """Flatten canonical items that may be dicts with a text label."""
    result: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            value = item.get(key) or item.get("value") or item.get("name")
            if value:
                result.append(str(value))
        elif item:
            result.append(str(item))
    return result


def build_user_content(canonical: dict[str, Any], rag_context: RAGContext | None = None) -> str:
    """Return a compact, grounded source brief for the model."""
    lines: list[str] = []

    title = canonical.get("title") or "Untitled source"
    summary = canonical.get("summary") or ""
    lines.append(f"TITLE: {title}")
    if summary:
        lines.append(f"SUMMARY: {summary}")

    topics = _list_items(canonical.get("topics", []), key="value")
    if topics:
        lines.append("TOPICS: " + "; ".join(topics))

    entities = _list_items(canonical.get("entities", []), key="name")
    if entities:
        lines.append("ENTITIES: " + "; ".join(entities))

    key_points = _list_items(canonical.get("key_points", []))
    if key_points:
        lines.append("KEY POINTS:")
        lines.extend(f"- {p}" for p in key_points)

    claims = _list_items(canonical.get("claims", []))
    if claims:
        lines.append("CLAIMS:")
        lines.extend(f"- {c}" for c in claims)

    statistics = _list_items(canonical.get("statistics", []))
    if statistics:
        lines.append("STATISTICS:")
        lines.extend(f"- {s}" for s in statistics)

    dates = _list_items(canonical.get("dates", []))
    if dates:
        lines.append("DATES:")
        lines.extend(f"- {d}" for d in dates)

    recommendations = _list_items(canonical.get("recommendations", []))
    if recommendations:
        lines.append("RECOMMENDATIONS/ACTIONS:")
        lines.extend(f"- {r}" for r in recommendations)

    if rag_context is not None and rag_context.assembled_text:
        lines.append("")
        lines.append("ADDITIONAL RETRIEVED SOURCE CONTEXT:")
        lines.append(rag_context.assembled_text)

    return "\n".join(lines)


def output_spec(schema_fields: list[str]) -> str:
    """Render the field list for a schema as a prompt directive."""
    return "{" + ", ".join(field for field in schema_fields) + "}"
