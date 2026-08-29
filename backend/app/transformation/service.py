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

from app.db.models.transformation_job import TransformationJob
from app.rag.service import RAGService
from app.transformation.orchestrator import TransformationOrchestrator


class TransformationError(Exception):
    """Raised when a transformation job cannot be safely processed."""


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
