"""Internal consistency analysis for the Phase 8 verification engine.

A conservative, deterministic check that only flags an output as inconsistent
when two claims share a meaningful context and carry conflicting numeric or
date values.  The engine deliberately avoids fabricating certainty: when the
system cannot prove a contradiction it reports ``passed`` and documents that
semantic contradiction detection is conservative.
"""

from __future__ import annotations

from typing import Any

from app.transformation.verification_engine.evidence import _claim_excerpt
from app.transformation.verification_engine.text_utils import meaningful_terms

# Two claims only compete for consistency when they share this many
# content-bearing terms (i.e. they refer to the same subject).
_MIN_COMMON_TERMS = 2


def _format_numbers(values: set[float]) -> str:
    """Render numbers compactly (``500`` not ``500.0``)."""
    rendered: list[str] = []
    for value in sorted(values):
        if float(value).is_integer():
            rendered.append(str(int(value)))
        else:
            rendered.append(str(value))
    return ", ".join(rendered)


def check_consistency(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze whether claims within one output contradict each other.

    Returns a consistency record with a status, score, and the list of detected
    conflicts (each type: ``conflicting_numbers`` | ``conflicting_dates``).
    """
    conflicts: list[dict[str, Any]] = []
    checked_pairs = 0

    for index, left in enumerate(claims):
        left_terms = meaningful_terms(left["text"])
        left_numbers = set(left["numbers"])
        left_dates = set(left["dates"])
        for right in claims[index + 1:]:
            right_terms = meaningful_terms(right["text"])
            common = left_terms & right_terms
            if len(common) < _MIN_COMMON_TERMS:
                continue
            checked_pairs += 1

            right_numbers = set(right["numbers"])
            right_dates = set(right["dates"])

            if (
                left_numbers
                and right_numbers
                and not (left_numbers & right_numbers)
            ):
                conflicts.append(
                    {
                        "type": "conflicting_numbers",
                        "message": (
                            f"Contradictory numbers: '{_claim_excerpt(left['text'])}' "
                            f"({_format_numbers(left_numbers)}) conflicts with "
                            f"'{_claim_excerpt(right['text'])}' "
                            f"({_format_numbers(right_numbers)})."
                        ),
                        "left_claim_id": left["id"],
                        "right_claim_id": right["id"],
                    }
                )
            if (
                left_dates
                and right_dates
                and not (left_dates & right_dates)
            ):
                conflicts.append(
                    {
                        "type": "conflicting_dates",
                        "message": (
                            f"Contradictory dates: '{_claim_excerpt(left['text'])}' "
                            f"({', '.join(sorted(left_dates))}) conflicts with "
                            f"'{_claim_excerpt(right['text'])}' "
                            f"({', '.join(sorted(right_dates))})."
                        ),
                        "left_claim_id": left["id"],
                        "right_claim_id": right["id"],
                    }
                )

    if conflicts:
        score = round(1.0 / (1 + len(conflicts)), 4)
        status = "warning"
    else:
        score = 1.0
        status = "passed"

    note = (
        "Deterministic check: only explicit numeric/date contradictions are "
        "flagged; semantic antonym contradictions are conservatively not "
        "reported as inconsistency."
    )

    return {
        "status": status,
        "score": score,
        "conflicts": conflicts,
        "checked_pairs": checked_pairs,
        "note": note,
    }