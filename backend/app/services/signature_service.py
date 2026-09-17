"""
TransformIQ / KaryaSetu AI — Digital Signature Service (Phase 2H)

Responsible for:
1. Authoritative post-generation digital signing of outputs (sign_output_artifact).
2. Batch signing of completed outputs in run_transformation_job (record_job_digital_signatures).
3. Read-only digital signature verification and tamper detection (verify_output_signature).
4. Emission of security audit events:
   - signature_recorded
   - signature_verified
   - signature_failed
5. Zero private key exposure; safe public verification metadata only.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.audit import emit_security_event
from app.policy.integrity import IntegrityStatus, sha256_bytes
from app.policy.signature import (
    DigitalSignatureRecord,
    DigitalSigner,
    SignatureStatus,
    build_signing_payload,
    compute_signing_payload_bytes,
    get_digital_signer,
)
from app.services.integrity_service import verify_output_integrity


def sign_output_artifact(
    output: Any,
    *,
    signer: DigitalSigner | None = None,
    db: Any = None,
    signed_at: str | None = None,
    project_id: str | None = None,
) -> DigitalSignatureRecord | None:
    """Compute and attach a digital signature to an output's authoritative metadata.

    Signing sequence:
    1. Verify output has a completed Phase 2G cryptographic_integrity record.
    2. Build canonical signing payload from the integrity envelope and governance facts.
    3. Calculate canonical payload bytes and SHA-256 payload hash.
    4. Sign payload bytes using the configured DigitalSigner.
    5. Persist DigitalSignatureRecord under output_metadata['digital_signature'].
    6. Emit 'signature_recorded' security audit event.

    Returns DigitalSignatureRecord, or None if the output cannot be signed.
    """
    out_meta = dict(output.output_metadata or {})
    integ = out_meta.get("cryptographic_integrity")

    # Requires existing Phase 2G integrity sealing
    if not isinstance(integ, dict) or not integ.get("artifact_hash") or not integ.get("provenance_hash"):
        return None

    active_signer = signer or get_digital_signer()

    # 1. Build canonical signing payload
    payload = build_signing_payload(output)
    payload_bytes = compute_signing_payload_bytes(payload)
    signed_payload_hash = sha256_bytes(payload_bytes)

    # 2. Generate signature
    sig_str = active_signer.sign(payload_bytes)
    sig_time = signed_at or datetime.now(timezone.utc).isoformat()

    # 3. Create persistent record
    record = DigitalSignatureRecord(
        algorithm=active_signer.algorithm,
        key_id=active_signer.key_id,
        signature=sig_str,
        signed_payload_hash=signed_payload_hash,
        signed_integrity_hash=str(payload.get("artifact_hash")),
        signed_provenance_hash=str(payload.get("provenance_hash")),
        status=SignatureStatus.VALID.value,
        signed_at=sig_time,
        provider=active_signer.provider_type.value,
    )

    # 4. Attach to output metadata
    out_meta["digital_signature"] = record.model_dump(mode="json")

    # If provenance extensions exists, also populate reserved extension slots
    prov = out_meta.get("provenance")
    if isinstance(prov, dict):
        exts = prov.get("extensions")
        if isinstance(exts, dict):
            exts["signature"] = sig_str
            exts["signature_algorithm"] = active_signer.algorithm

    output.output_metadata = out_meta

    if db is not None:
        try:
            db.add(output)
        except Exception:
            pass

    # 5. Emit security audit event
    p_id = project_id
    if not p_id and hasattr(output, "job") and output.job and hasattr(output.job, "project_id"):
        p_id = str(output.job.project_id)

    emit_security_event(
        "signature_recorded",
        outcome="allowed",
        project_id=p_id,
        job_id=str(output.job_id) if hasattr(output, "job_id") else None,
        reason="output_digital_signature_recorded",
        details={
            "output_id": str(output.id),
            "algorithm": record.algorithm,
            "key_id": record.key_id,
            "provider": record.provider,
            "signed_payload_hash": signed_payload_hash,
            "status": record.status,
        },
    )

    return record


def record_job_digital_signatures(
    db: Any,
    job_id: uuid.UUID,
    *,
    project_id: str | None = None,
    signer: DigitalSigner | None = None,
) -> list[DigitalSignatureRecord]:
    """Batch-sign completed outputs of a job in post-generation finalization.

    Called immediately after Phase 2G integrity sealing in run_transformation_job.
    Fail-open: failures never block or abort completed outputs.
    """
    from sqlalchemy import select
    from app.db.models.output import Output

    signed_records: list[DigitalSignatureRecord] = []
    try:
        outputs = db.execute(
            select(Output).where(
                Output.job_id == job_id,
                Output.status == "completed",
            )
        ).scalars().all()
    except Exception:
        return signed_records

    for output in outputs:
        try:
            record = sign_output_artifact(
                output,
                signer=signer,
                db=db,
                project_id=project_id,
            )
            if record is not None:
                signed_records.append(record)
        except Exception:
            pass

    return signed_records


def verify_output_signature(
    output: Any,
    *,
    signer: DigitalSigner | None = None,
    storage: Any | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Verify stored digital signature against authoritative artifact and integrity state.

    Read-only verification sequence:
    1. Load stored digital signature record. If missing -> UNAVAILABLE.
    2. Verify underlying Phase 2G cryptographic integrity. If not VERIFIED -> INVALID / UNAVAILABLE.
    3. Reconstruct canonical signing payload from current authoritative output state.
    4. Compute current payload hash and compare with stored signed_payload_hash.
    5. Verify cryptographic signature using the DigitalSigner.
    6. Return VALID if all checks match, INVALID on any mismatch or tamper.
    7. Read-only: never overwrites or re-signs stored records.
    8. Emits signature_verified or signature_failed audit event.
    """
    out_meta = output.output_metadata if isinstance(output.output_metadata, dict) else {}
    stored_sig = out_meta.get("digital_signature")

    # 1. Missing signature -> UNAVAILABLE
    if not isinstance(stored_sig, dict):
        return {
            "status": SignatureStatus.UNAVAILABLE.value,
            "algorithm": None,
            "key_id": None,
            "signature": None,
            "signed_payload_hash": None,
            "signed_integrity_hash": None,
            "signed_provenance_hash": None,
            "signed_at": None,
            "provider": None,
            "details": {
                "reason": "Digital signature record not found (legacy or unsigned output).",
                "signature_verified": False,
                "integrity_verified": False,
            },
        }

    # 2. Verify underlying Phase 2G integrity
    integ_res = verify_output_integrity(output, storage=storage)
    if integ_res["status"] == IntegrityStatus.UNAVAILABLE.value:
        return {
            "status": SignatureStatus.UNAVAILABLE.value,
            "algorithm": stored_sig.get("algorithm"),
            "key_id": stored_sig.get("key_id"),
            "signature": stored_sig.get("signature"),
            "signed_payload_hash": stored_sig.get("signed_payload_hash"),
            "signed_integrity_hash": stored_sig.get("signed_integrity_hash"),
            "signed_provenance_hash": stored_sig.get("signed_provenance_hash"),
            "signed_at": stored_sig.get("signed_at"),
            "provider": stored_sig.get("provider"),
            "details": {
                "reason": "Underlying artifact or storage is unavailable for verification.",
                "signature_verified": False,
                "integrity_verified": False,
                "integrity_detail": integ_res.get("details", {}),
            },
        }

    if integ_res["status"] != IntegrityStatus.VERIFIED.value:
        _emit_signature_audit(
            output=output,
            status=SignatureStatus.INVALID.value,
            outcome="denied",
            reason="underlying_integrity_failed",
            project_id=project_id,
        )
        return {
            "status": SignatureStatus.INVALID.value,
            "algorithm": stored_sig.get("algorithm"),
            "key_id": stored_sig.get("key_id"),
            "signature": stored_sig.get("signature"),
            "signed_payload_hash": stored_sig.get("signed_payload_hash"),
            "signed_integrity_hash": stored_sig.get("signed_integrity_hash"),
            "signed_provenance_hash": stored_sig.get("signed_provenance_hash"),
            "signed_at": stored_sig.get("signed_at"),
            "provider": stored_sig.get("provider"),
            "details": {
                "reason": "Underlying cryptographic integrity is invalid or tampered.",
                "signature_verified": False,
                "integrity_verified": False,
                "integrity_detail": integ_res.get("details", {}),
            },
        }

    # 3. Reconstruct canonical signing payload
    curr_payload = build_signing_payload(output)
    curr_payload_bytes = compute_signing_payload_bytes(curr_payload)
    curr_payload_hash = sha256_bytes(curr_payload_bytes)

    # 4. Check payload hash match
    stored_payload_hash = stored_sig.get("signed_payload_hash")
    payload_match = (stored_payload_hash == curr_payload_hash)

    # 5. Check integrity and provenance references
    stored_int_hash = stored_sig.get("signed_integrity_hash")
    stored_prov_hash = stored_sig.get("signed_provenance_hash")
    int_match = (stored_int_hash == curr_payload.get("artifact_hash"))
    prov_match = (stored_prov_hash == curr_payload.get("provenance_hash"))

    # 6. Verify cryptographic signature
    active_signer = signer
    if active_signer is None:
        active_signer = get_digital_signer(
            provider_override=stored_sig.get("algorithm"),
            key_id=stored_sig.get("key_id"),
        )

    sig_valid = False
    sig_str = stored_sig.get("signature", "")
    if sig_str:
        sig_valid = active_signer.verify(
            curr_payload_bytes,
            sig_str,
            key_id=stored_sig.get("key_id"),
        )

    all_valid = payload_match and int_match and prov_match and sig_valid
    status = SignatureStatus.VALID.value if all_valid else SignatureStatus.INVALID.value

    # 7. Emit audit event
    _emit_signature_audit(
        output=output,
        status=status,
        outcome="allowed" if all_valid else "denied",
        reason="signature_verified" if all_valid else "signature_tamper_detected",
        project_id=project_id,
    )

    details: dict[str, Any] = {
        "signature_verified": sig_valid,
        "payload_verified": payload_match,
        "integrity_verified": int_match,
        "provenance_verified": prov_match,
        "stored_payload_hash": stored_payload_hash,
        "current_payload_hash": curr_payload_hash,
        "signer_public_info": active_signer.get_public_key_info(),
    }
    if not all_valid:
        reasons = []
        if not payload_match:
            reasons.append("Signing payload hash mismatch (governance, provenance, or policy modified).")
        if not int_match:
            reasons.append("Underlying artifact hash mismatch.")
        if not prov_match:
            reasons.append("Provenance digest mismatch.")
        if not sig_valid:
            reasons.append("Digital signature verification failed or signature string corrupted.")
        details["reason"] = " ".join(reasons)

    return {
        "status": status,
        "algorithm": stored_sig.get("algorithm"),
        "key_id": stored_sig.get("key_id"),
        "signature": stored_sig.get("signature"),
        "signed_payload_hash": curr_payload_hash,
        "signed_integrity_hash": stored_int_hash,
        "signed_provenance_hash": stored_prov_hash,
        "signed_at": stored_sig.get("signed_at"),
        "provider": stored_sig.get("provider"),
        "details": details,
    }


def _emit_signature_audit(
    *,
    output: Any,
    status: str,
    outcome: str,
    reason: str,
    project_id: str | None = None,
) -> None:
    p_id = project_id
    if not p_id and hasattr(output, "job") and output.job and hasattr(output.job, "project_id"):
        p_id = str(output.job.project_id)

    event_type = "signature_verified" if status == SignatureStatus.VALID.value else "signature_failed"
    emit_security_event(
        event_type,
        outcome=outcome,
        project_id=p_id,
        job_id=str(output.job_id) if hasattr(output, "job_id") else None,
        reason=reason,
        details={
            "output_id": str(output.id),
            "status": status,
        },
    )
