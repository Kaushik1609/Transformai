from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.embeddings.service import EmbeddingService


@dataclass(frozen=True)
class ChunkMatch:
    source_id: UUID
    chunk_id: UUID
    chunk_index: int
    content: str
    distance: float
    score: float | None = None


class RetrievalService:
    """Read-only retrieval that ranks stored chunk embeddings by cosine distance."""

    def __init__(self, *, embedding_service: EmbeddingService | None = None, dimensions: int | None = None):
        self.dimensions = dimensions if dimensions is not None else settings.EMBEDDING_DIMENSIONS
        self.embedding_service = embedding_service or EmbeddingService(dimensions=self.dimensions)

    def _validate_top_k(self, top_k: int) -> int:
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer.")
        return top_k

    def _validate_query_vector(self, query_vector: Sequence[float]) -> list[float]:
        if not isinstance(query_vector, (list, tuple)) or not query_vector:
            raise ValueError("Query vector must be a non-empty list or tuple of floats.")
        vector = [float(value) for value in query_vector]
        if len(vector) != self.dimensions:
            raise ValueError(f"Query vector dimensions mismatch: expected {self.dimensions}, got {len(vector)}.")
        return vector

    def _validate_query_text(self, text: str) -> str:
        if not isinstance(text, str):
            raise ValueError("Query text must be a string.")
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Query text cannot be empty.")
        return cleaned

    def _apply_project_filter(self, query, *, project_id: UUID | None):
        if project_id is None:
            return query
        return query.join(SourceChunk.source).where(SourceChunk.source.has(project_id=project_id))

    def _coerce_embedding_vector(self, value) -> list[float]:
        if value is None:
            raise ValueError("Stored embedding is missing.")
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned.startswith("[") and cleaned.endswith("]"):
                inner = cleaned[1:-1].strip()
                if not inner:
                    return []
                return [float(part.strip()) for part in inner.split(",") if part.strip()]
            cleaned = cleaned.replace("(", "").replace(")", "")
            if cleaned:
                return [float(part.strip()) for part in cleaned.split(",") if part.strip()]
            return []
        if isinstance(value, (list, tuple)):
            return [float(part) for part in value]
        if hasattr(value, "tolist"):
            return [float(part) for part in value.tolist()]
        raise ValueError("Stored embedding is not a numeric vector.")

    def _cosine_distance(self, left: Sequence[float], right: Sequence[float]) -> float:
        left_vector = [float(value) for value in left]
        right_vector = [float(value) for value in right]
        if len(left_vector) != len(right_vector):
            raise ValueError("Vector dimension mismatch during similarity check.")
        if not left_vector or not right_vector:
            return 1.0
        dot_product = sum(a * b for a, b in zip(left_vector, right_vector))
        left_norm = math.sqrt(sum(a * a for a in left_vector))
        right_norm = math.sqrt(sum(b * b for b in right_vector))
        if left_norm == 0.0 or right_norm == 0.0:
            return 1.0
        similarity = dot_product / (left_norm * right_norm)
        similarity = max(-1.0, min(1.0, float(similarity)))
        return 1.0 - similarity

    def query_by_vector(
        self,
        db: Session,
        query_vector: Sequence[float],
        *,
        top_k: int = 5,
        project_id: UUID | None = None,
    ) -> list[ChunkMatch]:
        validated_vector = self._validate_query_vector(query_vector)
        validated_top_k = self._validate_top_k(top_k)

        candidate_query = select(SourceChunk).where(SourceChunk.embedding.is_not(None))
        if project_id is not None:
            project_source_ids = db.execute(
                select(Source.id).where(Source.project_id == project_id)
            ).scalars().all()
            if not project_source_ids:
                return []
            candidate_query = candidate_query.where(SourceChunk.source_id.in_(project_source_ids))

        rows = db.execute(candidate_query).scalars().all()
        scored: list[tuple[float, SourceChunk]] = []
        for row in rows:
            try:
                row_vector = self._coerce_embedding_vector(row.embedding)
            except ValueError:
                continue
            distance = self._cosine_distance(validated_vector, row_vector)
            scored.append((distance, row))

        scored.sort(key=lambda item: item[0])
        matches: list[ChunkMatch] = []
        for distance, row in scored[:validated_top_k]:
            matches.append(
                ChunkMatch(
                    source_id=row.source_id,
                    chunk_id=row.id,
                    chunk_index=row.chunk_index,
                    content=row.content,
                    distance=float(distance),
                    score=1.0 - float(distance) if float(distance) <= 1.0 else 0.0,
                )
            )
        return matches

    def query_by_text(
        self,
        db: Session,
        text: str,
        *,
        top_k: int = 5,
        project_id: UUID | None = None,
    ) -> list[ChunkMatch]:
        cleaned = self._validate_query_text(text)
        validated_top_k = self._validate_top_k(top_k)
        vector = self.embedding_service.embed_texts([cleaned])[0]
        return self.query_by_vector(db, vector, top_k=validated_top_k, project_id=project_id)
