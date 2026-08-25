"""
TransformIQ Backend — Generation Configuration Pydantic Schemas

Request and response schemas for the generation configuration API.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ConfigurationCreate(BaseModel):
    """Body for POST /api/v1/projects/{project_id}/configurations"""

    target_audience: str | None = Field(
        default=None,
        max_length=255,
        description="Intended audience (e.g. 'technology executives')",
    )
    tone: str | None = Field(
        default=None,
        max_length=100,
        description="Desired tone (e.g. 'professional', 'casual')",
    )
    language: str = Field(
        default="English",
        max_length=50,
        description="Output language",
    )
    detail_level: str | None = Field(
        default=None,
        max_length=50,
        description="concise | standard | detailed",
    )
    communication_objective: str | None = Field(
        default=None,
        max_length=255,
        description="What should the content achieve? (e.g. 'inform', 'persuade')",
    )
    content_style: str | None = Field(
        default=None,
        max_length=100,
        description="Content style (e.g. 'narrative', 'bullet-points')",
    )
    custom_instructions: str | None = Field(
        default=None,
        description="Free-form custom instructions for the AI",
    )


class ConfigurationUpdate(BaseModel):
    """Body for PATCH /api/v1/configurations/{configuration_id}"""

    target_audience: str | None = Field(default=None, max_length=255)
    tone: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, max_length=50)
    detail_level: str | None = Field(default=None, max_length=50)
    communication_objective: str | None = Field(default=None, max_length=255)
    content_style: str | None = Field(default=None, max_length=100)
    custom_instructions: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ConfigurationResponse(BaseModel):
    """Serialized configuration record returned by the API."""

    id: uuid.UUID
    project_id: uuid.UUID
    target_audience: str | None
    tone: str | None
    language: str
    detail_level: str | None
    communication_objective: str | None
    content_style: str | None
    custom_instructions: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConfigurationListResponse(BaseModel):
    """Paginated list of configurations."""

    success: bool = True
    data: list[ConfigurationResponse]
    count: int


class ConfigurationDetailResponse(BaseModel):
    """Single configuration detail response."""

    success: bool = True
    data: ConfigurationResponse


class DeleteResponse(BaseModel):
    """Acknowledgement for DELETE operations."""

    success: bool = True
    message: str
