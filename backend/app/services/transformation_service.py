"""
TransformIQ Backend — Transformation Job Service

Business logic for transformation job, output, and verification result persistence.
Phase 2: Only persistence is implemented. No actual job enqueueing.
Phase 6 will add the Redis job dispatch step.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.transformation_job import TransformationJob
from app.db.models.output import Output
from app.db.models.verification_result import VerificationResult

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_job(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    configuration_id: uuid.UUID,
    output_types: list[str],
) -> TransformationJob:
    """
    Create a new transformation job record.
    Phase 2: Record is persisted with status='queued'.
    Phase 6 will add the Redis enqueueing step.
    """
    job = TransformationJob(
        id=uuid.uuid4(),
        project_id=project_id,
        source_id=source_id,
        configuration_id=configuration_id,
        requested_outputs={"output_types": output_types},
        status="queued",
        progress=0,
        created_at=_utcnow(),
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    logger.info(
        "Transformation job created",
        job_id=str(job.id),
        project_id=str(project_id),
        output_types=output_types,
    )
    return job


async def get_job(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
) -> TransformationJob | None:
    """
    Return a single job by ID, scoped to the user's projects.
    Joins through project to enforce the authorization boundary.
    """
    from app.db.models.project import Project  # avoid circular import

    result = await db.execute(
        select(TransformationJob)
        .join(Project, TransformationJob.project_id == Project.id)
        .where(
            TransformationJob.id == job_id,
            Project.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_jobs_by_project(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
) -> list[TransformationJob]:
    """Return all transformation jobs for a project (newest first)."""
    result = await db.execute(
        select(TransformationJob)
        .where(TransformationJob.project_id == project_id)
        .order_by(TransformationJob.created_at.desc())
    )
    return list(result.scalars().all())


async def list_job_outputs(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> list[Output]:
    """Return all outputs for a transformation job."""
    result = await db.execute(
        select(Output)
        .where(Output.job_id == job_id)
        .order_by(Output.created_at.asc())
    )
    return list(result.scalars().all())


async def get_output(
    db: AsyncSession,
    *,
    output_id: uuid.UUID,
) -> Output | None:
    """Return a single output by ID."""
    result = await db.execute(select(Output).where(Output.id == output_id))
    return result.scalar_one_or_none()


async def get_output_owned(
    db: AsyncSession,
    *,
    output_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Output | None:
    """
    Return a single output by ID, scoped to an owning user.

    Enforces the full ownership chain at the database level by joining
    through the output's job to the owning project. An output that exists but
    belongs to another user is indistinguishable from a nonexistent output
    (returns ``None``).

    Chain: Output → job → project → user

    Phase 9A — SQL-level ownership scoping to prevent IDOR / BOLA.
    """
    from app.db.models.project import Project  # avoid circular import
    from app.db.models.transformation_job import TransformationJob

    result = await db.execute(
        select(Output)
        .join(TransformationJob, Output.job_id == TransformationJob.id)
        .join(Project, TransformationJob.project_id == Project.id)
        .where(
            Output.id == output_id,
            Project.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_output_verifications(
    db: AsyncSession,
    *,
    output_id: uuid.UUID,
) -> list[VerificationResult]:
    """Return all verification results for an output."""
    result = await db.execute(
        select(VerificationResult)
        .where(VerificationResult.output_id == output_id)
        .order_by(VerificationResult.created_at.desc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Direct persistence helpers (used by tests and future worker code)
# ---------------------------------------------------------------------------

async def create_output(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    output_type: str,
    status: str = "generating",
    structured_content: dict[str, Any] | None = None,
    text_content: str | None = None,
    storage_key: str | None = None,
    mime_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Output:
    """Create an output record (called by worker in Phase 6)."""
    output = Output(
        id=uuid.uuid4(),
        job_id=job_id,
        output_type=output_type,
        status=status,
        structured_content=structured_content,
        text_content=text_content,
        storage_key=storage_key,
        mime_type=mime_type,
        output_metadata=metadata,
        created_at=_utcnow(),
    )
    db.add(output)
    await db.flush()
    await db.refresh(output)
    return output


async def create_verification_result(
    db: AsyncSession,
    *,
    output_id: uuid.UUID,
    overall_status: str = "warning",
    grounding_score: float | None = None,
    consistency_score: float | None = None,
    claims_checked: int | None = None,
    claims_supported: int | None = None,
    warnings: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> VerificationResult:
    """Create a verification result record (called by verifier in Phase 8)."""
    result = VerificationResult(
        id=uuid.uuid4(),
        output_id=output_id,
        overall_status=overall_status,
        grounding_score=grounding_score,
        consistency_score=consistency_score,
        claims_checked=claims_checked,
        claims_supported=claims_supported,
        warnings=warnings,
        details=details,
        created_at=_utcnow(),
    )
    db.add(result)
    await db.flush()
    await db.refresh(result)
    return result
