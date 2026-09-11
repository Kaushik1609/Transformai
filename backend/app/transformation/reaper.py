"""
TransformIQ Backend — Stale Transformation-Job Reaper (Phase 13G)

A transformation job stuck in the ``running`` state with no successful finish
usually means its RQ worker died or was killed mid-job (a hard RQ timeout is
already handled by ``transformation_failure_handler`` and would never leave the
job running). To avoid an eternal ``running`` job and free the user-facing
history to show a terminal state, the backend reaper fails jobs whose
``started_at`` is older than ``STALE_TRANSFORMATION_JOB_GRACE_SECONDS``.

Safety: the grace period is strictly greater than ``WORKER_JOB_TIMEOUT``
(enforced in settings), so a live-but-slow job that RQ will time out on its own
is never touched by the reaper; and ``started_at`` is only set when a real
worker begins execution (never at enqueue time).
"""
from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select, update
from sqlalchemy.sql import func

from app.core.config import settings

logger = structlog.get_logger(__name__)


async def fail_stale_transformation_jobs(db) -> int:
    """Fail transformation jobs stuck in ``running`` past the grace period.

    Returns the number of jobs failed. Never raises. Emits a ``job_failed``
    security event per stale job (reason ``stale_job_reaped``) and drains the
    audit sink within the caller's session when the database sink is active.
    Caller owns commit/rollback.
    """
    from datetime import datetime, timedelta, timezone

    from app.core.audit import drain_pending_audit_events, emit_security_event
    from app.core.metrics import metrics
    from app.db.models.transformation_job import TransformationJob

    grace = settings.STALE_TRANSFORMATION_JOB_GRACE_SECONDS
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=grace)

    stale_ids = []
    try:
        rows = await db.scalars(
            select(TransformationJob.id).where(
                TransformationJob.status == "running",
                TransformationJob.started_at.is_not(None),
                TransformationJob.started_at < cutoff,
            )
        )
        stale_ids = list(rows.all())
    except Exception as exc:
        logger.error(
            "stale_job_reaper_query_failed",
            error=type(exc).__name__,
        )
        return 0

    if not stale_ids:
        return 0

    try:
        await db.execute(
            update(TransformationJob)
            .where(TransformationJob.id.in_(stale_ids))
            .values(
                status="failed",
                error_message=(
                    "Worker heartbeat expired: job marked failed by the stale-job "
                    f"reaper after {grace} seconds without completion."
                ),
                completed_at=func.now(),
            )
        )
    except Exception as exc:
        logger.error(
            "stale_job_reaper_update_failed",
            error=type(exc).__name__,
        )
        return 0

    for job_id in stale_ids:
        emit_security_event(
            "job_failed",
            outcome="denied",
            job_id=str(job_id),
            reason="stale_job_reaped",
            details={"grace_seconds": int(grace)},
        )
    metrics.inc("stale_transformation_jobs_failed_total", amount=len(stale_ids))

    if settings.SECURITY_AUDIT_SINK == "database":
        await drain_pending_audit_events(db)

    return len(stale_ids)


async def run_stale_job_reaper_loop(interval_seconds: int | None = None) -> None:
    """Continuous background loop (backend lifespan task).

    Runs every ``interval_seconds`` (default ``STALE_JOB_REAPER_INTERVAL_SECONDS``)
    or every 60s minimum. Each sweep opens a short async session, fails stale
    jobs, and commits. Failures are logged and never crash the loop.
    """
    from app.db.engine import get_async_session_factory

    interval = max(
        60, interval_seconds or settings.STALE_JOB_REAPER_INTERVAL_SECONDS
    )
    logger.info("stale_job_reaper_started", interval_seconds=interval)
    while True:
        try:
            session_factory = get_async_session_factory()
            async with session_factory() as session:
                failed = await fail_stale_transformation_jobs(session)
                await session.commit()
            if failed:
                logger.warning("stale_job_reaper_failed_jobs", count=failed)
        except asyncio.CancelledError:
            logger.info("stale_job_reaper_stopped")
            raise
        except Exception as exc:
            logger.error(
                "stale_job_reaper_sweep_failed",
                error=type(exc).__name__,
            )
        await asyncio.sleep(interval)