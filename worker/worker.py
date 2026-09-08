"""
TransformIQ Worker
RQ (Redis Queue) background job processor.

Phase 1 — establishes the Redis connection, registers a demo job function,
and confirms the worker is operational. Real job handlers for document
processing and AI transformation will be added in Phase 3+.

Usage:
    python worker.py

Environment variables:
    REDIS_URL           Redis connection string  (default: redis://localhost:6379/0)
    LOG_LEVEL           Logging verbosity        (default: INFO)
    ENVIRONMENT         Application environment  (default: development)
    WORKER_COUNT        Number of worker processes (default: 1)
    WORKER_JOB_TIMEOUT  Max seconds per job      (default: 605, from WORKER_JOB_TIMEOUT)
"""
import logging
import os
import subprocess
import sys
import time

import redis
import structlog
from rq import Queue, Worker

from app.core.config import settings
from app.core.metrics import metrics, push_worker_metrics
from app.core.redaction import redact_secrets
from app.ingestion.worker_processing import process_source_with_session
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Bootstrap logging before importing app modules so early errors are visible.
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
)

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
        if os.getenv("ENVIRONMENT", "development") == "development"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    ),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment (no hardcoded values)
# ---------------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# Phase 11L-D: scaling is the NUMBER OF WORKER PROCESSES (a single RQ 2.0
# worker process runs one job at a time). main() launches WORKER_COUNT
# processes that share the same Redis-backed queues.
WORKER_COUNT = int(os.getenv("WORKER_COUNT", "1"))
# Single source of truth: the worker timeout is read ONLY from application
# config (backend/app/core/config.py WORKER_JOB_TIMEOUT). RQ applies it as the
# per-job timeout at enqueue time (see app/*/queue.py).
WORKER_JOB_TIMEOUT = settings.WORKER_JOB_TIMEOUT

# Queue names — will be extended as job types are added in later phases.
QUEUE_NAMES = [
    "high",     # Priority jobs (user-facing, short operations)
    "default",  # Standard transformation jobs
    "low",      # Background/bulk operations
    "ingestion",  # Source ingestion jobs
    "embedding",  # Embedding generation jobs
    "content_intelligence",  # Phase 4 source analysis jobs
    "transformation",  # Phase 6 transformation jobs
]


def process_source(source_id: str) -> dict[str, str]:
    """RQ handler that processes a source using authoritative database data."""
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    try:
        import uuid

        with Session(engine) as session:
            source = process_source_with_session(session, uuid.UUID(source_id))
            result = {"source_id": str(source.id), "status": source.status}
        metrics.inc("ingestion_jobs_total", {"kind": "source", "result": "completed"})
        _push_metrics()
        return result
    except Exception:
        metrics.inc(
            "ingestion_jobs_total", {"kind": "source", "result": "failed"}
        )
        _push_metrics()
        raise
    finally:
        engine.dispose()


def process_source_embedding(source_id: str) -> dict[str, str]:
    """RQ handler that generates embeddings for a source's chunks without deleting source data.

    The embedding provider is resolved from configuration (EMBEDDING_PROVIDER)
    via the Phase 11G factory. An explicitly selected real provider NEVER falls
    back to fake embeddings: missing credentials or provider failures surface as
    an explicit job failure so RAG quality is never silently degraded.
    """
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    try:
        import uuid

        from app.embeddings.factory import build_resilient_embedding_provider
        from app.ingestion.worker_processing import process_source_embeddings_with_session

        embedding_provider = build_resilient_embedding_provider()

        with Session(engine) as session:
            source = process_source_embeddings_with_session(
                session, uuid.UUID(source_id), provider=embedding_provider
            )
            result = {"source_id": str(source.id), "status": source.status}
        metrics.inc("ingestion_jobs_total", {"kind": "embedding", "result": "completed"})
        _push_metrics()
        return result
    except Exception:
        metrics.inc(
            "ingestion_jobs_total", {"kind": "embedding", "result": "failed"}
        )
        _push_metrics()
        raise
    finally:
        engine.dispose()


def process_content_intelligence(source_id: str) -> dict[str, str]:
    """RQ handler for validated Phase 4 canonical content analysis."""
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    try:
        import uuid

        from app.content_intelligence.fake_provider import FakeContentAnalysisProvider
        from app.content_intelligence.service import ContentIntelligenceService

        with Session(engine) as session:
            content = ContentIntelligenceService(
                provider=FakeContentAnalysisProvider()
            ).analyze_source(session, uuid.UUID(source_id))
            result = {"source_id": str(content.source_id), "status": content.status}
        metrics.inc(
            "ingestion_jobs_total", {"kind": "content_intelligence", "result": "completed"}
        )
        _push_metrics()
        return result
    except Exception:
        metrics.inc(
            "ingestion_jobs_total", {"kind": "content_intelligence", "result": "failed"}
        )
        _push_metrics()
        raise
    finally:
        engine.dispose()


