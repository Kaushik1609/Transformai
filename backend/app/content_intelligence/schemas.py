"""Validated contracts for Phase 4 canonical content."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GroundedItem(BaseModel):
    """An extracted item with mandatory source-chunk provenance."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    source_chunk_ids: list[uuid.UUID] = Field(min_length=1)
    chunk_index: int | None = Field(default=None, ge=0)
    evidence: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class TopicItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1)
    source_chunk_ids: list[uuid.UUID] = Field(min_length=1)
    category: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class EntityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    source_chunk_ids: list[uuid.UUID] = Field(min_length=1)
    normalized_name: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class StatisticItem(GroundedItem):
    value: str | None = None
    unit: str | None = None
    label: str | None = None


class DateItem(GroundedItem):
    iso_date: str | None = None
    date_type: str | None = None


class CanonicalContentPayload(BaseModel):
    """Provider output accepted for persistence."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    topics: list[TopicItem] = Field(default_factory=list)
    entities: list[EntityItem] = Field(default_factory=list)
    key_points: list[GroundedItem] = Field(default_factory=list)
    claims: list[GroundedItem] = Field(default_factory=list)
    statistics: list[StatisticItem] = Field(default_factory=list)
    dates: list[DateItem] = Field(default_factory=list)
    recommendations: list[GroundedItem] = Field(default_factory=list)
    source_references: list[GroundedItem] = Field(default_factory=list)

    @field_validator("title", "summary")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class CanonicalContentResponse(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    title: str | None
    summary: str | None
    metadata: dict[str, Any]
    topics: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    key_points: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    statistics: list[dict[str, Any]]
    dates: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    source_references: list[dict[str, Any]]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    analyzed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ContentIntelligenceResponse(BaseModel):
    success: bool = True
    data: CanonicalContentResponse
