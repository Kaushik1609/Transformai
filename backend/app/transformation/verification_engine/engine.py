"""Phase 8 verification engine — orchestration and result assembly.

Pipeline (mirrors the Phase 8 objective):

    generated output -> claim extraction -> evidence matching
      -> grounding analysis -> consistency analysis
      -> warning generation -> verification result

The primary implementation is fully deterministic and offline: no API key, no
provider, no network.  The existing ``LLMProvider`` abstraction remains the
optional enhancement point for a future semantic reviewer without changing
Phase 8's default behavior.
"""

from __future__ import annotations

from typing import Any

from app.transformation.verification_engine.claims import extract_claims
from app.transformation.verification_engine.consistency import check_consistency
from app.transformation.verification_engine.evidence import analyze_claim

# Status values persisted to VerificationResult.overall_status.
STATUS_PASSED = "passed"
STATUS_WARNING = "warning"

# Internal result status (details.status) marking a completed real engine run.
RESULT_COMPLETED = "completed"


def _clean_chunks(source_chunks: Any) -> list[str]:
    """Coerce and filter source evidence to a list of non-empty strings."""
    if not source_chunks:
        return []
    chunks: list[str] = []
    for chunk in source_chunks:
        if isinstance(chunk, str) and chunk.strip():
            chunks.append(chunk.strip())
    return chunks


def _build_warning(
    *,
    warning_type: str,
    severity: str,
    message: str,
    claim_text: str | None = None,
    evidence: str | None = None,
    chunk_index: int | None = None,
) -> dict[str, Any]:
    """Build a single structured warning item."""
    return {
        "type": warning_type,
        "severity": severity,
        "message": message,
        "claim_text": claim_text,
        "evidence": evidence,
        "chunk_index": chunk_index,
    }


def _assemble_warnings(
    *,
    evidence_records: list[dict[str, Any]],
    consistency: dict[str, Any],
    overall_status: str,
    message: str,
) -> dict[str, Any]:
    """Assemble the persisted warnings mapping (dict as the JSONB requires)."""
    items: list[dict[str, Any]] = []

    for record in evidence_records:
        if record["verdict"] == "supported":
            continue
        if record["verdict"] == "weakly_supported":
            items.append(
                _build_warning(
                    warning_type="weakly_supported_claim",
                    severity="warning",
                    message=record["reason"],
                    claim_text=record["claim_text"],
                    evidence=record["evidence"],
                    chunk_index=record["chunk_index"],
                )
            )
            continue
        if record["reason_type"] == "numeric_mismatch":
            items.append(
                _build_warning(
                    warning_type="numeric_mismatch",
                    severity="error",
                    message=record["reason"],
                    claim_text=record["claim_text"],
                    evidence=record["evidence"],
                    chunk_index=record["chunk_index"],
                )
            )
            continue
        if record["reason_type"] == "date_mismatch":
            items.append(
                _build_warning(
                    warning_type="date_mismatch",
                    severity="error",
                    message=record["reason"],
                    claim_text=record["claim_text"],
                    evidence=record["evidence"],
                    chunk_index=record["chunk_index"],
                )
            )
            continue
        items.append(
            _build_warning(
                warning_type="unsupported_claim",
                severity="warning",
                message=record["reason"],
                claim_text=record["claim_text"],
                evidence=record["evidence"],
                chunk_index=record["chunk_index"],
            )
        )

    for conflict in consistency["conflicts"]:
        if conflict["type"] == "conflicting_numbers":
            warning_type = "conflicting_numbers"
        else:
            warning_type = "conflicting_dates"
        items.append(
            _build_warning(
                warning_type=warning_type,
                severity="warning",
                message=conflict["message"],
            )
        )

    return {
        "status": overall_status,
        "message": message,
        "items": items,
        "count": len(items),
    }


def _build_message(
    *,
    claims_checked: int,
    claims_supported: int,
    consistency: dict[str, Any],
) -> str:
    """Build a concise human-readable summary of the verification outcome."""
    if claims_checked == 0:
        return "No checkable assertions were found in the generated output."

    parts: list[str] = []
    if claims_supported == claims_checked:
        parts.append(
            f"All {claims_checked} assertion(s) are grounded in the source evidence."
        )
    else:
        unmet = claims_checked - claims_supported
        parts.append(
            f"{claims_supported} of {claims_checked} assertion(s) are grounded; "
            f"{unmet} are weak or unsupported by the source."
        )
    if consistency["conflicts"]:
        parts.append(
            f"{len(consistency['conflicts'])} internal contradiction(s) detected."
        )
    return " ".join(parts)


def run_verification(
    *,
    output: dict[str, Any],
    canonical: dict[str, Any] | None = None,
    source_chunks: list[str] | None = None,
) -> dict[str, Any]:
    """Run the full Phase 8 verification pipeline for one generated output.

    Args:
        output: The generated output's structured content.
        canonical: The source canonical content (used for entity signals).
        source_chunks: The normalized source chunks used as evidence.

    Returns:
        A JSON-serializable verification result dict safe for persistence in
        the existing ``VerificationResult`` model.
    """
    chunks = _clean_chunks(source_chunks)
    claims = extract_claims(output, canonical)
    evidence_records = [analyze_claim(claim, chunks) for claim in claims]

    claims_checked = len(claims)
    claims_supported = sum(
        1 for record in evidence_records if record["verdict"] == "supported"
    )
    grounding_score = (
        round(claims_supported / claims_checked, 4)
        if claims_checked
        else None
    )

    consistency = check_consistency(claims)
    consistency_score = consistency["score"] if claims_checked else None

    has_grounding_warning = claims_checked > 0 and claims_supported < claims_checked
    has_consistency_warning = bool(consistency["conflicts"])
    if claims_checked == 0:
        overall_status = STATUS_PASSED
    elif has_grounding_warning or has_consistency_warning:
        overall_status = STATUS_WARNING
    else:
        overall_status = STATUS_PASSED

    message = _build_message(
        claims_checked=claims_checked,
        claims_supported=claims_supported,
        consistency=consistency,
    )
    warnings = _assemble_warnings(
        evidence_records=evidence_records,
        consistency=consistency,
        overall_status=overall_status,
        message=message,
    )

    return {
        "status": RESULT_COMPLETED,
        "overall_status": overall_status,
        "message": message,
        "grounding_score": grounding_score,
        "consistency_score": consistency_score,
        "claims_checked": claims_checked,
        "claims_supported": claims_supported,
        "warnings": warnings,
        "details": {
            "status": RESULT_COMPLETED,
            "generator": "deterministic-phase8-factcheck",
            "claims": claims,
            "evidence": evidence_records,
            "grounding": {
                "checked": claims_checked,
                "supported": claims_supported,
                "score": grounding_score,
            },
            "consistency": {
                "status": consistency["status"],
                "score": consistency_score,
                "conflicts": consistency["conflicts"],
                "checked_pairs": consistency["checked_pairs"],
                "note": consistency["note"],
            },
        },
    }