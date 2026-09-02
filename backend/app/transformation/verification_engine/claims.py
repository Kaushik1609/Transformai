"""Claim extraction for the Phase 8 verification engine.

Deterministic, offline extraction of checkable factual statements from a
generated output's structured content.  Purely stylistic, decorative, or
placeholder text (headings, visual cues, fake-provider defaults) is excluded so
the grounding/consistency scores reflect real assertions only.

A claim is only emitted when it carries a specificity signal:

- a number, percentage, or date; or
- at least ``_MIN_MEANINGFUL_LONG_CLAIM`` content-bearing terms (a long
  declarative assertion); or
- a term that matches a named entity/topic in the source canonical content.
"""

from __future__ import annotations

import re
from typing import Any

from app.transformation.verification_engine.text_utils import (
    extract_dates,
    extract_numbers,
    extract_percentages,
    meaningful_terms,
    normalize_text,
    split_bullets,
    split_sentences,
)

# A short declarative sentence needs this many content-bearing terms before it
# is treated as a factual assertion rather than a fragment/heading.
_MIN_MEANINGFUL_LONG_CLAIM = 5

# Visual/stylistic cues produced by the deterministic providers or renderers.
_DECORATIVE_FRAGMENTS: frozenset[str] = frozenset(
    {
        "chart or diagram",
        "icon or chart",
        "b-roll footage",
        "visual recommendation",
        "visual suggestion",
        "speaker notes",
        "speaker note",
        "title",
        "narrate",
        "explain",
        "message",
        "key message one",
        "key message two",
        "key message three",
    }
)

_STRUCTURAL_HEADING_RE = re.compile(
    r"^(?:slide|section|scene|chapter)\s+\d+$", re.IGNORECASE
)

# Inline section headings such as "# Executive Summary: Platform Capacity Report"
# that survive bullet/sentence splitting must never be treated as claims.
_EMBEDDED_HEADING_RE = re.compile(
    r"^(?:executive summary|key findings|key facts|recommendations|action items|"
    r"source context|overview|conclusions|next steps)\b\s*:",
    re.IGNORECASE,
)


def flatten_content(output: dict[str, Any]) -> list[str]:
    """Collect every non-empty string leaf from a structured output mapping."""
    segments: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            value = node.strip()
            if value:
                segments.append(value)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(output)
    return segments


def candidate_segments(output: dict[str, Any]) -> list[str]:
    """Return normalized, de-duplicated bullet/sentence segments from output."""
    seen: set[str] = set()
    result: list[str] = []
    for text in flatten_content(output):
        for segment in split_bullets(text) + split_sentences(text):
            cleaned = segment.strip()
            normalized = normalize_text(cleaned)
            if not cleaned or not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(cleaned)
    return result


def _clean_segment(text: str) -> str:
    """Strip light markdown and leading structural markers from a segment."""
    cleaned = re.sub(r"^[#>*-]\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\*+", "", cleaned)
    return cleaned.strip()


def _is_decorative(text: str) -> bool:
    """Return True for structural headings and non-factual placeholder text."""
    if _STRUCTURAL_HEADING_RE.search(text):
        return True
    if _EMBEDDED_HEADING_RE.match(text):
        return True
    normalized = normalize_text(text)
    if "deterministic" in normalized:
        return True
    return normalized in _DECORATIVE_FRAGMENTS


def _has_entity_signal(meaningful: set[str], canonical: dict[str, Any] | None) -> bool:
    """Return True when a claim term matches an entity/topic from the source."""
    if not canonical:
        return False
    for key in ("entities", "topics"):
        items = canonical.get(key) or []
        for item in items:
            if not item:
                continue
            name = ""
            if isinstance(item, dict):
                name = item.get("name") or item.get("value") or item.get("text") or ""
            elif isinstance(item, str):
                name = item
            if not name:
                continue
            entity_terms = meaningful_terms(name)
            if entity_terms and entity_terms & meaningful:
                return True
    return False


def _classify(text: str, canonical: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build a structured Claim record, or None for non-factual segments."""
    cleaned = _clean_segment(text)
    if not cleaned:
        return None
    if _is_decorative(cleaned):
        return None

    numbers = extract_numbers(cleaned)
    percentages = extract_percentages(cleaned)
    dates = extract_dates(cleaned)
    meaningful = meaningful_terms(cleaned)

    if len(meaningful) < 3:
        return None

    has_signal = (
        bool(numbers or percentages or dates)
        or len(meaningful) >= _MIN_MEANINGFUL_LONG_CLAIM
        or _has_entity_signal(meaningful, canonical)
    )
    if not has_signal:
        return None

    if percentages:
        claim_type = "percentage"
    elif dates:
        claim_type = "date"
    elif numbers:
        claim_type = "numeric"
    else:
        claim_type = "factual"

    return {
        "text": cleaned,
        "normalized_text": normalize_text(cleaned),
        "claim_type": claim_type,
        "numbers": numbers,
        "dates": dates,
        "source_position": None,
        "confidence": 1.0,
    }


def extract_claims(
    output: dict[str, Any],
    canonical: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return the checkable factual claims found in a generated output."""
    claims: list[dict[str, Any]] = []
    for index, segment in enumerate(candidate_segments(output)):
        claim = _classify(segment, canonical)
        if claim is None:
            continue
        claim["id"] = f"c{index}"
        claims.append(claim)
    return claims