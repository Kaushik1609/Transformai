"""
TransformIQ / KaryaSetu AI — Deterministic Evidence & Provenance Layer (Phase 2E)

Responsible for constructing, validating, and persisting the canonical provenance
record for every generated output artifact.

Lineage Chain:
    SOURCE
    → EVIDENCE CHUNKS (RAG citations captured at generation time)
    → TRANSFORMATION / JOB
    → POLICY CLASSIFICATION & AI ROUTING
    → GENERATOR & SCHEMA
    → FACT VERIFICATION (Phase 8 / 11N)
    → DISSEMINATION POLICY (Phase 2D)
    → ARTIFACT INTEGRITY (Phase 11M / SHA-256)
    → SECURITY AUDIT EVENT

Guarantees:
- Zero-LLM dependency: Provenance assembly is purely deterministic.
- Secret sanitization: API keys, tokens, credentials, and raw configurations are strictly excluded.
- Bounded storage: Evidence excerpts are capped to prevent JSONB bloat.
- Historical resilience: Snapshots chunk IDs, indices, and content hashes so lineage
  remains verifiable even if underlying sources are modified or re-ingested.
- Fail-open in worker: Provenance errors never abort artifact generation or corrupt results.
- Future-proof: Extension slots for Phases 2F (approvals), 2G (signatures), 2I (air-gap).
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PROVENANCE_SCHEMA_VERSION = "1.0"
MAX_EXCERPT_CHARS = 250


# ---------------------------------------------------------------------------
# Provenance Data Schemas
# ---------------------------------------------------------------------------

class SourceLineage(BaseModel):
    """Immutable snapshot of the source document at transformation time."""

    model_config = ConfigDict(extra="forbid")

    source_id: str | None = Field(default=None, description="UUID of the source document, or null if prompt-only.")
    source_type: str | None = Field(default=None, description="Type of source (e.g. 'pdf', 'docx', 'text').")
    original_filename: str | None = Field(default=None, description="Original filename of the source.")
    source_content_hash: str | None = Field(default=None, description="Optional content hash of the source text if available.")
    classification: str = Field(default="INTERNAL", description="Information classification label.")
    created_at: str | None = Field(default=None, description="ISO timestamp when the source was uploaded.")
    source_version: str | None = Field(default=None, description="Source version identifier if supported.")


class EvidenceCitationLineage(BaseModel):
    """Bounded, auditable record of a single evidence chunk used during generation."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str | None = Field(default=None, description="UUID of the source chunk.")
    source_id: str | None = Field(default=None, description="Source document UUID.")
    chunk_index: int = Field(default=0, ge=0, description="Order of chunk within the source.")
    content_hash: str | None = Field(default=None, description="SHA-256 prefix hash of chunk content.")
    relevance_score: float | None = Field(default=None, description="Similarity score from vector retrieval.")
    excerpt: str = Field(default="", description="Bounded text excerpt from the chunk.")


class EvidenceLineage(BaseModel):
    """Structured evidence set that grounded the transformation."""

    model_config = ConfigDict(extra="forbid")

    retrieval_method: str = Field(default="none", description="Method used for evidence retrieval.")
    chunks_count: int = Field(default=0, ge=0, description="Number of evidence citations used.")
    citations: list[EvidenceCitationLineage] = Field(default_factory=list, description="Exact citations that grounded generation.")


class TransformationLineage(BaseModel):
    """Context of the transformation execution request."""

    model_config = ConfigDict(extra="forbid")

    transformation_id: str | None = Field(default=None, description="Optional transformation request ID.")
    job_id: str = Field(..., description="UUID of the executing TransformationJob.")
    project_id: str = Field(..., description="UUID of the parent Project.")
    requested_outputs: list[str] = Field(default_factory=list, description="Sibling output types in this transformation.")
    prompt_provided: bool = Field(default=False, description="True if an operator prompt was supplied.")


class PolicyRoutingLineage(BaseModel):
    """Policy engine and AI routing decision metadata."""

    model_config = ConfigDict(extra="forbid")

    classification: str = Field(..., description="Evaluated information classification.")
    processing_route: str = Field(..., description="Authoritative route ('cloud', 'private_local', 'controlled_internal').")
    provider_id: str = Field(..., description="Canonical ID of the resolved AI provider (e.g. 'openai', 'local', 'fake').")
    model_id: str = Field(..., description="Model identifier used for generation.")
    provider_category: str = Field(..., description="Provider category ('commercial_cloud', 'private_local', 'test_mock').")
    policy_id: str = Field(default="karyasetu-policy-v1", description="Policy engine version identifier.")
    routing_reason: str = Field(default="", description="Justification for the routing decision.")