def process_transformation(job_id: str) -> dict:
    """RQ handler for Phase 6/7 transformation jobs.

    Receives only the authoritative transformation job ID and loads all required
    state (job, canonical content, configuration, RAG) from the database.  The
    LLM provider is wired from environment settings through a resilient
    ProviderManager: retries, backoff, circuit breaking and an optional
    fallback are applied centrally (Phase 11D).
    """
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    try:
        import uuid

        from app.transformation.llm.factory import build_resilient_provider
        from app.transformation.llm.metered import MeteredLLMProvider
        from app.transformation.service import run_transformation_job

        llm_provider = MeteredLLMProvider(build_resilient_provider())
        with Session(engine) as session:
            result = run_transformation_job(
                session, uuid.UUID(job_id), llm_provider=llm_provider
            )
        if not result.get("skipped"):
            metrics.inc("transformation_jobs_total", {"result": "completed"})
        _push_metrics()
        return result
    except Exception:
        _push_metrics()
        raise
    finally:
        engine.dispose()


def _is_timeout_failure(value) -> bool:
    """Return True when an RQ failure value represents a job timeout.

    RQ 2.0 raises ``rq.timeouts.JobTimeoutException`` (threading-based timer,
    platform-independent) when a job exceeds its ``job_timeout``. We detect the
    base class so a clear, timeout-specific reason is written to the DB row.
    """
    try:
        from rq.timeouts import BaseTimeoutException

        if isinstance(value, BaseTimeoutException):
            return True
    except ImportError:  # pragma: no cover - RQ API safety
        pass
    return "jobtimeout" in type(value).__name__.lower()


def transformation_failure_handler(job, connection, type, value, traceback):
    """Mark a transformation job failed when the RQ job itself fails.

    RQ calls this when a queued transformation job raises an unhandled error
    (including exceeding ``WORKER_JOB_TIMEOUT``, which RQ turns into a
    ``JobTimeoutException``). The job is never left in a stuck ``running`` /
    ``queued`` state: a ``failed`` status with a clear reason is written to the
    job's DB record. Records a controlled error without corrupting the source or
    other outputs.
    """
    logger = structlog.get_logger(__name__)
    job_id = None
    try:
        args = job.args if job.args is not None else ()
        if args:
            job_id = args[0]
    except Exception:  # pragma: no cover - defensive
        job_id = None

    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    try:
        import uuid
        from datetime import datetime, timezone

        from sqlalchemy import select

        from app.core.audit import emit_security_event, flush_pending_audit_sync
        from app.core.metrics import metrics
        from app.core.config import settings as app_settings
        from app.db.models.transformation_job import TransformationJob

        if job_id is not None:
            metrics.inc("transformation_jobs_total", {"result": "failed"})
            _push_metrics()
            with Session(engine) as session:
                job_record = session.execute(
                    select(TransformationJob).where(TransformationJob.id == uuid.UUID(job_id))
                ).scalar_one_or_none()
                if job_record is not None and job_record.status not in ("completed", "cancelled"):
                    job_record.status = "failed"
                    if _is_timeout_failure(value):
                        job_record.error_message = (
                            f"Worker job timed out after {WORKER_JOB_TIMEOUT} seconds."
                        )
                    else:
                        job_record.error_message = (
                            "Worker job failed: "
                            f"{redact_secrets(str(value))}"[:4000]
                        )
                    job_record.completed_at = datetime.now(timezone.utc)
                    # Phase 13G: durable job-failure security event + metric.
                    emit_security_event(
                        "job_failed",
                        outcome="denied",
                        job_id=job_id,
                        project_id=str(job_record.project_id) if job_record.project_id else None,
                        reason="worker_job_failure",
                        details={"timeout": _is_timeout_failure(value)},
                    )
                    if app_settings.SECURITY_AUDIT_SINK == "database":
                        flush_pending_audit_sync(session)
                    session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(
            "Could not mark transformation job failed",
            error=redact_secrets(str(exc)),
        )
    finally:
        engine.dispose()
    logger.error(
        "Transformation RQ job failed",
        job_id=job_id,
        error=redact_secrets(str(value)),
    )


# ---------------------------------------------------------------------------
# Worker metrics (Phase 11L-C)
# ---------------------------------------------------------------------------

_METRIC_CONN = None


