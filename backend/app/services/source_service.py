"""
TransformIQ Backend — Source Service

Business logic for source metadata CRUD operations.
Actual document processing (extraction, chunking, embeddings) is Phase 3+.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import emit_security_event
from app.core.config import settings
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.ingestion.documents import DocumentExtractionError, extract_docx, extract_pdf
from app.ingestion.malware_scan import (
    MalwareScanRejected,
    build_malware_scanner,
    run_malware_scan,
)
from app.ingestion.queue import enqueue_source_ingestion
from app.ingestion.pii_scan import EVENT_TYPE, scan_source_pii
from app.ingestion.storage import StorageAdapter, get_storage
from app.ingestion.text import chunk_text, normalize_text
from app.ingestion.validation import validate_source
from app.policy.classification import normalize_classification
from app.services.storage_lifecycle import (
    cleanup_storage_keys,
    collect_source_artifact_keys,
    keys_referenced_by_other_records,
)

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _scan_malware(
    *,
    content: bytes,
    project_id: uuid.UUID,
    source_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Run the configured malware scan and return bounded metadata (or empty).

    Raises ``MalwareScanRejected`` when a required scan is not CLEAN
    (fail-closed).  Returns ``{}`` when scanning is disabled or no metadata
    was produced.  Never alters ``content`` and never persists raw output.
    """
    if not settings.MALWARE_SCAN_ENABLED:
        return {}
    try:
        scanner = build_malware_scanner(
            name=settings.MALWARE_SCANNER,
            host=settings.CLAMAV_HOST,
            port=settings.CLAMAV_PORT,
            timeout_seconds=settings.CLAMAV_TIMEOUT_SECONDS,
        )
        meta = run_malware_scan(
            content=content,
            scanner=scanner,
            enabled=True,
            required=settings.MALWARE_SCAN_REQUIRED,
            project_id=str(project_id),
            source_id=str(source_id) if source_id is not None else None,
        )
        return {"malware_scan": meta} if meta else {}
    except MalwareScanRejected as exc:
        # Real/test malware (INFECTED) must ALWAYS be rejected in all environments.
        if getattr(exc, "status", None) == "infected":
            raise
        # When ClamAV daemon is unreachable in free deployment environments:
        # If scanning is not strictly required, record truthful unavailable metadata.
        if not settings.MALWARE_SCAN_REQUIRED:
            return {
                "malware_scan": {
                    "status": "unavailable",
                    "scanner": settings.MALWARE_SCANNER,
                    "reason": "daemon_unreachable",
                }
            }
        raise


async def create_pending_source(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    content: bytes,
    source_type: str,
    filename: str,
    mime_type: str,
    language: str,
    metadata: dict[str, Any] | None = None,
    classification: str | None = None,
) -> Source:
    """Validate and store an original, leaving extraction to the worker."""
    validated = validate_source(
        source_type=source_type,
        content=content,
        filename=filename,
        mime_type=mime_type,
        max_size_bytes=settings.max_upload_size_bytes,
    )
    source_metadata = dict(metadata or {})
    source_metadata["classification"] = normalize_classification(
        classification or source_metadata.get("classification")
    ).value
    source_metadata["file_security"] = {
        "status": "active",
        "validated_format": validated.source_type,
    }
    source_metadata.update(_scan_malware(content=content, project_id=project_id))
    source = Source(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type=validated.source_type,
        original_filename=validated.filename,
        mime_type=validated.mime_type,
        file_size=validated.file_size,
        language=language,
        status="processing",
        source_metadata=source_metadata or None,
        created_at=_utcnow(),
    )
    db.add(source)
    await db.flush()

    storage = get_storage()
    storage_key = storage.source_key(project_id, source.id, filename)
    storage.save(storage_key, content, content_type=validated.mime_type)
    source.storage_key = storage_key
    await db.flush()
    await db.refresh(source)
    return source