class GeneratorLineage(BaseModel):
    """Identity and schema metadata of the output generator."""

    model_config = ConfigDict(extra="forbid")

    output_type: str = Field(..., description="Output type (e.g. 'summary', 'linkedin', 'presentation').")
    generator_class: str = Field(..., description="Name of the generator class.")
    generator_version: str | None = Field(default=None, description="Version of the generator if available.")
    schema_name: str | None = Field(default=None, description="Structured Pydantic schema name for this output.")
    schema_version: str | None = Field(default=None, description="Schema version identifier if available.")
    prompt_identifier: str | None = Field(default=None, description="Prompt identifier or version if available.")


class VerificationLineage(BaseModel):
    """Post-generation fact verification metrics."""

    model_config = ConfigDict(extra="forbid")

    verification_result_id: str | None = Field(default=None, description="UUID of the VerificationResult record.")
    has_verification: bool = Field(default=False, description="True if fact verification was performed.")
    overall_status: str | None = Field(default=None, description="Status ('passed', 'warning', 'failed').")
    grounding_score: float | None = Field(default=None, description="Score indicating source grounding quality.")
    consistency_score: float | None = Field(default=None, description="Score indicating factual consistency.")
    claims_checked: int | None = Field(default=None, description="Total checkable claims analyzed.")
    claims_supported: int | None = Field(default=None, description="Claims supported by evidence.")


class DisseminationLineage(BaseModel):
    """Phase 2D dissemination policy determination."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(default="karyasetu-dissemination-v1", description="Dissemination policy version.")
    primary_destination: str = Field(default="INTERNAL", description="Primary target dissemination destination.")
    primary_decision: str = Field(default="ALLOW", description="Primary decision ('ALLOW', 'BLOCK', 'REVIEW').")
    primary_allowed: bool = Field(default=True, description="Whether primary destination is allowed.")


class IntegrityLineage(BaseModel):
    """Phase 11M artifact content integrity."""

    model_config = ConfigDict(extra="forbid")

    algorithm: str = Field(default="sha256", description="Digest algorithm used.")
    content_digest: str | None = Field(default=None, description="Hexadecimal SHA-256 hash of artifact content.")
    representation: str | None = Field(default=None, description="'binary' for files, 'text' for textual outputs.")
    ledger_status: str | None = Field(default=None, description="'recorded', 'local', or 'unavailable'.")
    ledger_reference: str | None = Field(default=None, description="Ledger reference or local reference.")


class AuditLineage(BaseModel):
    """Audit event reference."""

    model_config = ConfigDict(extra="forbid")

    provenance_event_type: str = Field(default="provenance_recorded", description="Audit event identifier.")
    recorded_at: str = Field(..., description="ISO 8601 UTC timestamp of provenance recording.")


class ProvenanceExtensions(BaseModel):
    """Forward-compatible extension slots for future governance phases (2F–2I)."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str | None = Field(default=None, description="Reserved for Phase 2F Human Approval.")
    signature: str | None = Field(default=None, description="Reserved for Phase 2H Digital Signatures.")
    signature_algorithm: str | None = Field(default=None, description="Reserved for Phase 2H Signature Algorithm.")
    airgap_bundle_id: str | None = Field(default=None, description="Reserved for Phase 2I Air-Gapped Deployment.")


class ProvenanceRecord(BaseModel):
    """Canonical, auditable provenance record for a single transformation output."""

    model_config = ConfigDict(extra="forbid")

    provenance_id: str = Field(..., description="Unique, stable identifier for this output's provenance record.")
    version: str = Field(default=PROVENANCE_SCHEMA_VERSION, description="Provenance specification version.")
    created_at: str = Field(..., description="ISO timestamp when this provenance record was created.")

    source: SourceLineage
    evidence: EvidenceLineage
    transformation: TransformationLineage
    policy_routing: PolicyRoutingLineage
    generator: GeneratorLineage
    verification: VerificationLineage
    dissemination: DisseminationLineage
    integrity: IntegrityLineage
    audit: AuditLineage
    extensions: ProvenanceExtensions = Field(default_factory=ProvenanceExtensions)


# ---------------------------------------------------------------------------
# Output Type to Schema Mapping
# ---------------------------------------------------------------------------

_OUTPUT_SCHEMA_NAMES: dict[str, str] = {
    "summary": "ExecutiveSummary",
    "linkedin": "LinkedInPost",
    "advisory": "PolicyAdvisory",
    "presentation": "PresentationDeck",
    "x": "XThread",
    "infographic": "InfographicSpec",
    "video": "VideoScript",
}


# ---------------------------------------------------------------------------
# Provenance Builder
# ---------------------------------------------------------------------------