def _metric_connection() -> redis.Redis:
    """Lazily created, short-timeout Redis connection used to push deltas."""
    global _METRIC_CONN
    if _METRIC_CONN is None:
        _METRIC_CONN = redis.from_url(
            REDIS_URL, socket_connect_timeout=1, socket_timeout=2
        )
    return _METRIC_CONN


def _push_metrics() -> None:
    """Push accumulated local counter delta to the shared metric keys.

    Deltas are removed from the local registry only after a successful push
    (the backend absorbs outstanding deltas if the push fails, so a temporary
    Redis blip never loses or double-counts samples).
    """
    try:
        push_worker_metrics(_metric_connection())
    except Exception as exc:  # pragma: no cover - Redis outage path
        logger.warning(
            "Could not push worker metrics",
            error=redact_secrets(str(exc)),
        )


# ---------------------------------------------------------------------------
# Demo job — Phase 1 test mechanism
# ---------------------------------------------------------------------------

def demo_job(message: str = "hello") -> dict:
    """
    Minimal test job used to verify the worker can pick up and execute tasks.

    This function is intentionally simple — its only purpose is to prove
    end-to-end queue connectivity during Phase 1. Real transformation job
    handlers will be added starting in Phase 3.

    Args:
        message: A short string to echo back in the result.

    Returns:
        A dict containing the echoed message and a timestamp.
    """
    logger.info("demo_job executing", message=message)
    result = {
        "status": "completed",
        "message": message,
        "worker": f"transformiq-worker-{os.getpid()}",
        "timestamp": time.time(),
    }
    logger.info("demo_job completed", result=result)
    return result


# ---------------------------------------------------------------------------
# Redis connectivity with retry
# ---------------------------------------------------------------------------

def _redis_host(url: str) -> str:
    """Return a credential-free host label for a Redis URL."""
    try:
        from urllib.parse import urlsplit

        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return host or "unknown"
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def wait_for_redis(url: str, retries: int = 10, delay: float = 3.0) -> redis.Redis:
    """
    Attempt to connect to Redis with retries.
    Exits the process if Redis is unreachable after all retries.
    """
    logger.info("Connecting to Redis", host=_redis_host(url))
    conn = redis.from_url(url)

    for attempt in range(1, retries + 1):
        try:
            conn.ping()
            logger.info("Redis connection established", attempt=attempt)
            return conn
        except redis.exceptions.ConnectionError as exc:
            logger.warning(
                "Redis not yet available",
                attempt=attempt,
                max_retries=retries,
                error=redact_secrets(str(exc)),
            )
            if attempt < retries:
                time.sleep(delay)
            else:
                logger.error(
                    "Could not connect to Redis after retries. Exiting.",
                    retries=retries,
                )
                sys.exit(1)

    # Unreachable — kept for type checker
    sys.exit(1)  # pragma: no cover


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SINGLE_WORKER_FLAG = "--worker-single"


def _run_single_worker_process() -> None:
    """Run one continuous RQ worker process against the shared queues."""
    redis_conn = wait_for_redis(REDIS_URL)
    queues = [Queue(name, connection=redis_conn) for name in QUEUE_NAMES]

    logger.info(
        "Worker ready — listening on queues",
        pid=os.getpid(),
        queues=QUEUE_NAMES,
        demo_job="worker.demo_job",
    )

    worker = Worker(
        queues=queues,
        connection=redis_conn,
        name=f"transformiq-worker-{os.getpid()}",
    )

    worker.work(
        with_scheduler=True,
        burst=False,  # continuous mode
    )


def main() -> None:
    single_mode = SINGLE_WORKER_FLAG in sys.argv

    logger.info(
        "TransformIQ worker starting",
        environment=os.getenv("ENVIRONMENT", "development"),
        queues=QUEUE_NAMES,
        worker_count=WORKER_COUNT,
        single_mode=single_mode,
    )

    # Phase 11L-D — worker scaling is the number of PROCESSES.  RQ 2.0 workers
    # run one job at a time, so main() launches (WORKER_COUNT - 1) one-shot
    # subprocesses (``--worker-single``) and keeps one worker in this process.
    # Each subprocess is its own Python process with its own RQ connection to
    # the same queues — this mirrors the production pattern of running N worker
    # containers/replicas and is safe on Windows (no os.fork dependency).
    if not single_mode:
        spawned = []
        for _ in range(max(0, WORKER_COUNT - 1)):
            proc = subprocess.Popen(
                [
                    sys.executable,
                    os.path.abspath(__file__),
                    SINGLE_WORKER_FLAG,
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            spawned.append(proc)
            logger.info(
                "Spawned worker subprocess",
                pid=proc.pid,
                worker_count=WORKER_COUNT,
            )

    _run_single_worker_process()


if __name__ == "__main__":
    main()
