"""Phase 12B — Deterministic cross-output consistency checking.

Compares factual values across completed outputs from the same transformation
job to detect numeric, percentage, and date conflicts.  This is a purely
offline, deterministic comparison that never invokes an LLM or performs
semantic contradiction detection.

Single completed output → NOT_APPLICABLE.
Incomplete outputs are excluded from comparison.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.transformation.verification_engine.text_utils import (
    extract_dates,
    extract_numbers,
    extract_percentages,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
STATUS_CONSISTENT = "CONSISTENT"
STATUS_INCONSISTENT = "INCONSISTENT"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

CATEGORY_NUMERIC = "numeric"
CATEGORY_PERCENTAGE = "percentage"
CATEGORY_DATE = "date"

# Maximum conflicts returned (bounded response).
MAX_CONFLICTS = 50

# Numbers below this absolute value are ignored (too common / low-signal).
_MIN_ABSOLUTE_NUMBER = 3.0

# Two numbers are "comparable" when they share the same order-of-magnitude
# bucket (base-10).  Values 100-999 are in one bucket, 1000-9999 in another.
def _order_of_magnitude(value: float) -> int:
    """Return the base-10 order-of-magnitude bucket for a value."""
    if value == 0:
        return 0
    return int(math.log10(abs(value)))


# We need math for log10.
import math

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValueFact:
    """A single extracted factual value from one output."""

    value: str  # canonical string form
    category: str  # "numeric" | "percentage" | "date"
    raw_value: float | None  # numeric float if applicable
    context: str  # capped excerpt of surrounding text (max 120 chars)


@dataclass(frozen=True)
class ConflictRecord:
    """A detected conflict between two outputs."""

    category: str
    value_a: str
    value_b: str
    output_a_id: str
    output_a_type: str
    output_b_id: str
    output_b_type: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "value_a": self.value_a,
            "value_b": self.value_b,
            "output_a_id": self.output_a_id,
            "output_a_type": self.output_a_type,
            "output_b_id": self.output_b_id,
            "output_b_type": self.output_b_type,
            "message": self.message,
        }


@dataclass(frozen=True)
class CrossOutputResult:
    """Assembled cross-output consistency result."""

    status: str  # CONSISTENT | INCONSISTENT | NOT_APPLICABLE
    completed_output_count: int
    conflicts: list[ConflictRecord]
    checked_pairs: int
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "completed_output_count": self.completed_output_count,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "checked_pairs": self.checked_pairs,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Value extraction (per output)
# ---------------------------------------------------------------------------

def _excerpt(text: str, limit: int = 120) -> str:
    """Cap text for context display."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_number(value: float) -> str:
    """Render a float compactly (500 not 500.0)."""
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def extract_output_values(text: str) -> list[ValueFact]:
    """Extract deterministic factual values from output text.

    Returns a bounded list of ValueFact objects covering numeric values,
    percentages, and dates found in the text.
    """
    if not text:
        return []

    facts: list[ValueFact] = []

    # Extract percentages first (before raw numbers, since percentages
    # contain numbers we don't want to double-count).
    pct_values = extract_percentages(text)
    seen_pct: set[float] = set()
    for val in pct_values:
        if val in seen_pct:
            continue
        seen_pct.add(val)
        if val < 0 or val > 1000:
            continue
        facts.append(
            ValueFact(
                value=f"{_format_number(val)}%",
                category=CATEGORY_PERCENTAGE,
                raw_value=val,
                context=_excerpt(text),
            )
        )

    # Extract raw numbers (excluding those already captured as percentages).
    num_values = extract_numbers(text)
    seen_num: set[float] = set()
    for val in num_values:
        if val in seen_num:
            continue
        seen_num.add(val)
        if abs(val) < _MIN_ABSOLUTE_NUMBER:
            continue
        # Skip if this number was already captured as a percentage.
        if val in pct_values:
            continue
        facts.append(
            ValueFact(
                value=_format_number(val),
                category=CATEGORY_NUMERIC,
                raw_value=val,
                context=_excerpt(text),
            )
        )

    # Extract dates.
    date_values = extract_dates(text)
    seen_dates: set[str] = set()
    for date_str in date_values:
        if date_str in seen_dates:
            continue
        seen_dates.add(date_str)
        facts.append(
            ValueFact(
                value=date_str,
                category=CATEGORY_DATE,
                raw_value=None,
                context=_excerpt(text),
            )
        )

    # Bound total facts per output.
    return facts[:100]


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def _are_comparable_numbers(a: float, b: float) -> bool:
    """Determine if two numbers could refer to the same concept.

    Uses order-of-magnitude bucketing: two numbers are comparable if they
    share the same order-of-magnitude bucket (base-10).
    """
    if a == b:
        return False
    bucket_a = _order_of_magnitude(a)
    bucket_b = _order_of_magnitude(b)
    return bucket_a == bucket_b


