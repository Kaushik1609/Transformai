"""
TransformIQ / KaryaSetu AI — Cryptographic Integrity & Artifact Hashing Layer (Phase 2G)

Responsible for:
1. Deterministic SHA-256 lowercase hexadecimal digest computation.
2. Canonical JSON serialization (UTF-8, sorted keys, compact separators, no extraneous whitespace).
3. Authoritative artifact hash generation (exact storage bytes for binary, canonical JSON for structured, UTF-8 for text).
4. Companion artifact hashing (named hashes for 'pdf' and 'srt').
5. Deterministic approval snapshot binding from Phase 2F governance metadata.
6. Canonical integrity-bound provenance projection strictly excluding volatile timestamps and circular references.
7. Construction and validation of the persistent cryptographic_integrity envelope.

Guarantees:
- Zero circularity: artifact_hash -> provenance projection -> provenance_hash -> cryptographic_integrity record.
- Secret sanitization: tokens, secrets, credentials, and volatile audit timestamps are strictly excluded.
- Integrity is NOT authorization: verified integrity never overrides dissemination or approval rules.
- Legacy outputs without integrity records evaluate honestly to UNAVAILABLE (no retroactive fabrication).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Domain Enums & Constants
# ---------------------------------------------------------------------------

class IntegrityStatus(str, Enum):
    """Cryptographic integrity status for an output artifact."""

    VERIFIED = "VERIFIED"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


DEFAULT_HASH_ALGORITHM = "sha256"

# Companion storage keys mapped to canonical companion role identifiers
COMPANION_ROLES: dict[str, str] = {
    "pdf": "pdf_storage_key",
    "srt": "subtitle_storage_key",
}


# ---------------------------------------------------------------------------
# Pure Hashing & Canonical Serialization Functions
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    """Compute lowercase SHA-256 hex digest of exact bytes."""
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    """Deterministic canonical JSON serialization as UTF-8 bytes.

    Guarantees:
    - UTF-8 encoded
    - Sorted keys
    - Compact separators (',', ':') with no extraneous whitespace
    - Deterministic primitive representation
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def canonical_json_hash(obj: Any) -> str:
    """Compute deterministic SHA-256 lowercase hex digest of canonical JSON."""
    return sha256_bytes(canonical_json_bytes(obj))


# ---------------------------------------------------------------------------
# Cryptographic Integrity Model
# ---------------------------------------------------------------------------

class CryptographicIntegrityRecord(BaseModel):
    """Persistent cryptographic integrity record stored in output.output_metadata['cryptographic_integrity']."""

    model_config = ConfigDict(extra="forbid")

    algorithm: str = Field(default=DEFAULT_HASH_ALGORITHM, description="Hash algorithm used ('sha256').")
    artifact_hash: str = Field(..., description="Authoritative SHA-256 digest of the primary persisted artifact.")
    companion_hashes: dict[str, str] = Field(default_factory=dict, description="Named SHA-256 digests of companion artifacts.")
    provenance_id: str = Field(..., description="Canonical provenance record identifier.")
    provenance_hash: str = Field(..., description="Deterministic digest of the canonical provenance projection.")
    approval_id: str | None = Field(default=None, description="Latest approval identifier snapshot bound at sealing.")
    recorded_at: str = Field(..., description="ISO 8601 UTC timestamp when integrity was recorded.")
    status: str = Field(default=IntegrityStatus.VERIFIED.value, description="Integrity state at record time ('VERIFIED').")


# ---------------------------------------------------------------------------
# Authoritative Artifact Hashing
# ---------------------------------------------------------------------------

