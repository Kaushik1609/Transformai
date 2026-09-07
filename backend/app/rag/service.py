"""Phase 5 RAG service + Phase 11 A/B hardening: bounded, deduplicated context."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.metrics import metrics
from app.rag.schemas import RAGContext, RAGCitation
from app.retrieval.service import RetrievalService, ChunkMatch


class RAGService:
    """
    Retrieval-Augmented Generation service.

    Wraps Phase 3F RetrievalService to assemble retrieved chunks into
    LLM-ready context with full source traceability.

    Phase 11A hardening:
      * SQL-level project/source isolation (delegated to RetrievalService).
      * Configurable defaults (RAG_TOP_K / RAG_MIN_SIMILARITY /
        RAG_MAX_CONTEXT_CHARS) applied when the caller does not override them.
      * Context length is bounded; strongest evidence is kept first and
        truncation is surfaced in metadata (never silent, never unbounded).
      * Duplicate chunks are removed, preserving the strongest evidence.
      * Empty retrieval is a distinct, observable state ("insufficient
        context") — never fabricated.
    """

    # Sentinel for "no evidence passed the similarity threshold".
    NO_CONTEXT = "(no relevant context retrieved)"

    def __init__(self, retrieval_service: RetrievalService | None = None):
        """Initialize with an optional custom RetrievalService."""
        self.retrieval = retrieval_service or RetrievalService()
        self.default_top_k = settings.RAG_TOP_K
        # 0.0 preserves legacy behavior (no filtering); values in (0, 1]
        # raise the bar for what counts as relevant.
        self.min_similarity_default = settings.RAG_MIN_SIMILARITY
        self.max_context_chars = settings.RAG_MAX_CONTEXT_CHARS

    def retrieve_context(
        self,
        db: Session,
        query: str,
        *,
        project_id: UUID | None = None,
        source_id: UUID | None = None,
        top_k: int | None = None,
        task_context: str | None = None,
        min_similarity: float | None = None,
    ) -> RAGContext:
        """
        Retrieve and assemble context for a generation task.

        Args:
            db: SQLAlchemy session
            query: Query text to retrieve relevant chunks for
            project_id: Optional project filter
            source_id: Optional source filter
            top_k: Number of chunks to retrieve (default from RAG_TOP_K)
            task_context: Optional metadata (audience, tone, detail level, etc.)
            min_similarity: Optional minimum similarity score threshold
                (default from RAG_MIN_SIMILARITY)

        Returns:
            RAGContext with assembled text and citations
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")

        resolved_top_k = self._resolve_top_k(top_k)
        resolved_min = self._resolve_min_similarity(min_similarity)

        started = time.monotonic()
        try:
            matches = self.retrieval.query_by_text(
                db,
                query,
                top_k=resolved_top_k,
                project_id=project_id,
                source_id=source_id,
                min_similarity=resolved_min,
            )
        except Exception:
            metrics.inc("rag_retrieval_failures_total")
            raise
        metrics.inc("rag_retrievals_total")
        metrics.observe(
            "rag_retrieval_duration_seconds", time.monotonic() - started
        )

        return self._assemble_context(
            matches=matches,
            query=query,
            task_context=task_context,
        )

    def retrieve_context_for_source(
        self,
        db: Session,
        source_id: UUID,
        query: str,
        *,
        project_id: UUID | None = None,
        top_k: int | None = None,
        task_context: str | None = None,
        min_similarity: float | None = None,
    ) -> RAGContext:
        """
        Retrieve context from one specific source only, with SQL-level project and source isolation.

        Args:
            db: SQLAlchemy session
            source_id: Source to restrict retrieval to
            query: Query text
            project_id: Optional project to enforce isolation
            top_k: Number of chunks to retrieve (default from RAG_TOP_K)
            task_context: Optional metadata
            min_similarity: Optional minimum similarity score threshold
                (default from RAG_MIN_SIMILARITY)

        Returns:
            RAGContext with citations only from the specified source
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")

        resolved_top_k = self._resolve_top_k(top_k)
        resolved_min = self._resolve_min_similarity(min_similarity)

        started = time.monotonic()
        try:
            matches = self.retrieval.query_by_text(
                db,
                query,
                top_k=resolved_top_k,
                project_id=project_id,
                source_id=source_id,
                min_similarity=resolved_min,
            )
        except Exception:
            metrics.inc("rag_retrieval_failures_total")
            raise
        metrics.inc("rag_retrievals_total")
        metrics.observe(
            "rag_retrieval_duration_seconds", time.monotonic() - started
        )

        return self._assemble_context(
            matches=matches,
            query=query,
            task_context=task_context,
        )

    def _resolve_top_k(self, top_k: int | None) -> int:
        """Resolve the effective top_k using config default when not supplied."""
        if top_k is None:
            return self.default_top_k
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
            raise ValueError("top_k must be a positive integer.")
        return top_k

    def _resolve_min_similarity(self, min_similarity: float | None) -> float:
        """Resolve the effective similarity threshold using config default."""
        if min_similarity is None:
            return self.min_similarity_default
        value = float(min_similarity)
        if value < 0.0 or value > 1.0:
            raise ValueError("min_similarity must be between 0.0 and 1.0.")
        return value

    def _assemble_context(
        self,
        matches: list[ChunkMatch],
        query: str,
        task_context: str | None = None,
    ) -> RAGContext:
        """Transform raw chunk matches into bounded, deduplicated LLM context.

        Ordering is deterministic (by relevance desc, then chunk_index asc) so
        the strongest evidence appears first. Duplicate chunk content is folded
        into a single occurrence, retaining the strongest/highest-scoring hit.
        The assembled text is capped at ``RAG_MAX_CONTEXT_CHARS``; truncation
        and empty/insufficient states are surfaced in ``metadata`` so raw
        retrieval failures are never mistaken for successful empty retrieval.
        """
        if not matches:
            return RAGContext(
                query=query,
                assembled_text=self.NO_CONTEXT,
                citations=[],
                chunk_count=0,
                task_context=task_context,
                metadata={
                    "retrieval_method": "cosine-similarity-pgvector",
                    "retrieval_status": "insufficient_context",
                },
                retrieved_at=datetime.now(),
            )

        # Deterministic ordering: strongest relevance first, ties by chunk order.
        ordered = sorted(
            matches,
            key=lambda m: (m.score if m.score is not None else 0.0, -m.chunk_index),
            reverse=True,
        )

        # Deduplicate identical content, keeping the strongest occurrence.
        deduped: list[ChunkMatch] = []
        seen_hashes: set[str] = set()
        for match in ordered:
            digest = hashlib.sha256(match.content.encode("utf-8")).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            deduped.append(match)

        citations = [
            RAGCitation(
                source_id=str(match.source_id),
                chunk_id=str(match.chunk_id),
                chunk_index=match.chunk_index,
                evidence=match.content,
                relevance_score=match.score,
            )
            for match in deduped
        ]

        # Bounded assembly, preserving the highest-relevance (front) chunks.
        fragments: list[str] = []
        used_chars = 0
        limit = self.max_context_chars
        truncated = False
        for match in deduped:
            fragment = f"[Chunk {match.chunk_index}]\n{match.content}"
            if used_chars + len(fragment) > limit:
                truncated = True
                break
            fragments.append(fragment)
            used_chars += len(fragment)

        if not fragments:
            # First (strongest) chunk alone exceeds the limit; keep it truncated.
            first = deduped[0]
            assembled_text = f"[Chunk {first.chunk_index}]\n{first.content}"[:limit]
            truncated = True
            if not assembled_text:
                assembled_text = self.NO_CONTEXT
        else:
            assembled_text = "\n\n".join(fragments)

        metadata = {
            "retrieval_method": "cosine-similarity-pgvector",
            "retrieval_status": "has_evidence" if assembled_text != self.NO_CONTEXT else "insufficient_context",
            "retrieved_count": len(matches),
            "deduplicated_count": len(matches) - len(deduped),
            "truncated": truncated,
            "max_context_chars": limit,
        }

        return RAGContext(
            query=query,
            assembled_text=assembled_text,
            citations=citations,
            chunk_count=len(deduped),
            task_context=task_context,
            metadata=metadata,
            retrieved_at=datetime.now(),
        )
