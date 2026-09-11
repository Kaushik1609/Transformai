"""Worker-facing transformation runner.

`run_transformation_job` is the authoritative entry point used by the RQ worker.
It loads the job from the database (never trusting queued payloads beyond the
job ID), honors cancellation, and coordinates the LangGraph workflow through the
orchestrator.  Successful outputs are committed; individual failures are
recorded without destroying successful outputs from the same job.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.metrics import metrics
from app.db.models.project import Project
from app.db.models.transformation_job import TransformationJob
from app.rag.service import RAGService
from app.transformation.orchestrator import TransformationOrchestrator


class TransformationError(Exception):
    """Raised when a transformation job cannot be safely processed."""


def _verify_job_ownership(db: Session, job: TransformationJob) -> TransformationJob:
    """
    Phase 9A — worker-side ownership integrity guard.

    The worker never receives an HTTP request context; it trusts only the
    authoritative job_id enqueued after the project was authorized at request
    time. This guard re-validates that the job still resolves to a project that
    owns a real user, so a queued job cannot reference orphaned / cross-tenant
    project or source relationships. This is a defense-in-depth integrity check,
    not a replacement for the request-time authorization performed when the job
    was created.
    """
    project = db.get(Project, job.project_id)
    if project is None:
        raise TransformationError(
            f"Transformation job {job.id} references a missing project."
        )
    if project.user_id is None:
        raise TransformationError(
            f"Transformation job {job.id} references a project without an owner."
        )
    # The job's source (when present) must belong to the job's project
    # (relationship integrity). Prompt-only jobs (source_id is None) skip the
    # source assertion.
    if job.source_id is not None:
        from app.db.models.source import Source

        source = db.get(Source, job.source_id)
        if source is None or source.project_id != job.project_id:
            raise TransformationError(
                f"Transformation job {job.id} source/ownership mismatch."
            )
    return job


def run_transformation_job(
    db: Session,
    job_id: uuid.UUID,
    *,
    rag_service: RAGService | None = None,
    verification_hook: Any | None = None,
    get_generator: Any | None = None,
    rag_mode: str = "auto",
    llm_provider: Any | None = None,
    storage: Any | None = None,
    transformation_job_timeout: int | None = None,
    cache_backend: Any | None = None,
    cache_enabled: bool | None = None,
) -> dict[str, Any]:
    """Run one transformation job to completion using authoritative DB state.

    Returns a summary dict of the outcome.  Commits the transaction when the
    run succeeds and rolls back (without corrupting the source) on unexpected
    worker-level failures.
    """
    job = db.execute(select(TransformationJob).where(TransformationJob.id == job_id)).scalar_one_or_none()
    if job is None:
        raise TransformationError(f"Transformation job {job_id} was not found.")

    # Phase 9A — verify owner/project/source relationship integrity before
    # the worker touches any job state.
    _verify_job_ownership(db, job)

    # Honour cancellation requested before the worker began processing.
    if job.status == "cancelled":
        return {
            "job_id": str(job_id),
            "skipped": True,
            "reason": "cancelled",
            "outputs": [],
            "errors": [],
        }

    if job.status == "completed":
        return {
            "job_id": str(job_id),
            "skipped": True,
            "reason": "already_completed",
            "outputs": [],
            "errors": [],
        }

    # Phase 11L-D — atomic worker claim.  A single UPDATE...WHERE on the status
    # transition (queued/failed -> running) is the worker's lease on the job.
    # Only ONE worker can get rowcount == 1 for a given job, so concurrent
    # workers / accidental re-enqueues can never execute the same script twice
    # (existing Phase 11E idempotent planning guards remain as defense-in-depth).
    claimed = db.execute(
        update(TransformationJob)
        .where(
            TransformationJob.id == job_id,
            TransformationJob.status.in_(("queued", "failed")),
        )
        .values(status="running")
    )
    if claimed.rowcount != 1:
        return {
            "job_id": str(job_id),
            "skipped": True,
            "reason": "claim_denied_already_running_or_terminal",
            "outputs": [],
            "errors": [],
        }
    # Persist the claim so the "running" lease is durable before any provider
    # work begins (a crash mid-run is surfaced by the RQ failure handler).
    db.commit()

    # Phase 11L-A — cache wiring.  When enabled, successful LLM generations are
    # cached per project (scope = job.project_id) so repeated transformations of
    # the same source never pay the provider cost twice.  Default off: historical
    # behavior is preserved and tests stay deterministic.
    provider = llm_provider
    use_cache = settings.CACHE_ENABLED if cache_enabled is None else cache_enabled
    if provider is not None and use_cache:
        backend = cache_backend
        if backend is None:
            from app.core.cache import build_cache_backend

            backend = build_cache_backend()
        if backend is not None:
            from app.transformation.llm.cache import CachingLLMProvider

            provider = CachingLLMProvider(
                provider,
                backend,
                scope=str(job.project_id),
                ttl_seconds=settings.CACHE_TTL_SECONDS,
                key_version=settings.CACHE_KEY_VERSION,
                provider_name=(settings.LLM_PROVIDER or "unknown"),
            )

    orchestrator = TransformationOrchestrator(
        session=db,
        rag_service=rag_service,
        verification_hook=verification_hook,
        get_generator=get_generator,
        rag_mode=rag_mode,
        llm_provider=provider,
        storage=storage,
        transformation_job_timeout=transformation_job_timeout,
    )
    started = time.monotonic()
    result = orchestrator.execute(job_id)
    # Phase 11M — POST-GENERATION integrity/provenance. Once generation has
    # completed (and without touching the AI pipeline), record the content
    # digest of every successfully persisted artifact. This is fail-open:
    # provenance failure never blocks or aborts the artifact or the job result.
    if settings.INTEGRITY_RECORD_ENABLED:
        _record_job_integrity(db, job_id, storage=storage, project_id=str(job.project_id))
    db.commit()
    metrics.observe(
        "transformation_job_duration_seconds", time.monotonic() - started
    )
    return result


def _record_job_integrity(
    db: Session,
    job_id: uuid.UUID,
    *,
    storage: Any | None = None,
    project_id: str | None = None,
) -> None:
    """Record integrity/provenance for a job's completed binary artifacts.

    Called only from the post-generation hook in ``run_transformation_job``.
    Loads the completed outputs and records a digest for each persisted
    artifact, storing the provenance status in ``output_metadata.integrity``.
    Never raises on a ledger failure: provenance is fail-open.
    """
    from app.db.models.output import Output
    from app.integrity.factory import build_ledger
    from app.integrity.service import record_output_integrity
    from app.transformation.artifacts import get_storage

    ledger = build_ledger()
    storage = storage or get_storage()
    try:
        outputs = db.execute(
            select(Output).where(
                Output.job_id == job_id,
                Output.status == "completed",
            )
        ).scalars().all()
    except Exception:
        metrics.inc(
            "integrity_hashes_total", {"result": "load_failed", "provider": "n/a"}
        )
        return
    for output in outputs:
        try:
            record_output_integrity(
                output,
                storage=storage,
                ledger=ledger,
                algorithm=settings.INTEGRITY_ALGORITHM,
                project_id=project_id,
            )
        except Exception:
            # Provenance must never break the job; record the failure metric and
            # continue with the remaining outputs.
            metrics.inc(
                "integrity_hashes_total", {"result": "error", "provider": "n/a"}
            )


def execute_transformation_job_sync(
    job_id: str | uuid.UUID,
    engine: Any | None = None,
) -> dict[str, Any]:
    """Execute a transformation job synchronously using DATABASE_SYNC_URL.

    Safe to invoke directly from in-process background tasks (FastAPI
    BackgroundTasks) or RQ workers. Atomic claiming ensures that if multiple
    workers or background tasks attempt to process the same job, exactly one
    wins the lease and the other gracefully skips.
    """
    import structlog
    from sqlalchemy import create_engine
    from app.transformation.llm.factory import build_llm_provider, build_resilient_provider
    from app.transformation.llm.metered import MeteredLLMProvider

    _logger = structlog.get_logger(__name__)
    job_uuid = uuid.UUID(str(job_id))
    engine_created = False
    if engine is None:
        engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
        engine_created = True
    try:
        with Session(engine) as session:
            job_record = session.get(TransformationJob, job_uuid)
            if not job_record:
                return {"job_id": str(job_id), "skipped": True, "reason": "not_found"}

            provider_override = None
            if job_record.requested_outputs and isinstance(job_record.requested_outputs, dict):
                provider_override = job_record.requested_outputs.get("llm_provider")

            if provider_override and str(provider_override).strip().lower() in (
                "fake",
                "development (fake - testing purpose)",
            ):
                base_provider = build_llm_provider("fake")
            else:
                base_provider = build_resilient_provider()

            if job_record.source_id:
                from app.db.models.canonical_content import CanonicalContent
                canonical = session.execute(
                    select(CanonicalContent).where(CanonicalContent.source_id == job_record.source_id)
                ).scalar_one_or_none()
                if canonical is None or canonical.status != "completed":
                    from app.content_intelligence.service import ContentIntelligenceService
                    from app.content_intelligence.fake_provider import FakeContentAnalysisProvider
                    ci = ContentIntelligenceService(provider=FakeContentAnalysisProvider())
                    ci.analyze_source(session, job_record.source_id)
                    session.commit()

            llm_provider = MeteredLLMProvider(base_provider)
            res = run_transformation_job(session, job_uuid, llm_provider=llm_provider)
            _logger.info("execute_transformation_job_sync completed", job_id=str(job_id), result=res)
            return res
    except Exception as exc:
        _logger.error("execute_transformation_job_sync failed", job_id=str(job_id), error=str(exc))
        try:
            with Session(engine) as session:
                job_record = session.get(TransformationJob, job_uuid)
                if job_record and job_record.status not in ("completed", "cancelled"):
                    job_record.status = "failed"
                    job_record.error_message = f"Execution error: {str(exc)}"[:1000]
                    session.commit()
        except Exception:
            pass
        return {"job_id": str(job_id), "status": "failed", "error": str(exc)}
    finally:
        if engine_created:
            engine.dispose()

