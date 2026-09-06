"""Explicit/manual embedding backfill for sources that missed embeddings.

Phase 11J-C (C9): this module is NEVER executed automatically and has no
import-time side effects (no engine, no Redis, no provider). It is an explicit
tool that:

* selects ready sources whose chunks have no populated embeddings,
* enqueues them through the EXISTING embedding queue abstraction
  (``enqueue_source_embedding`` / ``get_embedding_queue``) carrying only the
  authoritative ``source_id`` payload,
* does not create a new queue or provider and never bypasses the worker-side
  ``EmbeddingResilientProvider``,
* skips sources that are already ``queued`` or ``completed`` so a manual
  backfill does not duplicate in-flight or finished jobs.

Run explicitly (outside of any pytest/worker context):

    python -m app.ingestion.backfill --dry-run   # report candidates only
    python -m app.ingestion.backfill --execute   # enqueue candidates
"""

from __future__ import annotations

import argparse
import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.ingestion.queue import enqueue_source_embedding, get_embedding_queue

_COMPLETED = "completed"
_QUEUED = "queued"


def sources_requiring_embeddings(
    db: Session, *, include_queued: bool = False
) -> list[Source]:
    """Ready sources whose chunks have no populated embeddings.

    Excludes sources already ``completed`` or ``queued`` (unless
    ``include_queued`` forces inclusion, e.g. for jobs that were enqueued but
    never started). Overlapped with the current schema: embedding status is
    tracked per source in ``source.source_metadata["embedding_status"]``.
    """
    has_embedding = (
        select(SourceChunk.id)
        .where(
            SourceChunk.source_id == Source.id,
            SourceChunk.embedding.is_not(None),
        )
        .exists()
    )
    stmt = (
        select(Source)
        .where(Source.status == "ready")
        .where(~has_embedding)
        .order_by(Source.created_at)
    )
    candidates: list[Source] = []
    for source in db.execute(stmt).scalars().all():
        status = (source.source_metadata or {}).get("embedding_status")
        if status == _COMPLETED:
            continue
        if status == _QUEUED and not include_queued:
            continue
        candidates.append(source)
    return candidates


def enqueue_missing_embeddings(
    db: Session,
    *,
    include_queued: bool = False,
    limit: int | None = None,
    enqueue=enqueue_source_embedding,
    queue=None,
) -> tuple[list[uuid.UUID], list[tuple[uuid.UUID, str]]]:
    """Enqueue embedding jobs for every source missing embeddings.

    Returns ``(enqueued_source_ids, failures)`` where each failure is a
    ``(source_id, error_message)`` tuple. Marks each enqueued source as
    ``queued`` so repeated runs do not duplicate jobs (mirrors the ingestion
    pipeline's own enqueue bookkeeping).
    """
    if queue is None:
        queue = get_embedding_queue()
    candidates = sources_requiring_embeddings(db, include_queued=include_queued)
    if limit is not None:
        candidates = candidates[: max(0, int(limit))]

    enqueued: list[uuid.UUID] = []
    failures: list[tuple[uuid.UUID, str]] = []
    for source in candidates:
        try:
            enqueue(source.id, queue=queue)
        except Exception as exc:  # defensive: surface the failure, keep going
            failures.append((source.id, f"{type(exc).__name__}: {exc}"))
            continue
        metadata = dict(source.source_metadata or {})
        metadata["embedding_status"] = _QUEUED
        source.source_metadata = metadata
        enqueued.append(source.id)
    db.commit()
    return enqueued, failures


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual embedding backfill tool.")
    parser.add_argument("--dry-run", action="store_true", help="Report candidates only.")
    parser.add_argument("--execute", action="store_true", help="Enqueue embedding jobs.")
    parser.add_argument(
        "--include-queued",
        action="store_true",
        help="Also re-enqueue sources already marked queued (stuck jobs).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Cap the batch size.")
    args = parser.parse_args(argv)

    from sqlalchemy import create_engine

    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            candidates = sources_requiring_embeddings(
                session, include_queued=args.include_queued
            )
            if args.limit is not None:
                candidates = candidates[: max(0, args.limit)]

            if args.execute:
                enqueued, failures = enqueue_missing_embeddings(
                    session,
                    include_queued=args.include_queued,
                    limit=args.limit,
                    queue=get_embedding_queue(),
                )
                print(f"Enqueued {len(enqueued)} source(s) for embedding.")
                for source_id, error in failures:
                    print(f"FAILED to enqueue {source_id}: {error}")
            else:
                print(f"{len(candidates)} ready source(s) missing embeddings:")
                for source in candidates:
                    print(f"  {source.id}  {source.original_filename}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(_main())