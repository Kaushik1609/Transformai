"""
TransformIQ / KaryaSetu AI — Information Classification (Phase 2A)

Defines application-level information classification labels and utilities.

IMPORTANT:
These are internal KaryaSetu policy labels used strictly for deterministic
processing control. They must NOT be described as official Government of India,
NCIIPC, NTRO, or regulatory classifications.
"""
from __future__ import annotations

from enum import Enum
from typing import Any


class InformationClassification(str, Enum):
    """KaryaSetu application-level policy classification labels."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"

    def __str__(self) -> str:
        return self.value


class InvalidClassificationError(ValueError):
    """Raised when an unrecognised classification label is supplied."""


# Canonical set of valid uppercase string representations.
VALID_CLASSIFICATIONS = frozenset(c.value for c in InformationClassification)

# Safe default enterprise classification when material has no explicit label.
DEFAULT_CLASSIFICATION = InformationClassification.INTERNAL


def normalize_classification(
    value: str | InformationClassification | None,
) -> InformationClassification:
    """Validate and normalize a classification label string.

    Fails closed:
    - None or empty string safely resolves to DEFAULT_CLASSIFICATION (INTERNAL).
    - Valid labels are accepted case-insensitively with leading/trailing whitespace stripped.
    - Any unknown string raises InvalidClassificationError (fail-closed).
    """
    if value is None:
        return DEFAULT_CLASSIFICATION

    if isinstance(value, InformationClassification):
        return value

    if isinstance(value, Enum):
        raw = str(value.value).strip().upper()
    else:
        raw = str(value).strip().upper()

    if not raw:
        return DEFAULT_CLASSIFICATION

    if raw in VALID_CLASSIFICATIONS:
        return InformationClassification(raw)

    raise InvalidClassificationError(
        f"Invalid classification label: {value!r}. "
        f"Allowed values are: {', '.join(sorted(VALID_CLASSIFICATIONS))}."
    )


def resolve_source_classification(
    source_metadata: dict[str, Any] | None,
    fallback: str | None = None,
) -> InformationClassification:
    """Extract and normalize classification from source metadata dictionary.

    Safely falls back to DEFAULT_CLASSIFICATION if unlabelled or missing.
    """
    if source_metadata and isinstance(source_metadata, dict):
        raw = source_metadata.get("classification")
        if raw is not None:
            return normalize_classification(str(raw))

    if fallback is not None:
        return normalize_classification(fallback)

    return DEFAULT_CLASSIFICATION