def _detect_numeric_conflicts(
    values_a: list[ValueFact],
    values_b: list[ValueFact],
    id_a: str,
    type_a: str,
    id_b: str,
    type_b: str,
) -> list[ConflictRecord]:
    """Detect numeric conflicts between two outputs."""
    conflicts: list[ConflictRecord] = []
    nums_a = [v for v in values_a if v.category == CATEGORY_NUMERIC and v.raw_value is not None]
    nums_b = [v for v in values_b if v.category == CATEGORY_NUMERIC and v.raw_value is not None]

    for fa in nums_a:
        for fb in nums_b:
            if _are_comparable_numbers(fa.raw_value, fb.raw_value):
                conflicts.append(
                    ConflictRecord(
                        category=CATEGORY_NUMERIC,
                        value_a=fa.value,
                        value_b=fb.value,
                        output_a_id=id_a,
                        output_a_type=type_a,
                        output_b_id=id_b,
                        output_b_type=type_b,
                        message=(
                            f"Conflicting numeric values: {fa.value} "
                            f"({type_a}) vs {fb.value} ({type_b})."
                        ),
                    )
                )
    return conflicts


def _detect_percentage_conflicts(
    values_a: list[ValueFact],
    values_b: list[ValueFact],
    id_a: str,
    type_a: str,
    id_b: str,
    type_b: str,
) -> list[ConflictRecord]:
    """Detect percentage conflicts between two outputs."""
    conflicts: list[ConflictRecord] = []
    pcts_a = [v for v in values_a if v.category == CATEGORY_PERCENTAGE]
    pcts_b = [v for v in values_b if v.category == CATEGORY_PERCENTAGE]

    for fa in pcts_a:
        for fb in pcts_b:
            if fa.raw_value is not None and fb.raw_value is not None:
                if fa.raw_value != fb.raw_value:
                    conflicts.append(
                        ConflictRecord(
                            category=CATEGORY_PERCENTAGE,
                            value_a=fa.value,
                            value_b=fb.value,
                            output_a_id=id_a,
                            output_a_type=type_a,
                            output_b_id=id_b,
                            output_b_type=type_b,
                            message=(
                                f"Conflicting percentages: {fa.value} "
                                f"({type_a}) vs {fb.value} ({type_b})."
                            ),
                        )
                    )
    return conflicts


