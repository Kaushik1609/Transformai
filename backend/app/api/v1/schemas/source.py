"""
TransformIQ Backend — Source Pydantic Schemas

Request and response schemas for the source metadata API.
File extraction is NOT implemented here — that is Phase 3.
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class SourceCreate(BaseModel):
    """
    Body for POST /api/v1/projects/{project_id}/sources

    For Phase 2, only direct text and metadata records are supported.
    File upload support is added in Phase 3.
    """

    source_type: str = Field(
        default="text",
        description="Source type: text | pdf | docx | image | video | url",
    )
    original_filename: str | None = Field(
        default=None,
        max_length=512,
        description="Original filename (nullable for direct text input)",
    )
    extracted_text: str | None = Field(
        default=None,
        description="Direct text content (for source_type=text)",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="MIME type of the source file",
    )
    language: str = Field(
        default="en",
        max_length=10,
        description="ISO 639-1 language code",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Flexible metadata (page count, author, etc.)",
    )


class DirectTextSourceCreate(BaseModel):
    """Body for direct-text ingestion."""

    text: str = Field(..., min_length=1, description="Source text content")
    language: str = Field(default="en", max_length=10)
    metadata: dict[str, Any] | None = Field(default=None)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class SourceResponse(BaseModel):
    """Serialized source record returned by the API."""

    id: uuid.UUID
    project_id: uuid.UUID
    source_type: str
    original_filename: str | None
    storage_key: str | None
    mime_type: str | None
    file_size: int | None
    language: str
    status: str
    source_metadata: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SourceListResponse(BaseModel):
    """Paginated list of sources."""

    success: bool = True
    data: list[SourceResponse]
    count: int


class SourceDetailResponse(BaseModel):
    """Single source detail response."""

    success: bool = True
    data: SourceResponse


class DeleteResponse(BaseModel):
    """Acknowledgement for DELETE operations."""

    success: bool = True
    message: str
