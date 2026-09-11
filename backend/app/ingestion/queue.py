"""Redis/RQ dispatch helpers for asynchronous source ingestion and embeddings."""

from __future__ import annotations

from uuid import UUID

from rq import Queue

import redis

from app.core.config import settings


def get_ingestion_queue() -> Queue:
    """Create the Redis-backed ingestion queue from application settings."""
    connection = redis.from_url(settings.REDIS_URL)
    return Queue("ingestion", connection=connection)


def get_embedding_queue() -> Queue:
    """Create the Redis-backed embedding queue from application settings."""
    connection = redis.from_url(settings.REDIS_URL)
    return Queue("embedding", connection=connection)


def enqueue_source_ingestion(
    source_id: UUID,
    *,
    queue: Queue,
) -> str:
    """Enqueue only the authoritative source identifier."""
    job = queue.enqueue(
        "worker.process_source",
        source_id=str(source_id),
        job_timeout=settings.WORKER_JOB_TIMEOUT,
        result_ttl=86400,
    )
    return str(job.id)


def enqueue_source_embedding(
    source_id: UUID,
    *,
    queue: Queue,
) -> str:
    """Enqueue a source for embedding generation using only the source_id payload."""
    job = queue.enqueue(
        "worker.process_source_embedding",
        source_id=str(source_id),
        job_timeout=settings.WORKER_JOB_TIMEOUT,
        result_ttl=86400,
    )
    return str(job.id)


def get_content_intelligence_queue() -> Queue:
    """Create the Redis-backed Phase 4 analysis queue."""
    connection = redis.from_url(settings.REDIS_URL)
    return Queue("content_intelligence", connection=connection)


def enqueue_content_intelligence(source_id: UUID, *, queue: Queue) -> str:
    """Enqueue only the authoritative source identifier for analysis."""
    job = queue.enqueue(
        "worker.process_content_intelligence",
        source_id=str(source_id),
        job_timeout=settings.WORKER_JOB_TIMEOUT,
        result_ttl=86400,
    )
    return str(job.id)
