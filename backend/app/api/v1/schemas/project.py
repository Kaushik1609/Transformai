"""
TransformIQ Backend — Project Pydantic Schemas

Request and response schemas for the project API.
These are separate from the ORM model and define the API contract.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    """Body for POST /api/v1/projects"""

    name: str = Field(..., min_length=1, max_length=255, description="Project name")
    description: str | None = Field(
        default=None,
        max_length=4096,
        description="Optional project description",
    )


class ProjectUpdate(BaseModel):
    """Body for PATCH /api/v1/projects/{project_id}"""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Updated project name",
    )
    description: str | None = Field(
        default=None,
        max_length=4096,
        description="Updated project description",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ProjectResponse(BaseModel):
    """Serialized project record returned by the API."""

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    """Paginated list of projects."""

    success: bool = True
    data: list[ProjectResponse]
    count: int


class ProjectDetailResponse(BaseModel):
    """Single project detail response."""

    success: bool = True
    data: ProjectResponse


class DeleteResponse(BaseModel):
    """Acknowledgement for DELETE operations."""

    success: bool = True
    message: str