def create_provenance_id(output_id: uuid.UUID | str) -> str:
    """Generate a deterministic or unique provenance identifier bound to an output."""
    return f"prov-{output_id}"


def sanitize_text_excerpt(text: str | None, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    """Return a bounded, whitespace-normalized excerpt."""
    if not text:
        return ""
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "..."


def compute_content_hash(text: str | None) -> str | None:
    """Compute a deterministic 16-character SHA-256 digest of text.

    This matches the canonical hash format stored in SourceChunk.chunk_metadata["content_hash"]
    (hashlib.sha256(content_chunk.encode("utf-8")).hexdigest()[:16]).
    """
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class ProvenanceBuilder:
    """Deterministic assembler of canonical ProvenanceRecord instances."""

    @staticmethod
    def build_record(
        *,
        output_id: uuid.UUID | str,
        job_id: uuid.UUID | str,
        project_id: uuid.UUID | str,
        output_type: str,
        source: Any | None = None,
        classification: str = "INTERNAL",
        requested_outputs: list[str] | None = None,
        prompt_provided: bool = False,
        citations: list[dict[str, Any]] | None = None,
        retrieval_method: str | None = None,
        routing_metadata: dict[str, Any] | None = None,
        generator_class: str | None = None,
        verification_result: Any | None = None,
        dissemination_metadata: dict[str, Any] | None = None,
        integrity_metadata: dict[str, Any] | None = None,
        audit_event_type: str | None = None,
        is_backfill: bool = False,
        created_at: datetime | None = None,
    ) -> ProvenanceRecord:
        """Construct a validated ProvenanceRecord from runtime objects."""
        now_iso = (created_at or datetime.now(timezone.utc)).isoformat()
        prov_id = create_provenance_id(output_id)

        # 1. Source Lineage
        source_lineage = SourceLineage(
            source_id=str(source.id) if source and getattr(source, "id", None) else None,
            source_type=str(source.source_type) if source and getattr(source, "source_type", None) else None,
            original_filename=str(source.original_filename) if source and getattr(source, "original_filename", None) else None,
            source_content_hash=(
                compute_content_hash(getattr(source, "extracted_text", None))
                if source else None
            ),
            classification=str(classification),
            created_at=(
                source.created_at.isoformat()
                if source and getattr(source, "created_at", None)
                else None
            ),
        )

        # 2. Evidence Lineage
        raw_citations = citations or []
        evidence_citations: list[EvidenceCitationLineage] = []
        for c in raw_citations:
            excerpt = sanitize_text_excerpt(c.get("excerpt") or c.get("evidence"))
            # Canonical chunk content hash:
            # 1. Use existing canonical content_hash if already computed/available from SourceChunk
            # 2. Compute from full chunk evidence if present (never just a truncated excerpt)
            # 3. Fallback to excerpt hash only when full chunk evidence is completely absent
            full_evidence = c.get("evidence")
            chash = (
                c.get("content_hash")
                or (compute_content_hash(full_evidence) if full_evidence else compute_content_hash(excerpt))
            )
            evidence_citations.append(
                EvidenceCitationLineage(
                    chunk_id=str(c.get("chunk_id")) if c.get("chunk_id") else None,
                    source_id=str(c.get("source_id")) if c.get("source_id") else (str(source.id) if source else None),
                    chunk_index=int(c.get("chunk_index", 0)),
                    content_hash=chash,
                    relevance_score=(
                        float(c["relevance_score"])
                        if c.get("relevance_score") is not None
                        else None
                    ),
                    excerpt=excerpt,
                )
            )

        resolved_retrieval_method = retrieval_method
        if not resolved_retrieval_method:
            if citations is None:
                # Historical / legacy provenance backfill where citations were not captured at generation time.
                # Honestly indicate "unavailable" rather than fabricating citations or falsely claiming "none".
                resolved_retrieval_method = "unavailable"
            elif evidence_citations:
                resolved_retrieval_method = "cosine-similarity-pgvector"
            else:
                # Legitimate transformation with no RAG requirement
                resolved_retrieval_method = "none"

        evidence_lineage = EvidenceLineage(
            retrieval_method=resolved_retrieval_method,
            chunks_count=len(evidence_citations),
            citations=evidence_citations,
        )

        # 3. Transformation Lineage
        transformation_lineage = TransformationLineage(
            job_id=str(job_id),
            project_id=str(project_id),
            requested_outputs=requested_outputs or [output_type],
            prompt_provided=prompt_provided,
        )

        # 4. Policy Routing Lineage
        # Extract safe non-secret fields from routing_metadata or resilience metadata
        rmeta = routing_metadata or {}
        from app.policy.classification import normalize_classification
        from app.policy.routing import get_policy_router

        norm_class = normalize_classification(classification)
        # Attempt to resolve compliant route info deterministically if not explicitly supplied
        p_id = rmeta.get("provider") or rmeta.get("provider_id")
        m_id = rmeta.get("model") or rmeta.get("model_id")
        p_cat = rmeta.get("provider_category")
        p_route = rmeta.get("processing_route")
        p_reason = rmeta.get("reason") or rmeta.get("routing_reason") or ""

        if not (p_id and m_id and p_cat and p_route):
            try:
                from app.policy.classification import InformationClassification
                from app.policy.routing import get_policy_router

                target_env = (
                    "local"
                    if norm_class in (InformationClassification.CONFIDENTIAL, InformationClassification.RESTRICTED)
                    else "cloud"
                )
                req_p = p_id or ("local" if target_env == "local" else None)
                router = get_policy_router()
                rd = router.resolve_route(norm_class, requested_provider=req_p, requested_model=m_id, environment=target_env)
                p_id = rd.provider_id
                m_id = rd.model_id
                p_cat = rd.provider_category.value
                p_route = rd.processing_route.value
                p_reason = rd.reason
            except Exception:
                p_id = p_id or "local"
                m_id = m_id or "default"
                p_cat = p_cat or ("commercial_cloud" if p_route == "cloud" else "private_local")
                p_route = p_route or "private_local"
                p_reason = p_reason or "default policy resolution"

        routing_lineage = PolicyRoutingLineage(
            classification=norm_class.value,
            processing_route=str(p_route),
            provider_id=str(p_id),
            model_id=str(m_id),
            provider_category=str(p_cat),
            policy_id="karyasetu-policy-v1",
            routing_reason=str(p_reason),
        )

        # 5. Generator Lineage
        gen_class = generator_class or f"{output_type.capitalize()}Generator"
        schema_name = _OUTPUT_SCHEMA_NAMES.get(output_type.lower())
        generator_lineage = GeneratorLineage(
            output_type=output_type,
            generator_class=gen_class,
            schema_name=schema_name,
        )

        # 6. Verification Lineage
        if verification_result is not None:
            verification_lineage = VerificationLineage(
                verification_result_id=str(getattr(verification_result, "id", "")),
                has_verification=True,
                overall_status=getattr(verification_result, "overall_status", "warning"),
                grounding_score=(
                    float(verification_result.grounding_score)
                    if getattr(verification_result, "grounding_score", None) is not None
                    else None
                ),
                consistency_score=(
                    float(verification_result.consistency_score)
                    if getattr(verification_result, "consistency_score", None) is not None
                    else None
                ),
                claims_checked=getattr(verification_result, "claims_checked", 0),
                claims_supported=getattr(verification_result, "claims_supported", 0),
            )
        else:
            verification_lineage = VerificationLineage(has_verification=False)

        # 7. Dissemination Lineage
        dmeta = dissemination_metadata or {}
        dissemination_lineage = DisseminationLineage(
            policy_id=dmeta.get("policy_id", "karyasetu-dissemination-v1"),
            primary_destination=dmeta.get("primary_destination", "INTERNAL"),
            primary_decision=dmeta.get("primary_decision", "ALLOW"),
            primary_allowed=bool(dmeta.get("primary_allowed", True)),
        )

        # 8. Integrity Lineage
        imeta = integrity_metadata or {}
        integrity_lineage = IntegrityLineage(
            algorithm=imeta.get("algorithm", "sha256"),
            content_digest=imeta.get("digest") or imeta.get("content_digest"),
            representation=imeta.get("representation", "text"),
            ledger_status=imeta.get("status"),
            ledger_reference=imeta.get("reference"),
        )

        # 9. Audit Lineage
        audit_event = audit_event_type or (
            "provenance_backfilled" if (is_backfill or citations is None) else "provenance_recorded"
        )
        audit_lineage = AuditLineage(
            provenance_event_type=audit_event,
            recorded_at=now_iso,
        )

        return ProvenanceRecord(
            provenance_id=prov_id,
            version=PROVENANCE_SCHEMA_VERSION,
            created_at=now_iso,
            source=source_lineage,
            evidence=evidence_lineage,
            transformation=transformation_lineage,
            policy_routing=routing_lineage,
            generator=generator_lineage,
            verification=verification_lineage,
            dissemination=dissemination_lineage,
            integrity=integrity_lineage,
            audit=audit_lineage,
            extensions=ProvenanceExtensions(),
        )


def get_provenance_builder() -> type[ProvenanceBuilder]:
    """Return the ProvenanceBuilder class."""
    return ProvenanceBuilder
