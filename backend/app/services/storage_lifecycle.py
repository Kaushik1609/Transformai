"""
TransformIQ Backend — Storage Lifecycle Service

Keeps persisted storage artifacts in step with their owning database records.

Ownership model (one artifact family per record):
    * Source.storage_key        -> original uploaded file
    * Output.storage_key        -> primary rendered artifact
    * Output.output_metadata    -> companion artifacts, carried under the
      "pdf_storage_key" (PDF targets) and "subtitle_storage_key" (SRT/video
      subtitle) roles.

Cleanup ordering (retry-safe):
    1. Remove storage files BEFORE deleting the database record. Missing
       files are treated as an idempotent success, so a retry converges.
    2. If an unexpected filesystem error occurs, it propagates before the
       record is deleted, leaving the record in place for a safe retry.

Shared-key protection:
    A key is deleted only when no other persisted Source/Output row still
    references it. Records scheduled for deletion are excluded through the
    explicit ``exclude_source_ids`` / ``exclude_output_ids`` sets so their own
    keys remain eligible for cleanup.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.output import Output
from app.db.models.source import Source
from app.db.models.transformation_job import TransformationJob
from app.ingestion.storage import StorageAdapter

logger = structlog.get_logger(__name__)

# Output metadata roles that carry companion artifact storage keys.
_OUTPUT_METADATA_STORAGE_ROLES = ("pdf_storage_key", "subtitle_storage_key")


def output_storage_keys(output: Output) -> list[str]:
    """Return every storage key owned by an output (primary plus companions)."""
    keys: list[str] = []
    if output.storage_key:
        keys.append(output.storage_key)
    metadata = output.output_metadata if isinstance(output.output_metadata, dict) else {}
    for role in _OUTPUT_METADATA_STORAGE_ROLES:
        key = metadata.get(role)
        if isinstance(key, str) and key:
            keys.append(key)
    return keys


async def collect_source_artifact_keys(
    db: AsyncSession,
    *,
    source: Source,
) -> tuple[list[str], set[uuid.UUID]]:
    """Return ``(keys, output_ids)`` for everything cascaded from a source.

    ``output_ids`` identifies the outputs owned by the source's jobs so a later
    reference scan can exclude them from the shared-key guard.
    """
    keys: list[str] = [source.storage_key] if source.storage_key else []
    job_ids = (
        await db.execute(
            select(TransformationJob.id).where(TransformationJob.source_id == source.id)
        )
    ).scalars().all()
    outputs = await _load_outputs(db, job_ids=set(job_ids))
    for output in outputs:
        keys.extend(output_storage_keys(output))
    return keys, {output.id for output in outputs}


async def collect_project_artifact_keys(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
) -> tuple[list[str], set[uuid.UUID], set[uuid.UUID]]:
    """Return ``(keys, source_ids, output_ids)`` for everything under a project."""
    source_rows = (
        await db.execute(
            select(Source.id, Source.storage_key).where(Source.project_id == project_id)
        )
    ).all()
    source_ids: set[uuid.UUID] = set()
    keys: list[str] = []
    for source_id, storage_key in source_rows:
        source_ids.add(source_id)
        if storage_key:
            keys.append(storage_key)
    job_ids = (
        await db.execute(
            select(TransformationJob.id).where(TransformationJob.project_id == project_id)
        )
    ).scalars().all()
    outputs = await _load_outputs(db, job_ids=set(job_ids))
    output_ids: set[uuid.UUID] = set()
    for output in outputs:
        output_ids.add(output.id)
        keys.extend(output_storage_keys(output))
    return keys, source_ids, output_ids


async def _load_outputs(db: AsyncSession, *, job_ids: set[uuid.UUID]) -> list[Output]:
    if not job_ids:
        return []
    return list(
        (await db.execute(select(Output).where(Output.job_id.in_(job_ids)))).scalars().all()
    )


async def keys_referenced_by_other_records(
    db: AsyncSession,
    *,
    keys: list[str],
    exclude_source_ids: set[uuid.UUID] | None = None,
    exclude_output_ids: set[uuid.UUID] | None = None,
) -> set[str]:
    """Return the subset of ``keys`` still referenced by persisted records.

    Records scheduled for deletion are passed in via the ``exclude_*`` sets so
    their own keys are not treated as a reason to keep a file. Both scalar
    ``storage_key`` columns and companion ``output_metadata`` roles are checked.
    """
    key_set = {key for key in keys if key}
    if not key_set:
        return set()
    excluded_sources = set(exclude_source_ids or ())
    excluded_outputs = set(exclude_output_ids or ())
    referenced: set[str] = set()

    for source_id, storage_key in (
        await db.execute(
            select(Source.id, Source.storage_key).where(
                Source.storage_key.in_(list(key_set))
            )
        )
    ).all():
        if storage_key and source_id not in excluded_sources:
            referenced.add(storage_key)

    for output_id, storage_key in (
        await db.execute(
            select(Output.id, Output.storage_key).where(
                Output.storage_key.in_(list(key_set))
            )
        )
    ).all():
        if storage_key and output_id not in excluded_outputs:
            referenced.add(storage_key)

    output_meta_rows = await db.execute(select(Output.id, Output.output_metadata))
    for output_id, metadata in output_meta_rows.all():
        if output_id in excluded_outputs:
            continue
        for value in (metadata or {}).values():
            if isinstance(value, str) and value in key_set:
                referenced.add(value)

    return referenced


def cleanup_storage_keys(
    storage: StorageAdapter,
    *,
    keys: list[str],
    referenced_keys: set[str] | None = None,
) -> None:
    """Idempotently delete ``keys`` unless another record still references one.

    Missing artifacts are treated as success. Unsupported keys (traversal,
    directory targets) and unexpected filesystem errors propagate so cleanup
    failures are never silently swallowed.
    """
    protected = set(referenced_keys or ())
    for key in keys:
        if not key or key in protected:
            continue
        storage.delete(key)
    logger.debug(
        "Storage cleanup complete", total=len(keys), skipped=len(protected)
    )