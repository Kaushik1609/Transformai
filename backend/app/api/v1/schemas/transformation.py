"""
TransformIQ Backend — Transformation Job, Output, VerificationResult Schemas

Request and response schemas for transformation jobs.
Phase 2: persistence model only. No actual job enqueueing.
"""
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.transformation.generators import KNOWN_OUTPUT_TYPES


# ---------------------------------------------------------------------------
# Transformation Job schemas
# ---------------------------------------------------------------------------

class TransformationJobCreate(BaseModel):
    """
    Body for POST /api/v1/transformations

    Creates a transformation job record. Phase 6 will actually enqueue the job.

    Phase 15: at least one of ``source_id`` / ``prompt`` is required
    (source-only, prompt-only, or source + prompt are all supported).
    """
    project_id: uuid.UUID = Field(..., description="Project UUID")
    source_id: uuid.UUID | None = Field(
        default=None,
        description="Source UUID (optional when a prompt is supplied)",
    )
    configuration_id: uuid.UUID = Field(..., description="Configuration UUID")
    prompt: str | None = Field(
        default=None,
        max_length=500_000,
        description="Operator prompt (optional when a source is supplied)",
    )
    output_types: list[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="List of output types: summary | linkedin | x | advisory | infographic | presentation | video",
    )
    llm_provider: str | None = Field(
        default=None,
        description="Optional LLM provider override: fake | gemini | openai | local",
    )
    model: str | None = Field(
        default=None,
        description="Optional model identifier override (e.g. 'gpt-4o-mini', 'llama-3-8b')",
    )

    @field_validator("prompt")
    @classmethod
    def _strip_prompt(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        return value or None

    @field_validator("output_types")
    @classmethod
    def _validate_output_types(cls, values: list[str]) -> list[str]:
        oversized = sorted(
            {value for value in values if not value or len(value) > 32}
        )
        if oversized:
            raise ValueError(
                "Output type names must each be between 1 and 32 characters; "
                "got oversized value(s): "
                + ", ".join(repr(value[:32]) for value in oversized)
            )
        unknown = sorted({value for value in values if value not in KNOWN_OUTPUT_TYPES})
        if unknown:
            raise ValueError(
                "Unsupported output type(s): "
                + ", ".join(repr(value) for value in unknown)
                + f". Supported output types: {sorted(KNOWN_OUTPUT_TYPES)}"
            )
        return values

    @model_validator(mode="after")
    def _require_an_input(self) -> "TransformationJobCreate":
        if self.source_id is None and not self.prompt:
            raise ValueError(
                "At least one transformation input is required: provide a "
                "source_id, a prompt, or both."
            )
        return self


class TransformationJobResponse(BaseModel):
    """Serialized transformation job record."""

    id: uuid.UUID
    project_id: uuid.UUID
    source_id: uuid.UUID | None
    configuration_id: uuid.UUID
    prompt: str | None = None
    requested_outputs: dict[str, Any] | None
    status: str
    progress: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TransformationJobListResponse(BaseModel):
    success: bool = True
    data: list[TransformationJobResponse]
    count: int


class TransformationJobDetailResponse(BaseModel):
    success: bool = True
    data: TransformationJobResponse


# ---------------------------------------------------------------------------
# Output schemas
# ---------------------------------------------------------------------------

class OutputResponse(BaseModel):
    """Serialized output record."""

    id: uuid.UUID
    job_id: uuid.UUID
    output_type: str
    status: str
    structured_content: dict[str, Any] | None
    text_content: str | None
    storage_key: str | None
    mime_type: str | None
    output_metadata: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OutputListResponse(BaseModel):
    success: bool = True
    data: list[OutputResponse]
    count: int


class OutputDetailResponse(BaseModel):
    success: bool = True
    data: OutputResponse


# ---------------------------------------------------------------------------
# Verification Result schemas
# ---------------------------------------------------------------------------

class VerificationResultResponse(BaseModel):
    """Serialized verification result record."""

    id: uuid.UUID
    output_id: uuid.UUID
    overall_status: str
    grounding_score: float | None
    consistency_score: float | None
    claims_checked: int | None
    claims_supported: int | None
    warnings: dict[str, Any] | None
    details: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class VerificationListResponse(BaseModel):
    success: bool = True
    data: list[VerificationResultResponse]
    count: int


# ---------------------------------------------------------------------------
# Artifact integrity / provenance (Phase 11M)
# ---------------------------------------------------------------------------

class IntegrityRecordResponse(BaseModel):
    """Serialized integrity/provenance record for an output artifact."""

    output_id: uuid.UUID
    digest: str | None = None
    algorithm: str | None = None
    representation: str | None = None
    provider: str | None = None
    reference: str | None = None
    status: str
    recorded: bool
    verified_at: datetime | None = None

    model_config = {"from_attributes": True}


class IntegrityResultResponse(BaseModel):
    """Read-only verification result for an output artifact."""

    verified: bool
    status: str
    message: str
    digest: str | None = None
    algorithm: str | None = None


class IntegrityDetailResponse(BaseModel):
    success: bool = True
    data: IntegrityRecordResponse


class IntegrityVerifyResponse(BaseModel):
    success: bool = True
    data: IntegrityResultResponse


# ---------------------------------------------------------------------------
# Evidence / fact verification (Phase 11N)
# ---------------------------------------------------------------------------
# All response fields are bounded: claim/evidence text is excerpted by the
# engine and evidence lists are capped per claim. IDs (source/chunk) are UUIDs,
# never free text.

class FactVerificationEvidenceResponse(BaseModel):
    """One retrieved, provenance-carrying piece of evidence for a claim."""

    source_id: uuid.UUID
    chunk_id: uuid.UUID
    chunk_index: int
    evidence: str
    relevance_score: float | None = None
    overlap: float = 0.0
    numeric_conflict: bool = False
    date_conflict: bool = False


class FactVerificationClaimResponse(BaseModel):
    """One extracted claim and its deterministic verdict."""

    id: str
    text: str
    claim_type: str
    verdict: str
    reason: str
    overlap: float = 0.0
    evidence: list[FactVerificationEvidenceResponse] = Field(default_factory=list)


class FactVerificationResultResponse(BaseModel):
    """A persisted Phase 11N fact-verification report."""

    report_id: uuid.UUID
    output_id: uuid.UUID
    overall_status: str
    summary: str
    claims_checked: int
    claims_supported: int
    claims_contradicted: int
    claims_unverified: int
    claims: list[FactVerificationClaimResponse] = Field(default_factory=list)


class FactVerificationResponse(BaseModel):
    success: bool = True
    data: FactVerificationResultResponse


# ---------------------------------------------------------------------------
# Trust status + cross-output consistency (Phase 12B)
# ---------------------------------------------------------------------------

class TrustSignalResponse(BaseModel):
    """A single trust-signal category assessment."""

    category: str
    present: bool
    status: str  # "positive" | "warning" | "failure" | "missing"
    reason_code: str
    detail: str


class TrustStatusResponse(BaseModel):
    """Per-output trust status derived from existing verification signals."""

    status: str  # TRUSTED | CAUTION | UNVERIFIED
    reason_codes: list[str] = Field(default_factory=list)
    signals: list[TrustSignalResponse] = Field(default_factory=list)
    output_id: str
    output_type: str


class ConsistencyConflictResponse(BaseModel):
    """A detected factual conflict between two outputs."""

    category: str
    value_a: str
    value_b: str
    output_a_id: str
    output_a_type: str
    output_b_id: str
    output_b_type: str
    message: str


class CrossOutputConsistencyResponse(BaseModel):
    """Cross-output consistency status for a transformation job."""

    status: str  # CONSISTENT | INCONSISTENT | NOT_APPLICABLE
    completed_output_count: int
    conflicts: list[ConsistencyConflictResponse] = Field(default_factory=list)
    checked_pairs: int
    note: str


class ConsistencyResultResponse(BaseModel):
    """Combined trust status + cross-output consistency for a job."""

    job_id: uuid.UUID
    trust_statuses: list[TrustStatusResponse] = Field(default_factory=list)
    cross_output: CrossOutputConsistencyResponse


class ConsistencyResponse(BaseModel):
    success: bool = True
    data: ConsistencyResultResponse


# ---------------------------------------------------------------------------
# Dissemination Control schemas (Phase 2D)
# ---------------------------------------------------------------------------

class DisseminateRequest(BaseModel):
    """Request payload for attempting dissemination of an output."""

    destination: str = Field(
        ...,
        description="Target destination (e.g. 'INTERNAL', 'DOWNLOAD', 'LINKEDIN', 'X', 'PUBLIC_WEB').",
    )


class DisseminationDecisionResponse(BaseModel):
    """Deterministic dissemination decision outcome."""

    allowed: bool
    decision: str  # ALLOW | BLOCK | REVIEW
    classification: str
    destination: str
    reason: str
    policy_id: str = "karyasetu-dissemination-v1"
    artifact_hash: str | None = None
    signature: str | None = None
    provenance_id: str | None = None
    approval_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DisseminateResponse(BaseModel):
    """Authoritative server response for a dissemination attempt."""

    success: bool = True
    data: DisseminationDecisionResponse


class DisseminationReportResponse(BaseModel):
    """Comprehensive dissemination policy report for an output across destinations."""

    success: bool = True
    output_id: uuid.UUID
    output_type: str
    classification: str
    destinations: dict[str, DisseminationDecisionResponse]


class DisseminationEvaluateRequest(BaseModel):
    """Request to evaluate dissemination policy without an existing output."""

    classification: str = Field(..., description="Information classification label.")
    destination: str = Field(..., description="Target dissemination destination.")
    output_type: str | None = Field(default=None, description="Optional output type context.")


# ---------------------------------------------------------------------------
# Evidence & Provenance schemas (Phase 2E)
# ---------------------------------------------------------------------------

class ProvenanceDetailResponse(BaseModel):
    """Authoritative provenance record response for an output."""

    success: bool = True
    output_id: uuid.UUID
    data: dict[str, Any]


# ---------------------------------------------------------------------------
# Human Approval & Controlled Release schemas (Phase 2F)
# ---------------------------------------------------------------------------

class ApprovalActionRequest(BaseModel):
    """Operator action to approve or reject output dissemination to a destination."""

    destination: str = Field(..., description="Target DisseminationDestination (e.g. DOWNLOAD, LINKEDIN).")
    action: Literal["approve", "reject"] = Field(..., description="Action: 'approve' or 'reject'.")
    comments: str | None = Field(default=None, max_length=1000, description="Optional reviewer remarks.")
    rejection_reason: str | None = Field(default=None, max_length=1000, description="Mandatory justification if action is 'reject'.")

    model_config = ConfigDict(extra="forbid")


class DestinationApprovalDetail(BaseModel):
    """Destination-scoped approval state detail."""

    destination: str
    approval_status: str  # HARD_BLOCKED | NOT_REQUIRED | PENDING_APPROVAL | APPROVED | REJECTED | REVOKED
    approval_id: str | None = None
    decision: str | None = None
    approver_id: str | None = None
    approver_email: str | None = None
    approver_role: str | None = None
    approved_at: str | None = None
    rejection_reason: str | None = None
    comments: str | None = None
    self_approved: bool = False
    policy_reason: str | None = None
    classification_snapshot: str | None = None
    verification_status_snapshot: str | None = None


class ApprovalStatusResponse(BaseModel):
    """Aggregated approval report for an output across destinations."""

    success: bool = True
    output_id: uuid.UUID
    classification: str
    destinations: dict[str, DestinationApprovalDetail]
    latest_approval_id: str | None = None


class ApprovalActionResponse(BaseModel):
    """Response returned upon submitting an approval or rejection action."""

    success: bool = True
    data: DestinationApprovalDetail


# ---------------------------------------------------------------------------
# Cryptographic Integrity schemas (Phase 2G)
# ---------------------------------------------------------------------------

class OutputIntegrityDetail(BaseModel):
    """Authoritative cryptographic integrity status and digests for an output artifact."""

    status: str = Field(..., description="Integrity status ('VERIFIED', 'INVALID', 'UNAVAILABLE').")
    algorithm: str = Field(default="sha256", description="Hash algorithm used ('sha256').")
    artifact_hash: str | None = Field(default=None, description="Primary artifact SHA-256 digest.")
    companion_hashes: dict[str, str] = Field(default_factory=dict, description="Named companion artifact digests.")
    provenance_id: str | None = Field(default=None, description="Canonical provenance record identifier.")
    provenance_hash: str | None = Field(default=None, description="Deterministic canonical provenance projection digest.")
    approval_id: str | None = Field(default=None, description="Latest approval identifier snapshot bound at sealing.")
    recorded_at: str | None = Field(default=None, description="ISO timestamp when integrity was sealed.")
    details: dict[str, Any] = Field(default_factory=dict, description="Verification details and comparison results.")


class OutputIntegrityResponse(BaseModel):
    """Response model for GET /api/v1/outputs/{output_id}/integrity."""

    success: bool = True
    output_id: uuid.UUID
    data: OutputIntegrityDetail


class IntegrityVerifyResponse(BaseModel):
    """Response model for POST /api/v1/outputs/{output_id}/integrity/verify."""

    success: bool = True
    output_id: uuid.UUID
    data: OutputIntegrityDetail


# ---------------------------------------------------------------------------
# Digital Signature schemas (Phase 2H)
# ---------------------------------------------------------------------------

class OutputSignatureDetail(BaseModel):
    """Authoritative digital signature status and verification metadata for an output artifact."""

    status: str = Field(..., description="Signature status ('VALID', 'INVALID', 'UNAVAILABLE').")
    algorithm: str | None = Field(default=None, description="Signing algorithm ('ed25519', 'fake-sig-v1', 'hmac-sha256').")
    key_id: str | None = Field(default=None, description="Public key or key reference identifier.")
    signature: str | None = Field(default=None, description="Cryptographic signature string.")
    signed_payload_hash: str | None = Field(default=None, description="SHA-256 digest of the canonical signed payload.")
    signed_integrity_hash: str | None = Field(default=None, description="Primary artifact hash bound into signature.")
    signed_provenance_hash: str | None = Field(default=None, description="Provenance hash bound into signature.")
    signed_at: str | None = Field(default=None, description="ISO timestamp when signature was recorded.")
    provider: str | None = Field(default=None, description="Signer provider category or name.")
    details: dict[str, Any] = Field(default_factory=dict, description="Verification details and diagnostics.")


class OutputSignatureResponse(BaseModel):
    """Response model for GET /api/v1/outputs/{output_id}/signature."""

    success: bool = True
    output_id: uuid.UUID
    data: OutputSignatureDetail


class SignatureVerifyResponse(BaseModel):
    """Response model for POST /api/v1/outputs/{output_id}/signature/verify."""

    success: bool = True
    output_id: uuid.UUID
    data: OutputSignatureDetail
