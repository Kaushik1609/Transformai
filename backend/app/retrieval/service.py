from __future__ import annotations

import hashlib
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
from app.retrieval.sql import (
    is_postgresql,
    scoped_hybrid_candidate_query,
    scoped_vector_ranking_query,
)


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

    def _ensure_scope(
        self,
        *,
        project_id: UUID | None,
        source_id: UUID | None,
        require_scope: bool,
    ) -> None:
        """Fail closed when strict scoping is requested but no scope is supplied.

        An unscoped retrieval would search every embedded chunk in the database —
        a cross-project data exposure. Production callers (the transformation
        graph) always pass project_id and source_id; this guard makes accidental
        unscoped/global queries impossible for callers that opt in.
        """
        if not require_scope:
            return
        if project_id is None and source_id is None:
            raise ValueError(
                "Retrieval scope required: pass project_id and/or source_id; "
                "refusing an unscoped (global) retrieval."
            )

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
        source_id: UUID | None = None,
        min_similarity: float | None = None,
        require_scope: bool = False,
    ) -> list[ChunkMatch]:
        self._ensure_scope(
            project_id=project_id, source_id=source_id, require_scope=require_scope
        )
        validated_vector = self._validate_query_vector(query_vector)
        validated_top_k = self._validate_top_k(top_k)

        if is_postgresql(db):
            # Phase 11J-C: exact pgvector pushdown. Scope/threshold/top_k are
            # enforced in SQL; distance and score semantics match the Python
            # reference implementation below (1 - cosine, clamped at zero).
            rows = db.execute(
                scoped_vector_ranking_query(
                    query_vector=validated_vector,
                    dimensions=self.dimensions,
                    top_k=validated_top_k,
                    project_id=project_id,
                    source_id=source_id,
                    min_similarity=min_similarity,
                )
            ).mappings()
            matches: list[ChunkMatch] = []
            for row in rows:
                distance = float(row["distance"])
                score = 1.0 - distance if distance <= 1.0 else 0.0
                if min_similarity is not None and score < min_similarity:
                    continue
                matches.append(
                    ChunkMatch(
                        source_id=row["source_id"],
                        chunk_id=row["id"],
                        chunk_index=row["chunk_index"],
                        content=row["content"],
                        distance=distance,
                        score=score,
                    )
                )
            return matches

        candidate_query = select(SourceChunk).where(SourceChunk.embedding.is_not(None))

        if source_id is not None:
            candidate_query = candidate_query.where(SourceChunk.source_id == source_id)

        if project_id is not None:
            candidate_query = candidate_query.join(
                Source, SourceChunk.source_id == Source.id
            ).where(Source.project_id == project_id)

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
        for distance, row in scored:
            score = 1.0 - float(distance) if float(distance) <= 1.0 else 0.0
            if min_similarity is not None and score < min_similarity:
                continue
            matches.append(
                ChunkMatch(
                    source_id=row.source_id,
                    chunk_id=row.id,
                    chunk_index=row.chunk_index,
                    content=row.content,
                    distance=float(distance),
                    score=score,
                )
            )
            if len(matches) >= validated_top_k:
                break
        return matches

    def query_by_text(
        self,
        db: Session,
        text: str,
        *,
        top_k: int = 5,
        project_id: UUID | None = None,
        source_id: UUID | None = None,
        min_similarity: float | None = None,
        require_scope: bool = False,
    ) -> list[ChunkMatch]:
        cleaned = self._validate_query_text(text)
        validated_top_k = self._validate_top_k(top_k)
        vector = self.embedding_service.embed_texts([cleaned])[0]
        return self.query_by_vector(
            db,
            vector,
            top_k=validated_top_k,
            project_id=project_id,
            source_id=source_id,
            min_similarity=min_similarity,
            require_scope=require_scope,
        )

    # ---------------------------------------------------------------------
    # Phase 11B — Lightweight hybrid retrieval (dense + lexical fusion)
    # ---------------------------------------------------------------------
    # This is NOT a full BM25 implementation. It blends the existing dense
    # vector similarity with a lightweight token-overlap lexical signal and
    # fuses them deterministically. Project/source isolation is still enforced
    # at the SQL query level. A full BM25 index / external reranker remains
    # deferred; this abstraction is intentionally small and extensible.

    DENSE_WEIGHT: float = 0.65
    LEXICAL_WEIGHT: float = 0.35

    def _scoped_candidate_query(
        self, *, project_id: UUID | None, source_id: UUID | None
    ):
        """Build a SQL-level scoped candidate query over embedded chunks."""
        candidate_query = select(SourceChunk).where(SourceChunk.embedding.is_not(None))
        if source_id is not None:
            candidate_query = candidate_query.where(SourceChunk.source_id == source_id)
        if project_id is not None:
            candidate_query = candidate_query.join(
                Source, SourceChunk.source_id == Source.id
            ).where(Source.project_id == project_id)
        return candidate_query

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Lower-cased word tokens for lexical overlap (no stemming)."""
        return {tok for tok in text.lower().split() if tok}

    @classmethod
    def _lexical_overlap(cls, query_tokens: set[str], chunk_tokens: set[str]) -> float:
        """Jaccard-style token overlap in [0, 1] between query and chunk."""
        union = query_tokens | chunk_tokens
        if not union:
            return 0.0
        return len(query_tokens & chunk_tokens) / len(union)

    def query_hybrid(
        self,
        db: Session,
        text: str,
        *,
        top_k: int = 5,
        project_id: UUID | None = None,
        source_id: UUID | None = None,
        min_similarity: float | None = None,
        require_scope: bool = False,
    ) -> list[ChunkMatch]:
        """Rank chunks by a deterministic fuse of dense + lexical similarity.

        Candidate filtering happens entirely in SQL (project/source scope). Each
        candidate receives a normalized dense score and a lightweight lexical
        token-overlap score, fused into ``final_score``. The dense score is what
        the caller's ``min_similarity`` bar is applied to. Duplicate chunk
        content is folded, provenance is preserved, and output is capped at
        ``top_k``.
        """
        self._ensure_scope(
            project_id=project_id, source_id=source_id, require_scope=require_scope
        )
        cleaned = self._validate_query_text(text)
        validated_top_k = self._validate_top_k(top_k)
        query_vector = self.embedding_service.embed_texts([cleaned])[0]
        query_tokens = self._tokenize(cleaned)

        if is_postgresql(db):
            # Phase 11J-C: dense distance is computed by PostgreSQL over the
            # full SQL-scoped candidate set; the lexical fusion, weighting,
            # deduplication, ordering and thresholds below are byte-for-byte
            # the reference behavior.
            rows = db.execute(
                scoped_hybrid_candidate_query(
                    query_vector=query_vector,
                    dimensions=self.dimensions,
                    project_id=project_id,
                    source_id=source_id,
                )
            ).mappings()
            candidates: list[tuple[UUID, UUID, int, str, float]] = [
                (
                    row["id"],
                    row["source_id"],
                    row["chunk_index"],
                    row["content"],
                    float(row["distance"]),
                )
                for row in rows
            ]
        else:
            rows = db.execute(
                self._scoped_candidate_query(project_id=project_id, source_id=source_id)
            ).scalars()
            candidates = []
            for row in rows:
                try:
                    row_vector = self._coerce_embedding_vector(row.embedding)
                except ValueError:
                    continue
                candidates.append(
                    (
                        row.id,
                        row.source_id,
                        row.chunk_index,
                        row.content,
                        float(self._cosine_distance(query_vector, row_vector)),
                    )
                )

        return self._fuse_hybrid(
            candidates,
            query_tokens=query_tokens,
            min_similarity=min_similarity,
            top_k=validated_top_k,
        )

    @classmethod
    def _fuse_hybrid(
        cls,
        candidates: Sequence[tuple[UUID, UUID, int, str, float]],
        *,
        query_tokens: set[str],
        min_similarity: float | None,
        top_k: int,
    ) -> list[ChunkMatch]:
        """Dense + lexical fusion over the SQL-scoped candidate set.

        Candidate tuples are ``(chunk_id, source_id, chunk_index, content,
        dense_distance)`` where ``dense_distance`` comes from PostgreSQL on the
        vector path or from the Python ``_cosine_distance`` reference on the
        fallback path. Ranking is identical to the reference hybrid
        implementation: dense threshold first, then weighted fusion:
        ``final = DENSE_WEIGHT * dense_score + LEXICAL_WEIGHT * lexical_score``,
        duplicate content folded (strongest occurrence kept), ordered by fused
        score desc with ``chunk_index`` asc as the deterministic tie-break, and
        capped at ``top_k``.
        """
        scored: list[tuple[float, int, UUID, UUID, str, float]] = []
        for chunk_id, source_id, chunk_index, content, distance in candidates:
            dense_score = 1.0 - float(distance) if float(distance) <= 1.0 else 0.0
            if min_similarity is not None and dense_score < min_similarity:
                continue
            lexical_score = cls._lexical_overlap(query_tokens, cls._tokenize(content))
            final_score = (cls.DENSE_WEIGHT * dense_score) + (
                cls.LEXICAL_WEIGHT * lexical_score
            )
            scored.append((final_score, chunk_index, chunk_id, source_id, content, dense_score))

        # Deterministic: fused score desc, then earliest chunk first.
        scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)

        matches: list[ChunkMatch] = []
        seen_hashes: set[str] = set()
        for final_score, chunk_index, chunk_id, source_id, content, dense_score in scored:
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            matches.append(
                ChunkMatch(
                    source_id=source_id,
                    chunk_id=chunk_id,
                    chunk_index=chunk_index,
                    content=content,
                    distance=1.0 - dense_score,
                    score=final_score,
                )
            )
            if len(matches) >= top_k:
                break
        return matches
