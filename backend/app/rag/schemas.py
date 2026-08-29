"""Schemas for Phase 5 RAG context assembly and citation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RAGCitation(BaseModel):
    """Citation metadata for a single retrieved chunk."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(description="UUID of the source")
    chunk_id: str = Field(description="UUID of the source chunk")
    chunk_index: int = Field(ge=0, description="Chunk order in the source")
    evidence: str = Field(min_length=1, description="The actual chunk content (evidence)")
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0, description="Cosine similarity score")


class RAGContext(BaseModel):
    """Assembled context ready for Phase 6 generation."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="The query used for retrieval")
    assembled_text: str = Field(description="Formatted concatenation of retrieved chunks")
    citations: list[RAGCitation] = Field(default_factory=list, description="Source citations for each chunk")
    chunk_count: int = Field(ge=0, description="Number of retrieved chunks")
    task_context: str | None = Field(default=None, description="Optional task context (audience, tone, etc.)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional retrieval metadata")
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(), description="Timestamp of retrieval")