def _detect_date_conflicts(
    values_a: list[ValueFact],
    values_b: list[ValueFact],
    id_a: str,
    type_a: str,
    id_b: str,
    type_b: str,
) -> list[ConflictRecord]:
    """Detect date conflicts between two outputs.

    Only flags conflicts between full dates (not bare years), since
    different outputs may legitimately reference different years when
    discussing different time periods.
    """
    conflicts: list[ConflictRecord] = []
    dates_a = [v for v in values_a if v.category == CATEGORY_DATE]
    dates_b = [v for v in values_b if v.category == CATEGORY_DATE]

    for da in dates_a:
        for db in dates_b:
            if da.value == db.value:
                continue
            # Only compare full dates (containing month info), not bare years.
            da_is_full = not da.value.isdigit()
            db_is_full = not db.value.isdigit()
            if da_is_full and db_is_full:
                conflicts.append(
                    ConflictRecord(
                        category=CATEGORY_DATE,
                        value_a=da.value,
                        value_b=db.value,
                        output_a_id=id_a,
                        output_a_type=type_a,
                        output_b_id=id_b,
                        output_b_type=type_b,
                        message=(
                            f"Conflicting dates: {da.value} "
                            f"({type_a}) vs {db.value} ({type_b})."
                        ),
                    )
                )
    return conflicts


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def check_cross_output_consistency(
    outputs: list[dict[str, Any]],
) -> CrossOutputResult:
    """Deterministically check consistency across outputs from the same job.

    Parameters
    ----------
    outputs : list of dict
        Serialized Output records (must include id, output_type, status,
        text_content).

    Returns
    -------
    CrossOutputResult
        Frozen dataclass with status, conflicts, and metadata.
    """
    # Filter to completed outputs only.
    completed = [
        o for o in outputs
        if isinstance(o, dict) and o.get("status") == "completed"
    ]

    if len(completed) < 2:
        return CrossOutputResult(
            status=STATUS_NOT_APPLICABLE,
            completed_output_count=len(completed),
            conflicts=[],
            checked_pairs=0,
            note=(
                "Cross-output consistency requires at least two completed outputs."
                if len(completed) < 2
                else ""
            ),
        )

    # Extract values from each completed output.
    output_values: dict[str, list[ValueFact]] = {}
    for out in completed:
        oid = str(out.get("id", ""))
        text = out.get("text_content") or ""
        structured = out.get("structured_content")
        # Also extract from structured content string representation
        # for outputs that store values in structured fields.
        if isinstance(structured, dict):
            # Flatten structured content to a text representation for value extraction.
            struct_text = _flatten_structured(structured)
            text = f"{text} {struct_text}".strip()
        output_values[oid] = extract_output_values(text)

    # Compare each pair of outputs.
    all_conflicts: list[ConflictRecord] = []
    checked_pairs = 0

    for i, out_a in enumerate(completed):
        id_a = str(out_a.get("id", ""))
        type_a = out_a.get("output_type", "unknown")
        vals_a = output_values.get(id_a, [])

        for out_b in completed[i + 1:]:
            id_b = str(out_b.get("id", ""))
            type_b = out_b.get("output_type", "unknown")
            vals_b = output_values.get(id_b, [])

            checked_pairs += 1

            all_conflicts.extend(
                _detect_numeric_conflicts(vals_a, vals_b, id_a, type_a, id_b, type_b)
            )
            all_conflicts.extend(
                _detect_percentage_conflicts(vals_a, vals_b, id_a, type_a, id_b, type_b)
            )
            all_conflicts.extend(
                _detect_date_conflicts(vals_a, vals_b, id_a, type_a, id_b, type_b)
            )

    # Bound and deduplicate conflicts.
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[ConflictRecord] = []
    for c in all_conflicts:
        key = (c.category, c.value_a, c.value_b, c.output_a_id)
        key_rev = (c.category, c.value_b, c.value_a, c.output_b_id)
        if key not in seen and key_rev not in seen:
            seen.add(key)
            unique.append(c)
        if len(unique) >= MAX_CONFLICTS:
            break

    status = STATUS_CONSISTENT if not unique else STATUS_INCONSISTENT
    note = (
        "Deterministic check: only explicit numeric, percentage, and date "
        "conflicts are reported; semantic contradictions are conservatively "
        "not detected."
    )

    return CrossOutputResult(
        status=status,
        completed_output_count=len(completed),
        conflicts=unique,
        checked_pairs=checked_pairs,
        note=note,
    )


def _flatten_structured(content: dict[str, Any], max_depth: int = 3) -> str:
    """Recursively extract string values from structured content."""
    if max_depth <= 0:
        return ""
    parts: list[str] = []
    for value in content.values():
        if isinstance(value, str) and value.strip():
            parts.append(value)
        elif isinstance(value, dict):
            parts.append(_flatten_structured(value, max_depth - 1))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(_flatten_structured(item, max_depth - 1))
    return " ".join(parts)
