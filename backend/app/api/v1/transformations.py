"""
TransformIQ Backend — Transformation Job API Router

Endpoints:
    POST   /api/v1/transformations
    GET    /api/v1/transformations/{job_id}
    GET    /api/v1/transformations/{job_id}/outputs
    POST   /api/v1/transformations/{job_id}/cancel  (stub — Phase 6)

    GET    /api/v1/outputs/{output_id}
    GET    /api/v1/outputs/{output_id}/verification

Phase 2: persistence only. No job enqueueing, no AI calls.
"""
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.api.v1.schemas.transformation import (
    OutputDetailResponse,
    OutputListResponse,
    OutputResponse,
    TransformationJobCreate,
    TransformationJobDetailResponse,
    TransformationJobResponse,
    VerificationListResponse,
    VerificationResultResponse,
)
from app.db.session import get_db
from app.services import project_service, source_service, configuration_service, transformation_service

logger = structlog.get_logger(__name__)

transformations_router = APIRouter(tags=["transformations"])
outputs_router = APIRouter(tags=["outputs"])


# ---------------------------------------------------------------------------
# Transformation Jobs
# ---------------------------------------------------------------------------

@transformations_router.post(
    "",
    response_model=TransformationJobDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a transformation job",
)
async def create_transformation(
    body: TransformationJobCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> TransformationJobDetailResponse:
    # Verify project ownership
    project = await project_service.get_project(
        db, project_id=body.project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {body.project_id} not found.",
        )
    # Verify source exists in project
    source = await source_service.get_source(db, source_id=body.source_id)
    if source is None or source.project_id != body.project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {body.source_id} not found in project {body.project_id}.",
        )
    # Verify configuration exists in project
    config = await configuration_service.get_configuration(
        db, configuration_id=body.configuration_id
    )
    if config is None or config.project_id != body.project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration {body.configuration_id} not found in project {body.project_id}.",
        )
    job = await transformation_service.create_job(
        db,
        project_id=body.project_id,
        source_id=body.source_id,
        configuration_id=body.configuration_id,
        output_types=body.output_types,
    )
    return TransformationJobDetailResponse(
        data=TransformationJobResponse.model_validate(job)
    )


@transformations_router.get(
    "/{job_id}",
    response_model=TransformationJobDetailResponse,
    summary="Get a transformation job by ID",
)
async def get_transformation(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> TransformationJobDetailResponse:
    job = await transformation_service.get_job(
        db, job_id=job_id, user_id=current_user.id
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )
    return TransformationJobDetailResponse(
        data=TransformationJobResponse.model_validate(job)
    )


@transformations_router.get(
    "/{job_id}/outputs",
    response_model=OutputListResponse,
    summary="List outputs for a transformation job",
)
async def list_job_outputs(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> OutputListResponse:
    job = await transformation_service.get_job(
        db, job_id=job_id, user_id=current_user.id
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )
    outputs = await transformation_service.list_job_outputs(db, job_id=job_id)
    return OutputListResponse(
        data=[OutputResponse.model_validate(o) for o in outputs],
        count=len(outputs),
    )


@transformations_router.post(
    "/{job_id}/cancel",
    response_model=TransformationJobDetailResponse,
    summary="Cancel a transformation job (stub — Phase 6)",
)
async def cancel_transformation(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> TransformationJobDetailResponse:
    """
    Phase 2 stub: marks the job cancelled in the database.
    Phase 6 will also revoke the queued Redis task.
    """
    job = await transformation_service.get_job(
        db, job_id=job_id, user_id=current_user.id
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )
    if job.status not in ("queued", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job {job_id} cannot be cancelled (current status: {job.status}).",
        )
    from datetime import datetime, timezone
    job.status = "cancelled"
    job.completed_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(job)
    return TransformationJobDetailResponse(
        data=TransformationJobResponse.model_validate(job)
    )


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

@outputs_router.get(
    "/{output_id}",
    response_model=OutputDetailResponse,
    summary="Get an output by ID",
)
async def get_output(
    output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> OutputDetailResponse:
    output = await transformation_service.get_output(db, output_id=output_id)
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    # Verify ownership through job → project
    job = await transformation_service.get_job(
        db, job_id=output.job_id, user_id=current_user.id
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    return OutputDetailResponse(data=OutputResponse.model_validate(output))


@outputs_router.get(
    "/{output_id}/verification",
    response_model=VerificationListResponse,
    summary="List verification results for an output",
)
async def list_output_verifications(
    output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> VerificationListResponse:
    output = await transformation_service.get_output(db, output_id=output_id)
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    job = await transformation_service.get_job(
        db, job_id=output.job_id, user_id=current_user.id
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    verifications = await transformation_service.list_output_verifications(
        db, output_id=output_id
    )
    return VerificationListResponse(
        data=[VerificationResultResponse.model_validate(v) for v in verifications],
        count=len(verifications),
    )
