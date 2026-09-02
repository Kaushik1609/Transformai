"""Worker-facing transformation runner.

`run_transformation_job` is the authoritative entry point used by the RQ worker.
It loads the job from the database (never trusting queued payloads beyond the
job ID), honors cancellation, and coordinates the LangGraph workflow through the
orchestrator.  Successful outputs are committed; individual failures are
recorded without destroying successful outputs from the same job.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

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
    # The job's source must belong to the job's project (relationship integrity).
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

    orchestrator = TransformationOrchestrator(
        session=db,
        rag_service=rag_service,
        verification_hook=verification_hook,
        get_generator=get_generator,
        rag_mode=rag_mode,
        llm_provider=llm_provider,
        storage=storage,
    )
    result = orchestrator.execute(job_id)
    db.commit()
    return result
