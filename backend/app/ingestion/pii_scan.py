"""Content-level PII scan for ingested sources (Phase 12C).

The Phase 11K PII engine (``app.core.pii.detect_pii``) was previously used
only for log/surface hygiene and was never wired into the document content
pipeline, so PII embedded in sources flowed unredacted through
ingestion -> RAG -> LLM -> outputs.

This module adds a narrow, deterministic, offline content-level scan of the
normalized source text.  It records per-category PII counts and a
``detected`` flag that are stored in the source metadata (``source_metadata``
JSONB) and surfaced as a ``pii_detected`` security event.

Security contract (preserved and unchanged):

  * The scan is best-effort and NEVER rewrites the stored source.  The
    original file and extracted text are left untouched, exactly as the
    Phase 11K PII module requires ("storage keeps the original file
    untouched").
  * Only non-secret category counts are stored/emitted.  Raw PII values are
    never persisted here and never attached to audit events.
  * Missing/unreadable text yields a clean \"no findings\" summary so the
    ingestion path is never blocked by the scan.
"""
from __future__ import annotations

from typing import Any

from app.core.pii import detect_pii

# Stable metadata / event keys.
META_KEY = "pii_scan"
EVENT_TYPE = "pii_detected"
_DETECTED_KEY = "detected"
_COUNTS_KEY = "counts"

# Deterministic category ordering for stable counts dicts.
_CATEGORY_ORDER = ("email", "phone", "ipv4", "credit_card")


def scan_source_pii(text: str | None) -> dict[str, Any]:
    """Return a bounded PII-scan summary for normalized source text.

    Returns a dict of the form ``{"detected": bool, "counts": {category: n}}``
    with only the categories present (deterministic order).  Never contains
    raw PII values.  Empty/None text yields ``detected=False``.
    """
    counts: dict[str, int] = {}
    if text:
        findings = detect_pii(text)
        for finding in findings:
            key = finding.category
            counts[key] = counts.get(key, 0) + 1

    ordered = {k: counts[k] for k in _CATEGORY_ORDER if counts.get(k)}
    return {_DETECTED_KEY: bool(ordered), _COUNTS_KEY: ordered}