def compute_artifact_hash(
    output: Any,
    storage: Any | None = None,
) -> tuple[str | None, dict[str, str]]:
    """Compute authoritative primary and companion artifact hashes for an Output.

    Production rules:
    1. Binary stored artifacts (has storage_key and mime_type):
       Reads the exact stored bytes using the StorageAdapter and SHA-256 hashes them.
    2. Structured outputs:
       If structured_content is present and a non-empty dict, hashes its canonical JSON representation.
    3. Textual outputs:
       If output has text_content without structured_content, hashes the UTF-8 bytes of text_content.
    4. Companion artifacts:
       Hashes 'pdf' (pdf_storage_key) and 'srt' (subtitle_storage_key) from output_metadata if persisted.

    Returns:
        (primary_hash, companion_hashes_dict)
        If primary artifact cannot be resolved or read, primary_hash is None.
    """
    primary_hash: str | None = None
    companion_hashes: dict[str, str] = {}

    meta = output.output_metadata if isinstance(output.output_metadata, dict) else {}

    # 1. Binary stored artifact (storage_key takes precedence for media/document artifacts)
    if output.storage_key and output.mime_type:
        try:
            if storage is None:
                from app.ingestion.storage import get_storage
                storage = get_storage()
            data = storage.read(output.storage_key)
            if data is not None and len(data) > 0:
                primary_hash = sha256_bytes(data)
        except Exception:
            primary_hash = None

    # 2. Structured content
    elif output.structured_content is not None and isinstance(output.structured_content, dict) and output.structured_content:
        primary_hash = canonical_json_hash(output.structured_content)

    # 3. Text content
    elif output.text_content is not None and output.text_content != "":
        primary_hash = sha256_bytes(output.text_content.encode("utf-8"))

    # 4. Companion artifacts (only hash if corresponding storage key exists)
    if storage is None:
        try:
            from app.ingestion.storage import get_storage
            storage = get_storage()
        except Exception:
            storage = None

    if storage is not None:
        for role, meta_key in COMPANION_ROLES.items():
            companion_key = meta.get(meta_key)
            if companion_key:
                try:
                    c_data = storage.read(companion_key)
                    if c_data is not None and len(c_data) > 0:
                        companion_hashes[role] = sha256_bytes(c_data)
                except Exception:
                    pass

    return primary_hash, companion_hashes


# ---------------------------------------------------------------------------
# Deterministic Approval Snapshot Projection
# ---------------------------------------------------------------------------

def build_approval_snapshot(output: Any) -> dict[str, Any]:
    """Extract a deterministic approval snapshot from output.output_metadata['approval'].

    Includes only relevant governance facts:
    - approval_id
    - destination
    - approval_status
    - decision
    - approver_id, approver_email, approver_role
    - approved_at
    - rejection_reason, comments
    - self_approved
    - policy_reason
    - classification_snapshot, verification_status_snapshot, source_hash_snapshot, policy_id_snapshot

    Strictly excludes volatile UI fields and credentials.
    """
    meta = output.output_metadata if isinstance(output.output_metadata, dict) else {}
    approval_meta = meta.get("approval")

    if not isinstance(approval_meta, dict):
        return {
            "destinations": {},
            "latest_approval_id": None,
        }

    raw_dests = approval_meta.get("destinations", {})
    destinations_snapshot: dict[str, Any] = {}

    if isinstance(raw_dests, dict):
        for dest_name in sorted(raw_dests.keys()):
            d = raw_dests[dest_name]
            if isinstance(d, dict):
                destinations_snapshot[dest_name] = {
                    "destination": d.get("destination") or dest_name,
                    "approval_status": d.get("approval_status"),
                    "approval_id": d.get("approval_id"),
                    "decision": d.get("decision"),
                    "approver_id": d.get("approver_id"),
                    "approver_email": d.get("approver_email"),
                    "approver_role": d.get("approver_role"),
                    "approved_at": d.get("approved_at"),
                    "rejection_reason": d.get("rejection_reason"),
                    "comments": d.get("comments"),
                    "self_approved": bool(d.get("self_approved", False)),
                    "policy_reason": d.get("policy_reason"),
                    "classification_snapshot": d.get("classification_snapshot"),
                    "verification_status_snapshot": d.get("verification_status_snapshot"),
                    "source_hash_snapshot": d.get("source_hash_snapshot"),
                    "policy_id_snapshot": d.get("policy_id_snapshot"),
                }

    return {
        "destinations": destinations_snapshot,
        "latest_approval_id": approval_meta.get("latest_approval_id"),
    }


# ---------------------------------------------------------------------------
# Deterministic Provenance Projection & Provenance Hashing
# ---------------------------------------------------------------------------

