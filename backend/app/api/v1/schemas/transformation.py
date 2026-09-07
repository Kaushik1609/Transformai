"""
TransformIQ Backend — Transformation Job, Output, VerificationResult Schemas

Request and response schemas for transformation jobs.
Phase 2: persistence model only. No actual job enqueueing.
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.transformation.generators import KNOWN_OUTPUT_TYPES


# ---------------------------------------------------------------------------
# Transformation Job schemas
# ---------------------------------------------------------------------------

class TransformationJobCreate(BaseModel):
    """
    Body for POST /api/v1/transformations

    Creates a transformation job record. Phase 6 will actually enqueue the job.
    """
    project_id: uuid.UUID = Field(..., description="Project UUID")
    source_id: uuid.UUID = Field(..., description="Source UUID")
    configuration_id: uuid.UUID = Field(..., description="Configuration UUID")
    output_types: list[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="List of output types: summary | linkedin | x | advisory | infographic | presentation | video",
    )

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


class TransformationJobResponse(BaseModel):
    """Serialized transformation job record."""

    id: uuid.UUID
    project_id: uuid.UUID
    source_id: uuid.UUID
    configuration_id: uuid.UUID
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
