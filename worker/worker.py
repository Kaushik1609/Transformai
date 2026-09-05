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
    WORKER_CONCURRENCY  Parallel worker threads  (default: 2)
    WORKER_JOB_TIMEOUT  Max seconds per job      (default: 300)
"""
import logging
import os
import sys
import time

import redis
import structlog
from rq import Queue, Worker

from app.core.config import settings
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
WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "2"))
WORKER_JOB_TIMEOUT = int(os.getenv("WORKER_JOB_TIMEOUT", "300"))

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
            return {"source_id": str(source.id), "status": source.status}
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
            return {"source_id": str(source.id), "status": source.status}
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
            return {"source_id": str(content.source_id), "status": content.status}
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
        from app.transformation.service import run_transformation_job

        llm_provider = build_resilient_provider()
        with Session(engine) as session:
            return run_transformation_job(
                session, uuid.UUID(job_id), llm_provider=llm_provider
            )
    finally:
        engine.dispose()


def transformation_failure_handler(job, connection, type, value, traceback):
    """Mark a transformation job failed when the RQ job itself fails.

    RQ calls this when a queued transformation job raises an unhandled error.
    Records a controlled error without corrupting the source or other outputs.
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

        from app.db.models.transformation_job import TransformationJob

        if job_id is not None:
            with Session(engine) as session:
                job_record = session.execute(
                    select(TransformationJob).where(TransformationJob.id == uuid.UUID(job_id))
                ).scalar_one_or_none()
                if job_record is not None and job_record.status not in ("completed", "cancelled"):
                    job_record.status = "failed"
                    job_record.error_message = f"Worker job failed: {value}"[:4000]
                    job_record.completed_at = datetime.now(timezone.utc)
                    session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Could not mark transformation job failed", error=str(exc))
    finally:
        engine.dispose()
    logger.error("Transformation RQ job failed", job_id=job_id, error=str(value))


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

def wait_for_redis(url: str, retries: int = 10, delay: float = 3.0) -> redis.Redis:
    """
    Attempt to connect to Redis with retries.
    Exits the process if Redis is unreachable after all retries.
    """
    logger.info("Connecting to Redis", url=url)
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
                error=str(exc),
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

def main() -> None:
    logger.info(
        "TransformIQ worker starting",
        environment=os.getenv("ENVIRONMENT", "development"),
        queues=QUEUE_NAMES,
        concurrency=WORKER_CONCURRENCY,
    )

    redis_conn = wait_for_redis(REDIS_URL)

    queues = [Queue(name, connection=redis_conn) for name in QUEUE_NAMES]

    logger.info(
        "Worker ready — listening on queues",
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


if __name__ == "__main__":
    main()
