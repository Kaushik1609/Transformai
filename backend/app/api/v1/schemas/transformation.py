"""
TransformIQ Backend — Transformation Job, Output, VerificationResult Schemas

Request and response schemas for transformation jobs.
Phase 2: persistence model only. No actual job enqueueing.
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
        description="List of output types: summary | linkedin | x | advisory | infographic | presentation | video",
    )


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
