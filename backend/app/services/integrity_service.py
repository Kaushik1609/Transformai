"""
TransformIQ / KaryaSetu AI — Integrity Service (Phase 2G)

Handles:
1. Post-generation cryptographic integrity sealing (seal_output_integrity).
2. Authoritative verification of output artifact integrity (verify_output_integrity).
3. Emission of security audit events:
   - integrity_recorded
   - integrity_verified
   - integrity_failed
4. Pure read-only verification: does not overwrite existing records upon verification.
5. Strict IDOR and ownership protection when invoked through transformation endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.audit import emit_security_event
from app.policy.integrity import (
    CryptographicIntegrityRecord,
    IntegrityStatus,
    build_approval_snapshot,
    build_provenance_projection,
    compute_artifact_hash,
    compute_provenance_hash,
)


def seal_output_integrity(
    output: Any,
    *,
    db: Any = None,
    storage: Any | None = None,
    recorded_at: str | None = None,
    project_id: str | None = None,
) -> CryptographicIntegrityRecord | None:
    """Compute and persist authoritative cryptographic integrity record for an Output.

    Authoritative sequence:
    1. Output generated and completed.
    2. Primary artifact read back from storage (or structured/text representation).
    3. Primary artifact_hash and companion_hashes computed.
    4. Provenance metadata resolved from output_metadata['provenance'].
    5. Approval snapshot resolved from output_metadata['approval'].
    6. Canonical provenance projection constructed.
    7. provenance_hash computed.
    8. cryptographic_integrity record persisted under output_metadata['cryptographic_integrity'].
    9. Audit event 'integrity_recorded' emitted.

    Returns CryptographicIntegrityRecord, or None if output cannot be sealed.
    """
    # 1. Compute artifact hash
    artifact_hash, companion_hashes = compute_artifact_hash(output, storage=storage)
    if not artifact_hash:
        return None

    out_meta = dict(output.output_metadata or {})
    provenance_data = out_meta.get("provenance")

    if not isinstance(provenance_data, dict) or not provenance_data.get("provenance_id"):
        return None

    # 2. Extract approval snapshot
    approval_snapshot = build_approval_snapshot(output)

    # 3. Construct canonical provenance projection and hash
    projection = build_provenance_projection(
        provenance_data,
        approval_snapshot=approval_snapshot,
        artifact_hash=artifact_hash,
        companion_hashes=companion_hashes,
    )
    provenance_hash = compute_provenance_hash(projection)

    # 4. Resolve approval ID
    approval_id = (
        approval_snapshot.get("latest_approval_id")
        or provenance_data.get("extensions", {}).get("approval_id")
    )

    # 5. Build persistent record
    rec_time = recorded_at or datetime.now(timezone.utc).isoformat()
    record = CryptographicIntegrityRecord(
        algorithm="sha256",
        artifact_hash=artifact_hash,
        companion_hashes=companion_hashes,
        provenance_id=str(provenance_data["provenance_id"]),
        provenance_hash=provenance_hash,
        approval_id=approval_id,
        recorded_at=rec_time,
        status=IntegrityStatus.VERIFIED.value,
    )

    # 6. Persist to output_metadata
    out_meta["cryptographic_integrity"] = record.model_dump(mode="json")
    output.output_metadata = out_meta

    if db is not None:
        try:
            db.add(output)
        except Exception:
            pass

    # 7. Emit security audit event
    p_id = project_id
    if not p_id and hasattr(output, "job") and output.job and hasattr(output.job, "project_id"):
        p_id = str(output.job.project_id)

    emit_security_event(
        "integrity_recorded",
        outcome="allowed",
        project_id=p_id,
        job_id=str(output.job_id) if hasattr(output, "job_id") else None,
        reason="output_cryptographic_integrity_sealed",
        details={
            "output_id": str(output.id),
            "output_type": getattr(output, "output_type", None),
            "artifact_hash": artifact_hash,
            "provenance_id": record.provenance_id,
            "provenance_hash": provenance_hash,
            "status": IntegrityStatus.VERIFIED.value,
        },
    )

    return record


def record_job_cryptographic_integrity(
    db: Any,
    job_id: uuid.UUID,
    *,
    storage: Any | None = None,
    project_id: str | None = None,
) -> list[CryptographicIntegrityRecord]:
    """Record cryptographic integrity for all completed outputs of a job.

    Called during post-generation finalization in run_transformation_job.
    Fail-open: failures never corrupt the job execution or abort completed outputs.
    """
    from sqlalchemy import select
    from app.db.models.output import Output

    sealed_records: list[CryptographicIntegrityRecord] = []
    try:
        outputs = db.execute(
            select(Output).where(
                Output.job_id == job_id,
                Output.status == "completed",
            )
        ).scalars().all()
    except Exception:
        return sealed_records

    for output in outputs:
        try:
            record = seal_output_integrity(
                output,
                db=db,
                storage=storage,
                project_id=project_id,
            )
            if record is not None:
                sealed_records.append(record)
        except Exception:
            pass

    return sealed_records


def verify_output_integrity(
    output: Any,
    *,
    storage: Any | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Verify stored cryptographic integrity against current authoritative artifacts and provenance.

    Verification sequence:
    1. Read stored cryptographic integrity record. If missing -> UNAVAILABLE.
    2. Re-read authoritative artifact bytes/content. If missing/unreadable -> UNAVAILABLE.
    3. Recompute current artifact hash and companion hashes.
    4. Reconstruct canonical approval snapshot and provenance projection.
    5. Recompute current provenance hash.
    6. Compare stored vs current digests.
    7. Return VERIFIED if all match, INVALID if any mismatch.
    8. Emit integrity_verified or integrity_failed audit event.
    9. Does NOT overwrite or mutate stored record.
    """
    out_meta = output.output_metadata if isinstance(output.output_metadata, dict) else {}
    stored_data = out_meta.get("cryptographic_integrity")

    # 1. Missing integrity record -> UNAVAILABLE
    if not isinstance(stored_data, dict):
        return {
            "status": IntegrityStatus.UNAVAILABLE.value,
            "algorithm": "sha256",
            "artifact_hash": None,
            "companion_hashes": {},
            "provenance_id": None,
            "provenance_hash": None,
            "approval_id": None,
            "recorded_at": None,
            "details": {
                "reason": "Cryptographic integrity record not found (legacy or unsealed output).",
                "artifact_verified": False,
                "provenance_verified": False,
                "companion_verified": False,
            },
        }

    # 2. Re-read authoritative artifact content
    curr_art_hash, curr_comp_hashes = compute_artifact_hash(output, storage=storage)
    if curr_art_hash is None:
        return {
            "status": IntegrityStatus.UNAVAILABLE.value,
            "algorithm": stored_data.get("algorithm", "sha256"),
            "artifact_hash": stored_data.get("artifact_hash"),
            "companion_hashes": stored_data.get("companion_hashes", {}),
            "provenance_id": stored_data.get("provenance_id"),
            "provenance_hash": stored_data.get("provenance_hash"),
            "approval_id": stored_data.get("approval_id"),
            "recorded_at": stored_data.get("recorded_at"),
            "details": {
                "reason": "Authoritative artifact content or storage bytes cannot be retrieved.",
                "artifact_verified": False,
                "provenance_verified": False,
                "companion_verified": False,
            },
        }

    # 3. Reconstruct approval snapshot and provenance projection
    curr_approval_snapshot = build_approval_snapshot(output)
    prov_data = out_meta.get("provenance") or {}
    curr_projection = build_provenance_projection(
        prov_data,
        approval_snapshot=curr_approval_snapshot,
        artifact_hash=curr_art_hash,
        companion_hashes=curr_comp_hashes,
    )
    curr_prov_hash = compute_provenance_hash(curr_projection)

    # 4. Compare digests
    stored_art_hash = stored_data.get("artifact_hash")
    stored_prov_hash = stored_data.get("provenance_hash")
    stored_comp_hashes = stored_data.get("companion_hashes", {})

    art_match = (stored_art_hash == curr_art_hash)
    prov_match = (stored_prov_hash == curr_prov_hash)
    comp_match = (stored_comp_hashes == curr_comp_hashes)

    all_verified = art_match and prov_match and comp_match
    status = IntegrityStatus.VERIFIED.value if all_verified else IntegrityStatus.INVALID.value

    # 5. Emit audit event
    p_id = project_id
    if not p_id and hasattr(output, "job") and output.job and hasattr(output.job, "project_id"):
        p_id = str(output.job.project_id)

    event_type = "integrity_verified" if all_verified else "integrity_failed"
    outcome = "allowed" if all_verified else "denied"
    reason = "integrity_verification_passed" if all_verified else "cryptographic_tamper_detected"

    emit_security_event(
        event_type,
        outcome=outcome,
        project_id=p_id,
        job_id=str(output.job_id) if hasattr(output, "job_id") else None,
        reason=reason,
        details={
            "output_id": str(output.id),
            "status": status,
            "artifact_verified": art_match,
            "provenance_verified": prov_match,
            "companion_verified": comp_match,
        },
    )

    return {
        "status": status,
        "algorithm": stored_data.get("algorithm", "sha256"),
        "artifact_hash": curr_art_hash,
        "companion_hashes": curr_comp_hashes,
        "provenance_id": stored_data.get("provenance_id"),
        "provenance_hash": curr_prov_hash,
        "approval_id": stored_data.get("approval_id"),
        "recorded_at": stored_data.get("recorded_at"),
        "details": {
            "artifact_verified": art_match,
            "provenance_verified": prov_match,
            "companion_verified": comp_match,
            "stored_artifact_hash": stored_art_hash,
            "stored_provenance_hash": stored_prov_hash,
            "current_artifact_hash": curr_art_hash,
            "current_provenance_hash": curr_prov_hash,
            "reason": reason,
        },
    }
