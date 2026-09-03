"""Task-aware retrieval query formulation for Phase 11B.

Constructs bounded, semantically rich retrieval queries from canonical
content and generation configuration. Avoids raw prompt injection or
excessively long paragraph queries.
"""

from __future__ import annotations

from typing import Any


def formulate_retrieval_query(
    canonical: dict[str, Any],
    config: dict[str, Any] | None = None,
    *,
    max_length: int = 300,
) -> str:
    """Formulate a compact, task-relevant query string for dense retrieval.

    Combines canonical title, key topics, communication objective, and target
    audience into a coherent search query without including arbitrary prompt
    instructions.
    """
    parts: list[str] = []

    title = (canonical.get("title") or "").strip()
    if title:
        parts.append(title)

    topics = canonical.get("topics") or []
    topic_words: list[str] = []
    for t in topics[:4]:
        if isinstance(t, str) and t.strip():
            topic_words.append(t.strip())
        elif isinstance(t, dict):
            val = t.get("value") or t.get("name")
            if val:
                topic_words.append(str(val))
    if topic_words:
        parts.append(" ".join(topic_words))

    key_points = canonical.get("key_points") or []
    if key_points and isinstance(key_points[0], str) and key_points[0].strip():
        parts.append(key_points[0].strip())

    if config:
        objective = (config.get("communication_objective") or "").strip()
        audience = (config.get("target_audience") or "").strip()
        if objective:
            parts.append(objective)
        if audience:
            parts.append(audience)

    combined = " ".join(parts).strip()
    if not combined:
        summary = (canonical.get("summary") or "").strip()
        combined = summary[:max_length] if summary else "source overview facts"

    return combined[:max_length].strip()
