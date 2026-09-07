"""Phase 11M — artifact integrity & provenance service.

The integrity layer is strictly POST-GENERATION: it reads the already-persisted
artifact bytes (or the exact persisted text representation), computes a
deterministic SHA-256 digest, optionally submits it to the configured ledger,
and stores the resulting provenance status in ``output_metadata["integrity"]``
(no database schema change).

Failure isolation:
  * Artifact persistence is independent of provenance. If the ledger is
    unavailable the artifact remains intact and the provenance status honestly
    reflects ``unavailable`` — the write is never faked as recorded.
  * Verification is always read-only and compares the CURRENT bytes against the
    RECORDED digest. Any change in bytes => verification FAILS.

Digests are computed over content only (never filenames, row IDs, URLs or
metadata). For binary artifacts (presentation/infographic/video) the exact
persisted storage bytes are hashed; for text outputs the exact persisted
``text_content`` representation is hashed.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from app.core.audit import emit_security_event
from app.core.metrics import metrics
from app.db.models.output import Output
from app.integrity.factory import build_ledger
from app.integrity.ledger import IntegrityLedger, IntegrityRecord, LedgerStatus

INTEGRITY_META_KEY = "integrity"

# Role -> metadata key holding the already-recorded Phase 11H-I sha256 digest.
_ROLE_DIGEST_KEYS: dict[str, str] = {
    "primary": "artifact_sha256",
    "pdf": "pdf_sha256",
    "srt": "srt_sha256",
}


def sha256_digest(content: bytes) -> str:
    """Lowercase SHA-256 hex digest of the exact content bytes."""
    return hashlib.sha256(content).hexdigest()


def _norm_algorithm(algorithm: str | None) -> str:
    return (algorithm or "sha256").lower()


def integrity_status_enum(value: str | None) -> str:
    """Map a stored provenance status string to a safe canonical value."""
    if value in ("recorded", "unavailable", "local"):
        return value
    return "unavailable"


def _record_for_output(
    output: Output,
    *,
    storage: Any,
    ledger: Optional[IntegrityLedger],
    algorithm: str,
    output_id: UUID,
) -> tuple[str | None, str, str]:
    """Compute the persisted-content digest for an output artifact.

    Returns ``(digest, representation, provider_status)`` where ``provider`` is
    the ledger provider name (or ``local`` when no ledger is configured, meaning
    hashes + local verification only).

    For binary artifacts the primary storage bytes are read back and hashed. For
    text outputs the exact persisted ``text_content`` is hashed. If no readable
    bytes exist (e.g. a non-artifact path) this returns no digest.
    """
    represent = "binary"
    if output.storage_key and output.mime_type:
        try:
            data = storage.read(output.storage_key)
        except Exception:
            data = None
        if data is None:
            return None, represent, "unavailable"
        digest = sha256_digest(data)
        provider = ledger.provider_name if ledger is not None else "local"
        return digest, represent, provider

    # Text/structured outputs persist their content on the Output row itself.
    text = (output.text_content or "").encode("utf-8")
    if not text:
        return None, represent, "unavailable"
    digest = sha256_digest(text)
    provider = ledger.provider_name if ledger is not None else "local"
    return digest, "text", provider


def record_output_integrity(
    output: Output,
    *,
    storage: Any,
    ledger: Optional[IntegrityLedger] = None,
    algorithm: str = "sha256",
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """Record integrity/provenance for a completed artifact (post-generation).

    Never raises on a ledger failure: it returns the provenance status so
    artifact persistence and the transformation result are unaffected. When a
    ledger is unavailable the stored status is ``unavailable`` (never ``recorded``).
    """
    provider = None
    reference = None
    status = LedgerStatus.UNAVAILABLE
    recorded = False
    ledger_ref: Optional[IntegrityRecord] = None

    if ledger is not None:
        provider = ledger.provider_name

    digest, represent, provider_status = _record_for_output(
        output, storage=storage, ledger=ledger,
        algorithm=_norm_algorithm(algorithm), output_id=output.id,
    )

    if digest is None:
        status = LedgerStatus.UNAVAILABLE
        metrics.inc("integrity_hashes_total", {"result": "not_hashable", "provider": provider_status})
    else:
        metrics.inc("integrity_hashes_total", {"result": "success", "provider": provider_status})
        if ledger is not None:
            recorded, ledger_ref, status = ledger.record_integrity_event(
                digest=digest, algorithm=_norm_algorithm(algorithm)
            )
            if ledger_ref is not None:
                reference = ledger_ref.reference
        # No ledger configured == local-hash-only provenance.
        if ledger is None:
            status = LedgerStatus.RECORDED
            recorded = True
            reference = f"local-{digest[:16]}"

    metrics.inc(
        "integrity_ledger_total",
        {"provider": provider or "none", "operation": "record", "result":
            "recorded" if status == LedgerStatus.RECORDED
            else "unavailable" if status == LedgerStatus.UNAVAILABLE else "error"},
    )

    meta = {
        "status": integrity_status_enum(status.value),
        "digest": digest,
        "algorithm": _norm_algorithm(algorithm),
        "representation": represent,
        "provider": provider or "none",
        "reference": reference,
        "recorded": recorded,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    output.output_metadata = {
        **(output.output_metadata or {}),
        INTEGRITY_META_KEY: meta,
    }

    emit_security_event(
        "artifact_integrity_recorded",
        outcome="allowed" if recorded else "observed",
        project_id=project_id,
        job_id=str(output.job_id),
        reason=status.value if not recorded else "recorded",
        details={
            "output_id": str(output.id),
            "provider": provider or "none",
            "representation": represent,
        },
    )
    return meta


def verify_output_integrity(
    output: Output,
    *,
    storage: Any,
    ledger: Optional[IntegrityLedger] = None,
    role: str = "primary",
) -> dict[str, Any]:
    """Verify the CURRENT artifact bytes against the RECORDED digest.

    This is read-only and always recomputes the SHA-256 over the current
    persisted bytes (or current text representation) and compares it to the
    digest recorded in ``output_metadata.integrity.digest``. If bytes have
    changed the verification FAILS; if they match it PASSES. Filenames and
    metadata are never the basis of the check.

    Returns a bounded, secret-free result dict.
    """
    recorded_meta = (output.output_metadata or {}).get(INTEGRITY_META_KEY)
    recorded_digest = (recorded_meta or {}).get("digest") if isinstance(recorded_meta, dict) else None

    if not recorded_digest or not (output.storage_key or output.text_content):
        result = {
            "verified": False,
            "status": "not_recorded",
            "message": "No integrity record exists for this artifact.",
        }
        metrics.inc("integrity_verifications_total", {"result": "not_recorded"})
        emit_security_event(
            "artifact_integrity_verification_failed",
            outcome="observed",
            job_id=str(output.job_id),
            reason="not_recorded",
            details={"output_id": str(output.id), "role": role},
        )
        return result

    current_digest: str | None = None
    if output.storage_key and output.mime_type:
        try:
            data = storage.read(output.storage_key)
        except Exception:
            data = None
        if data is not None:
            current_digest = sha256_digest(data)
    else:
        current_digest = sha256_digest((output.text_content or "").encode("utf-8"))

    if current_digest is None:
        result = {
            "verified": False,
            "status": "artifact_unreadable",
            "message": "The artifact bytes could not be read for verification.",
        }
        metrics.inc("integrity_verifications_total", {"result": "artifact_unreadable"})
        return result

    if current_digest == recorded_digest:
        result = {
            "verified": True,
            "status": "verified",
            "message": "The artifact matches its recorded SHA-256 digest.",
            "digest": recorded_digest,
            "algorithm": (recorded_meta or {}).get("algorithm", "sha256"),
        }
        metrics.inc("integrity_verifications_total", {"result": "verified"})
        emit_security_event(
            "artifact_integrity_verification_passed",
            outcome="allowed",
            job_id=str(output.job_id),
            reason="hash_match",
            details={"output_id": str(output.id), "role": role},
        )
        return result

    result = {
        "verified": False,
        "status": "tampered",
        "message": "The artifact bytes do NOT match the recorded SHA-256 digest.",
    }
    metrics.inc("integrity_verifications_total", {"result": "tampered"})
    emit_security_event(
        "artifact_integrity_verification_failed",
        outcome="denied",
        job_id=str(output.job_id),
        reason="hash_mismatch",
        details={"output_id": str(output.id), "role": role},
    )
    return result


__all__ = [
    "INTEGRITY_META_KEY",
    "record_output_integrity",
    "verify_output_integrity",
    "sha256_digest",
]
