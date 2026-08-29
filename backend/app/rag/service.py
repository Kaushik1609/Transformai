"""Phase 5 RAG service: context assembly and source grounding."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.rag.schemas import RAGContext, RAGCitation
from app.retrieval.service import RetrievalService, ChunkMatch


class RAGService:
    """
    Retrieval-Augmented Generation service.

    Wraps Phase 3F RetrievalService to assemble retrieved chunks into
    LLM-ready context with full source traceability.
    """

    def __init__(self, retrieval_service: RetrievalService | None = None):
        """Initialize with an optional custom RetrievalService."""
        self.retrieval = retrieval_service or RetrievalService()

    def retrieve_context(
        self,
        db: Session,
        query: str,
        *,
        project_id: UUID | None = None,
        top_k: int = 5,
        task_context: str | None = None,
    ) -> RAGContext:
        """
        Retrieve and assemble context for a generation task.

        Args:
            db: SQLAlchemy session
            query: Query text to retrieve relevant chunks for
            project_id: Optional project filter
            top_k: Number of chunks to retrieve (default 5)
            task_context: Optional metadata (audience, tone, detail level, etc.)

        Returns:
            RAGContext with assembled text and citations
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer.")

        matches = self.retrieval.query_by_text(
            db, query, top_k=top_k, project_id=project_id
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
        top_k: int = 5,
        task_context: str | None = None,
    ) -> RAGContext:
        """
        Retrieve context from one specific source only.

        Args:
            db: SQLAlchemy session
            source_id: Source to restrict retrieval to
            query: Query text
            top_k: Number of chunks to retrieve
            task_context: Optional metadata

        Returns:
            RAGContext with citations only from the specified source
        """
        from app.db.models.source_chunk import SourceChunk

        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer.")

        matches = self.retrieval.query_by_text(db, query, top_k=top_k)
        filtered = [m for m in matches if m.source_id == source_id]

        return self._assemble_context(
            matches=filtered,
            query=query,
            task_context=task_context,
        )

    def _assemble_context(
        self,
        matches: list[ChunkMatch],
        query: str,
        task_context: str | None = None,
    ) -> RAGContext:
        """Transform raw chunk matches into LLM-ready context."""
        citations = [
            RAGCitation(
                source_id=str(match.source_id),
                chunk_id=str(match.chunk_id),
                chunk_index=match.chunk_index,
                evidence=match.content,
                relevance_score=match.score,
            )
            for match in matches
        ]

        assembled_text = "\n\n".join(
            [f"[Chunk {match.chunk_index}]\n{match.content}" for match in matches]
        )

        return RAGContext(
            query=query,
            assembled_text=assembled_text if matches else "(no relevant context retrieved)",
            citations=citations,
            chunk_count=len(matches),
            task_context=task_context,
            metadata={"retrieval_method": "cosine-similarity-pgvector"},
            retrieved_at=datetime.now(),
        )