async def ingest_text_source(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    content: bytes,
    source_type: str,
    filename: str | None,
    mime_type: str,
    language: str,
    metadata: dict[str, Any] | None,
    classification: str | None = None,
) -> Source:
    """Synchronously validate, store, normalize, and persist a text source."""
    validated = validate_source(
        source_type=source_type,
        content=content,
        filename=filename,
        mime_type=mime_type,
        max_size_bytes=settings.max_upload_size_bytes,
    )
    try:
        text = normalize_text(content.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("Text source must be UTF-8 encoded.") from exc
    if not text:
        raise ValueError("Text source cannot be empty after normalization.")
    if len(text) > settings.INPUT_MAX_TEXT_LENGTH:
        raise ValueError(
            "Text source exceeds the configured input limit of "
            f"{settings.INPUT_MAX_TEXT_LENGTH} characters."
        )

    source_metadata = dict(metadata or {})
    source_metadata["classification"] = normalize_classification(
        classification or source_metadata.get("classification")
    ).value
    source_metadata["file_security"] = {
        "status": "active",
        "validated_format": validated.source_type,
    }
    source_metadata.update(_scan_malware(content=content, project_id=project_id))
    pii_scan = scan_source_pii(text)
    if pii_scan["detected"]:
        source_metadata["pii_scan"] = pii_scan
        emit_security_event(
            EVENT_TYPE,
            outcome="observed",
            project_id=str(project_id),
            reason="pii_detected_in_source",
            details={"categories": list(pii_scan["counts"])},
        )

    source = Source(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type=validated.source_type,
        original_filename=validated.filename,
        mime_type=validated.mime_type,
        file_size=validated.file_size,
        language=language,
        status="processing",
        source_metadata=source_metadata or None,
        extracted_text=text,
        created_at=_utcnow(),
    )
    db.add(source)
    await db.flush()

    storage_filename = validated.filename or "original.txt"
    storage = get_storage()
    storage_key = storage.source_key(project_id, source.id, storage_filename)
    storage.save(storage_key, content, content_type=validated.mime_type)
    source.storage_key = storage_key

    chunks = chunk_text(text)
    for chunk_index, chunk in enumerate(chunks):
        db.add(
            SourceChunk(
                id=uuid.uuid4(),
                source_id=source.id,
                chunk_index=chunk_index,
                content=chunk,
                embedding=None,
                created_at=_utcnow(),
            )
        )

    source_metadata = dict(source.source_metadata or {})
    source_metadata["chunk_count"] = len(chunks)
    source_metadata["embedding_status"] = "queued"
    source.source_metadata = source_metadata
    source.status = "ready"
    await db.flush()
    await db.refresh(source)

    try:
        from app.ingestion.queue import enqueue_source_embedding, get_embedding_queue
        enqueue_source_embedding(source.id, queue=get_embedding_queue())
    except Exception as exc:  # pragma: no cover - defensive best effort
        source_metadata = dict(source.source_metadata or {})
        source_metadata["embedding_queue_error"] = str(exc)
        source_metadata["embedding_status"] = "queued"
        source.source_metadata = source_metadata
        await db.flush()
        logger.warning(
            "Could not enqueue source embedding to Redis",
            source_id=str(source.id),
            error=str(exc),
        )

    logger.info(
        "Text source ingested",
        source_id=str(source.id),
        project_id=str(project_id),
        source_type=validated.source_type,
        chunk_count=len(chunks),
    )
    return source


async def ingest_document_source(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    content: bytes,
    source_type: str,
    filename: str | None,
    mime_type: str,
    language: str,
    metadata: dict[str, Any] | None = None,
    classification: str | None = None,
) -> Source:
    """Synchronously validate, extract, store, and persist a PDF or DOCX."""
    validated = validate_source(
        source_type=source_type,
        content=content,
        filename=filename,
        mime_type=mime_type,
        max_size_bytes=settings.max_upload_size_bytes,
    )
    extracted_text = (
        extract_pdf(content)
        if validated.source_type == "pdf"
        else extract_docx(content)
    )
    text = normalize_text(extracted_text)
    if not text:
        raise ValueError("Document contains no usable text.")

    source_metadata: dict[str, Any] = dict(metadata or {})
    source_metadata["classification"] = normalize_classification(
        classification or source_metadata.get("classification")
    ).value
    source_metadata["file_security"] = {
        "status": "active",
        "validated_format": validated.source_type,
    }
    source_metadata.update(_scan_malware(content=content, project_id=project_id))
    pii_scan = scan_source_pii(text)
    if pii_scan["detected"]:
        source_metadata["pii_scan"] = pii_scan
        emit_security_event(
            EVENT_TYPE,
            outcome="observed",
            project_id=str(project_id),
            reason="pii_detected_in_source",
            details={"categories": list(pii_scan["counts"])},
        )

    source = Source(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type=validated.source_type,
        original_filename=validated.filename,
        mime_type=validated.mime_type,
        file_size=validated.file_size,
        language=language,
        status="processing",
        extracted_text=text,
        source_metadata=source_metadata or None,
        created_at=_utcnow(),
    )
    db.add(source)
    await db.flush()

    storage = get_storage()
    storage_key = storage.source_key(project_id, source.id, validated.filename or "original")
    storage.save(storage_key, content, content_type=validated.mime_type)
    source.storage_key = storage_key

    chunks = chunk_text(text)
    for chunk_index, chunk in enumerate(chunks):
        db.add(
            SourceChunk(
                id=uuid.uuid4(),
                source_id=source.id,
                chunk_index=chunk_index,
                content=chunk,
                embedding=None,
                created_at=_utcnow(),
            )
        )

    source_metadata = dict(source.source_metadata or {})
    source_metadata["chunk_count"] = len(chunks)
    source_metadata["embedding_status"] = "queued"
    source.source_metadata = source_metadata
    source.status = "ready"
    await db.flush()
    await db.refresh(source)

    try:
        from app.ingestion.queue import enqueue_source_embedding, get_embedding_queue
        enqueue_source_embedding(source.id, queue=get_embedding_queue())
    except Exception as exc:  # pragma: no cover - defensive best effort
        source_metadata = dict(source.source_metadata or {})
        source_metadata["embedding_queue_error"] = str(exc)
        source_metadata["embedding_status"] = "queued"
        source.source_metadata = source_metadata
        await db.flush()
        logger.warning(
            "Could not enqueue source embedding to Redis",
            source_id=str(source.id),
            error=str(exc),
        )

    logger.info(
        "Document source ingested",
        source_id=str(source.id),
        project_id=str(project_id),
        source_type=validated.source_type,
        chunk_count=len(chunks),
    )
    return source


async def create_source(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    source_type: str,
    original_filename: str | None,
    extracted_text: str | None,
    mime_type: str | None,
    language: str,
    metadata: dict[str, Any] | None,
    classification: str | None = None,
) -> Source:
    """Create a new source metadata record."""
    source_metadata = dict(metadata or {})
    source_metadata["classification"] = normalize_classification(
        classification or source_metadata.get("classification")
    ).value

    source = Source(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type=source_type,
        original_filename=original_filename,
        extracted_text=extracted_text,
        mime_type=mime_type,
        language=language,
        status="uploaded",
        source_metadata=source_metadata,
        created_at=_utcnow(),
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)
    logger.info(
        "Source created",
        source_id=str(source.id),
        project_id=str(project_id),
        source_type=source_type,
    )
    return source


async def list_sources(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
) -> list[Source]:
    """Return all sources for a project."""
    result = await db.execute(
        select(Source)
        .where(Source.project_id == project_id)
        .order_by(Source.created_at.desc())
    )
    return list(result.scalars().all())


async def get_source(
    db: AsyncSession,
    *,
    source_id: uuid.UUID,
) -> Source | None:
    """Return a single source by ID (no user scope — caller must verify project ownership)."""
    result = await db.execute(select(Source).where(Source.id == source_id))
    return result.scalar_one_or_none()


async def get_source_owned(
    db: AsyncSession,
    *,
    source_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Source | None:
    """
    Return a single source by ID, scoped to an owning user.

    Enforces authorization at the database level by joining through the
    parent project to its owner. A source that exists but belongs to another
    user is indistinguishable from a nonexistent source (returns ``None``).

    Phase 9A — SQL-level ownership scoping to prevent IDOR / BOLA.
    """
    result = await db.execute(
        select(Source)
        .join(Project, Source.project_id == Project.id)
        .where(
            Source.id == source_id,
            Project.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_source(
    db: AsyncSession,
    *,
    source: Source,
    storage: StorageAdapter | None = None,
) -> None:
    """
    Delete a source and all its cascaded children, including persisted artifacts.

    Storage files for the source original and its job outputs are removed
    before the database record so a transient storage failure leaves the
    record intact for a safe, idempotent retry. Keys still referenced by other
    live records are protected from deletion.
    """
    keys, output_ids = await collect_source_artifact_keys(db, source=source)
    referenced_keys = await keys_referenced_by_other_records(
        db,
        keys=keys,
        exclude_source_ids={source.id},
        exclude_output_ids=output_ids,
    )
    cleaner = storage if storage is not None else get_storage()
    cleanup_storage_keys(cleaner, keys=keys, referenced_keys=referenced_keys)
    await db.delete(source)
    await db.flush()
    logger.info("Source deleted", source_id=str(source.id))