def build_provenance_projection(
    provenance_record: dict[str, Any],
    *,
    approval_snapshot: dict[str, Any],
    artifact_hash: str,
    companion_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Construct an integrity-bound canonical provenance projection.

    Rules:
    - strictly deterministic and reproducible.
    - binds: source, evidence, transformation, policy_routing, generator,
      verification, dissemination, approval snapshot, artifact hash, companion hashes.
    - strictly EXCLUDES:
        * volatile audit timestamps (e.g. audit.recorded_at)
        * provenance record creation timestamp (created_at)
        * self-referential provenance_hash
        * cryptographic_integrity envelope
        * verification timestamp generated after hashing
    """
    source_raw = provenance_record.get("source", {})
    source_snapshot = {
        "source_id": source_raw.get("source_id"),
        "source_type": source_raw.get("source_type"),
        "original_filename": source_raw.get("original_filename"),
        "source_content_hash": source_raw.get("source_content_hash"),
        "classification": source_raw.get("classification"),
        "source_version": source_raw.get("source_version"),
    }

    evidence_raw = provenance_record.get("evidence", {})
    citations_raw = evidence_raw.get("citations", [])
    citations_snapshot: list[dict[str, Any]] = []
    if isinstance(citations_raw, list):
        for c in citations_raw:
            if isinstance(c, dict):
                citations_snapshot.append({
                    "chunk_id": c.get("chunk_id"),
                    "source_id": c.get("source_id"),
                    "chunk_index": c.get("chunk_index"),
                    "content_hash": c.get("content_hash"),
                    "relevance_score": c.get("relevance_score"),
                    "excerpt": c.get("excerpt"),
                })

    evidence_snapshot = {
        "retrieval_method": evidence_raw.get("retrieval_method"),
        "chunks_count": evidence_raw.get("chunks_count"),
        "citations": citations_snapshot,
    }

    trans_raw = provenance_record.get("transformation", {})
    transformation_snapshot = {
        "transformation_id": trans_raw.get("transformation_id"),
        "job_id": trans_raw.get("job_id"),
        "project_id": trans_raw.get("project_id"),
        "requested_outputs": sorted(list(trans_raw.get("requested_outputs", []))),
        "prompt_provided": trans_raw.get("prompt_provided"),
    }

    routing_raw = provenance_record.get("policy_routing", {})
    routing_snapshot = {
        "classification": routing_raw.get("classification"),
        "processing_route": routing_raw.get("processing_route"),
        "provider_id": routing_raw.get("provider_id"),
        "model_id": routing_raw.get("model_id"),
        "provider_category": routing_raw.get("provider_category"),
        "policy_id": routing_raw.get("policy_id"),
        "routing_reason": routing_raw.get("routing_reason"),
    }

    gen_raw = provenance_record.get("generator", {})
    generator_snapshot = {
        "output_type": gen_raw.get("output_type"),
        "generator_class": gen_raw.get("generator_class"),
        "generator_version": gen_raw.get("generator_version"),
        "schema_name": gen_raw.get("schema_name"),
        "schema_version": gen_raw.get("schema_version"),
        "prompt_identifier": gen_raw.get("prompt_identifier"),
    }

    verif_raw = provenance_record.get("verification", {})
    verification_snapshot = {
        "verification_result_id": verif_raw.get("verification_result_id"),
        "has_verification": verif_raw.get("has_verification"),
        "overall_status": verif_raw.get("overall_status"),
        "grounding_score": verif_raw.get("grounding_score"),
        "consistency_score": verif_raw.get("consistency_score"),
        "claims_checked": verif_raw.get("claims_checked"),
        "claims_supported": verif_raw.get("claims_supported"),
    }

    dissem_raw = provenance_record.get("dissemination", {})
    dissemination_snapshot = {
        "policy_id": dissem_raw.get("policy_id"),
        "primary_destination": dissem_raw.get("primary_destination"),
        "primary_decision": dissem_raw.get("primary_decision"),
        "primary_allowed": dissem_raw.get("primary_allowed"),
    }

    sorted_companions = {
        k: companion_hashes[k] for k in sorted((companion_hashes or {}).keys())
    }

    return {
        "provenance_id": provenance_record.get("provenance_id"),
        "version": provenance_record.get("version"),
        "source": source_snapshot,
        "evidence": evidence_snapshot,
        "transformation": transformation_snapshot,
        "policy_routing": routing_snapshot,
        "generator": generator_snapshot,
        "verification": verification_snapshot,
        "dissemination": dissemination_snapshot,
        "approval": approval_snapshot,
        "artifact_hash": artifact_hash,
        "companion_hashes": sorted_companions,
    }


def compute_provenance_hash(projection: dict[str, Any]) -> str:
    """Compute deterministic lowercase SHA-256 hex digest of the canonical provenance projection."""
    return canonical_json_hash(projection)
