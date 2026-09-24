"""Shared synchronous source processing used by the RQ worker."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.audit import emit_security_event, flush_pending_audit_sync
from app.core.config import settings
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.embeddings.service import EmbeddingService
from app.ingestion.documents import DocumentExtractionError, extract_docx, extract_pdf
from app.ingestion.pii_scan import scan_source_pii
from app.ingestion.queue import enqueue_source_embedding, get_embedding_queue
from app.ingestion.text import chunk_text, chunk_text_with_metadata, normalize_text
from app.ingestion.storage import get_storage


def process_source_with_session(db: Session, source_id: uuid.UUID) -> Source:
    """Process one stored source and transition it to ready or failed."""
    source = db.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
    if source is None:
        raise ValueError(f"Source {source_id} was not found.")

    try:
        if not source.storage_key:
            raise ValueError("Source has no stored original file.")
        content = get_storage().read(source.storage_key)
        if source.source_type in {"text", "txt"}:
            extracted = content.decode("utf-8")
        elif source.source_type == "pdf":
            extracted = extract_pdf(content)
        elif source.source_type == "docx":
            extracted = extract_docx(content)
        else:
            raise ValueError(f"Unsupported source type: {source.source_type!r}.")

        normalized = normalize_text(extracted)
        if not normalized:
            raise ValueError("Source contains no usable text.")
        if len(normalized) > settings.MAX_EXTRACTED_CHARS:
            raise ValueError(
                "Source text exceeds the configured extraction limit "
                f"of {settings.MAX_EXTRACTED_CHARS} characters."
            )

        pii_scan = scan_source_pii(normalized)

        db.execute(delete(SourceChunk).where(SourceChunk.source_id == source.id))
        chunks_info = chunk_text_with_metadata(normalized)
        if len(chunks_info) > settings.MAX_SOURCE_CHUNKS:
            raise ValueError(
                "Source chunk count exceeds the configured limit "
                f"of {settings.MAX_SOURCE_CHUNKS} chunks."
            )
        for chunk_index, chunk_info in enumerate(chunks_info):
            content_chunk = chunk_info["content"]
            chunk_hash = hashlib.sha256(content_chunk.encode("utf-8")).hexdigest()[:16]
            chunk_meta = {
                "source_id": str(source.id),
                "chunk_index": chunk_index,
                "char_start": chunk_info.get("char_start", 0),
                "char_end": chunk_info.get("char_end", len(content_chunk)),
                "char_count": len(content_chunk),
                "content_hash": chunk_hash,
                "token_estimate": max(1, len(content_chunk.split())),
            }
            db.add(
                SourceChunk(
                    id=uuid.uuid4(),
                    source_id=source.id,
                    chunk_index=chunk_index,
                    content=content_chunk,
                    embedding=None,
                    chunk_metadata=chunk_meta,
                    created_at=datetime.now(timezone.utc),
                )
            )
        source.extracted_text = normalized
        source.status = "ready"
        source_metadata = dict(source.source_metadata or {})
        source_metadata["chunk_count"] = len(chunks_info)
        source_metadata["embedding_status"] = "queued"
        if pii_scan["detected"]:
            source_metadata["pii_scan"] = pii_scan
            emit_security_event(
                "pii_detected",
                outcome="observed",
                project_id=str(source.project_id),
                source_id=str(source.id),
                reason="pii_detected_in_source",
                details={"categories": list(pii_scan["counts"])},
            )
        if settings.SECURITY_AUDIT_SINK == "database":
            flush_pending_audit_sync(db)
        source.source_metadata = source_metadata
        db.commit()
        db.refresh(source)

        try:
            enqueue_source_embedding(source.id, queue=get_embedding_queue())
        except Exception as exc:  # pragma: no cover - defensive best effort
            source_metadata = dict(source.source_metadata or {})
            source_metadata["embedding_queue_error"] = str(exc)
            source_metadata["embedding_status"] = "queued"
            source.source_metadata = source_metadata
            db.commit()
        return source
    except (DocumentExtractionError, UnicodeDecodeError, OSError, ValueError) as exc:
        db.rollback()
        failed_source = db.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
        if failed_source is not None:
            failed_source.status = "failed"
            failed_source.source_metadata = {
                **(failed_source.source_metadata or {}),
                "ingestion_error": str(exc),
            }
            db.commit()
        raise


def claim_source_for_embedding(db: Session, source_id: uuid.UUID) -> bool:
    """Atomically claim a source for embedding generation.

    State transition: queued -> processing.
    Returns True if this worker won the claim and must generate embeddings.
    Returns False if the source is already processing, completed, or failed.
    """
    try:
        source = db.execute(
            select(Source).where(Source.id == source_id).with_for_update()
        ).scalar_one_or_none()
    except Exception:
        # Fallback for engines/dialects without SELECT FOR UPDATE (e.g. SQLite)
        source = db.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()

    if source is None:
        return False

    meta = dict(source.source_metadata or {})
    current_status = meta.get("embedding_status")

    if current_status in ("processing", "completed", "failed"):
        return False

    meta["embedding_status"] = "processing"
    source.source_metadata = meta
    db.commit()
    return True


def process_source_embeddings_with_session(
    db: Session,
    source_id: uuid.UUID,
    *,
    provider=None,
) -> Source:
    """Generate deterministic embeddings for a ready source and persist them without deleting source data.

    Enforces dual-dispatch safety: only the worker that successfully claims
    the source executes embedding generation.
    """
    source = db.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
    if source is None:
        raise ValueError(f"Source {source_id} was not found.")

    meta = dict(source.source_metadata or {})
    current_status = meta.get("embedding_status")

    # Idempotency check: if completed and all chunks have embeddings, return early
    if current_status == "completed":
        chunks = db.execute(
            select(SourceChunk)
            .where(SourceChunk.source_id == source.id)
            .order_by(SourceChunk.chunk_index)
        ).scalars().all()
        if chunks and all(chunk.embedding is not None for chunk in chunks):
            return source

    # Dual-dispatch safety: only the worker that wins the claim proceeds
    if not claim_source_for_embedding(db, source_id):
        refreshed = db.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
        return refreshed or source

    try:
        chunks = db.execute(
            select(SourceChunk)
            .where(SourceChunk.source_id == source.id)
            .order_by(SourceChunk.chunk_index)
        ).scalars().all()
        if not chunks:
            raise ValueError("Source has no chunks to embed.")

        texts = [chunk.content for chunk in chunks]
        service = EmbeddingService(provider=provider, dimensions=settings.EMBEDDING_DIMENSIONS)
        vectors = service.embed_texts(texts)
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector

        if not all(chunk.embedding is not None and len(chunk.embedding) == settings.EMBEDDING_DIMENSIONS for chunk in chunks):
            raise ValueError("Embedding generation incomplete: one or more chunks failed vector generation.")

        source_metadata = dict(source.source_metadata or {})
        source_metadata["embedding_status"] = "completed"
        source_metadata["embedding_dimensions"] = settings.EMBEDDING_DIMENSIONS
        source_metadata["embedding_model"] = settings.EMBEDDING_MODEL
        source_metadata["embedding_provider"] = settings.EMBEDDING_PROVIDER
        source_metadata["embedding_count"] = len(chunks)
        source.source_metadata = source_metadata
        db.commit()
        db.refresh(source)
        return source
    except Exception as exc:
        db.rollback()
        failed_source = db.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
        if failed_source is not None:
            metadata = dict(failed_source.source_metadata or {})
            metadata["embedding_status"] = "failed"
            metadata["embedding_error"] = str(exc)
            failed_source.source_metadata = metadata
            db.commit()
        raise


def execute_source_embeddings_sync(source_id: str | uuid.UUID, *, provider=None) -> None:
    """Execute source embedding generation synchronously using DATABASE_SYNC_URL.

    Safe for in-process background tasks or direct worker dispatch.
    """
    import structlog
    from sqlalchemy import create_engine
    from app.embeddings.factory import build_resilient_embedding_provider

    _logger = structlog.get_logger(__name__)
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    try:
        if provider is None:
            provider = build_resilient_embedding_provider()
        with Session(engine) as session:
            process_source_embeddings_with_session(session, uuid.UUID(str(source_id)), provider=provider)
            _logger.info("execute_source_embeddings_sync completed", source_id=str(source_id))
    except Exception as exc:
        _logger.error("execute_source_embeddings_sync failed", source_id=str(source_id), error=str(exc))
    finally:
        engine.dispose()
