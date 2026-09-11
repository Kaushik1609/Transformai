"""Redis/RQ dispatch helpers for the Phase 6 transformation queue.

Follows the existing ingestion/content-intelligence queue patterns.  The worker
receives only the authoritative transformation job ID and loads all state from
the database.
"""

from __future__ import annotations

from uuid import UUID

from rq import Queue

import redis

from app.core.config import settings
from app.core.metrics import metrics


def get_transformation_queue() -> Queue:
    """Create the Redis-backed transformation queue from application settings."""
    connection = redis.from_url(settings.REDIS_URL)
    return Queue("transformation", connection=connection)


def enqueue_transformation_job(
    job_id: UUID,
    *,
    queue: Queue,
) -> str:
    """Enqueue only the authoritative transformation job identifier."""
    job = queue.enqueue(
        "worker.process_transformation",
        str(job_id),
        job_timeout=settings.WORKER_JOB_TIMEOUT,
        result_ttl=86400,
        on_failure="worker.transformation_failure_handler",
    )
    metrics.inc("transformation_jobs_enqueued_total", {"queue": "transformation"})
    return str(job.id)


def cancel_transformation_job(
    job_id: UUID,
    *,
    queue: Queue,
) -> bool:
    """Attempt to revoke a queued transformation job using RQ cancellation.

    Returns True if a queued job was cancelled, False otherwise (e.g. the job
    was already dequeued/started — the DB status transition still applies).
    """
    rq_job_id = _find_queued_job_id(queue, job_id)
    if rq_job_id is None:
        return False
    rq_job = queue.fetch_job(rq_job_id)
    if rq_job is None:
        return False
    try:
        rq_job.cancel()
        return True
    except Exception:  # RQ cancellation limitations (e.g. started job)
        return False


def _find_queued_job_id(queue: Queue, job_id: UUID) -> str | None:
    """Return the RQ job ID for a queued transformation job if present.

    RQ stores queued payloads; we scan the queue registry for the payload that
    references the given job ID.  This is a best-effort lookup.
    """
    target = str(job_id)
    try:
        for rq_job_id in queue.job_ids:
            rq_job = queue.fetch_job(rq_job_id)
            if rq_job is None:
                continue
            args = rq_job.args if rq_job.args is not None else ()
            kwargs = rq_job.kwargs if rq_job.kwargs is not None else {}
            if args and args[0] == target:
                return rq_job_id
            if kwargs.get("job_id") == target:
                return rq_job_id
    except Exception:
        return None
    return None
