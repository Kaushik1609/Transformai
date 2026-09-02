"""Source evidence matching for the Phase 8 verification engine.

Each extracted claim is compared against the normalized source chunks using a
deterministic lexical-overlap strategy with explicit numeric/date consistency
checks.  The result distinguishes ``supported``, ``weakly_supported``, and
``unsupported`` claims rather than relying on blind substring matching.

A numeric or date mismatch on the closest matching chunk deliberately
outranks weak lexical support so an altered figure (e.g. ``50,000`` vs the
source's ``500``) is always surfaced as an unsupported claim.
"""

from __future__ import annotations

import re
from typing import Any

from app.transformation.verification_engine.text_utils import (
    extract_dates,
    extract_numbers,
    meaningful_terms,
)

# Lexical-overlap thresholds against the best matching source chunk.
_STRONG_OVERLAP = 0.55
_WEAK_OVERLAP = 0.30

# Strength ordering: supported > conflict > weak > none.
_STRENGTH_SUPPORTED = 2
_STRENGTH_CONFLICT = -2
_STRENGTH_WEAK = 1

_EVIDENCE_SNIPPET_MAX = 300


def _format_number(value: float) -> str:
    """Render a float compactly (``500`` not ``500.0``)."""
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _excerpt(text: str, limit: int = _EVIDENCE_SNIPPET_MAX) -> str:
    """Return a capped excerpt of source evidence."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _claim_excerpt(text: str, limit: int = 160) -> str:
    """Return a capped excerpt of a claim for warnings."""
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}…"


def analyze_claim(
    claim: dict[str, Any],
    source_chunks: list[str],
) -> dict[str, Any]:
    """Evaluate a single claim against all source chunks.

    Returns an evidence record with a verdict and a human-readable reason.
    """
    claim_terms = meaningful_terms(claim["text"])
    claim_numbers = set(claim["numbers"])
    claim_dates = set(claim["dates"])

    best_strength: int | None = None
    best: dict[str, Any] | None = None

    for chunk_index, chunk in enumerate(source_chunks):
        chunk_terms = meaningful_terms(chunk)
        overlap = 0.0
        if claim_terms:
            overlap = len(claim_terms & chunk_terms) / len(claim_terms)

        chunk_numbers = set(extract_numbers(chunk))
        chunk_dates = set(extract_dates(chunk))

        numeric_conflict = (
            bool(claim_numbers)
            and bool(chunk_numbers)
            and not claim_numbers.issubset(chunk_numbers)
        )
        date_conflict = (
            bool(claim_dates)
            and bool(chunk_dates)
            and not claim_dates.issubset(chunk_dates)
        )
        conflict = numeric_conflict or date_conflict

        if overlap >= _STRONG_OVERLAP:
            strength = _STRENGTH_CONFLICT if conflict else _STRENGTH_SUPPORTED
        elif overlap >= _WEAK_OVERLAP:
            strength = _STRENGTH_CONFLICT if conflict else _STRENGTH_WEAK
        else:
            continue

        if best is None or strength > best_strength:
            best_strength = strength
            best = {
                "verdict": "supported" if strength == _STRENGTH_SUPPORTED else "weakly_supported" if strength == _STRENGTH_WEAK else "unsupported",
                "reason_type": "supported" if strength == _STRENGTH_SUPPORTED else "weak_evidence" if strength == _STRENGTH_WEAK else "numeric_mismatch" if numeric_conflict else "date_mismatch" if date_conflict else "evidence_conflict",
                "overlap": round(overlap, 4),
                "chunk_index": chunk_index,
                "evidence": _excerpt(chunk),
                "matched_terms": sorted(claim_terms & chunk_terms),
            }

    if best is None:
        return {
            "claim_id": claim["id"],
            "claim_text": _claim_excerpt(claim["text"]),
            "verdict": "unsupported",
            "reason_type": "no_evidence",
            "reason": "No relevant source evidence was found for this claim.",
            "overlap": 0.0,
            "chunk_index": None,
            "evidence": None,
            "matched_terms": [],
        }

    verdict = best["verdict"]
    reason_type = best["reason_type"]
    if verdict == "supported":
        reason = (
            "Supported by source evidence "
            f"(overlap {int(best['overlap'] * 100)}%)."
        )
    elif verdict == "weakly_supported":
        reason = (
            "Only weak source evidence was found "
            f"(overlap {int(best['overlap'] * 100)}%)."
        )
    elif reason_type == "numeric_mismatch":
        reason = (
            "Numbers in the claim conflict with the source evidence "
            f"({', '.join(_format_number(v) for v in sorted(claim_numbers))})."
        )
    elif reason_type == "date_mismatch":
        reason = (
            "Dates in the claim conflict with the source evidence "
            f"({', '.join(sorted(claim_dates))})."
        )
    else:  # evidence_conflict
        reason = "The claim conflicts with the closest source evidence."

    return {
        "claim_id": claim["id"],
        "claim_text": _claim_excerpt(claim["text"]),
        "verdict": verdict,
        "reason_type": reason_type,
        "reason": reason,
        "overlap": best["overlap"],
        "chunk_index": best["chunk_index"],
        "evidence": best["evidence"],
        "matched_terms": best["matched_terms"],
    }


def evaluate_claims(
    claims: list[dict[str, Any]],
    source_chunks: list[str],
) -> list[dict[str, Any]]:
    """Evaluate every claim against the source chunks."""
    return [analyze_claim(claim, source_chunks) for claim in claims]