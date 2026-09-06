"""
TransformIQ Backend — Project API Router

Endpoints:
    POST   /api/v1/projects
    GET    /api/v1/projects
    GET    /api/v1/projects/{project_id}
    PATCH  /api/v1/projects/{project_id}
    DELETE /api/v1/projects/{project_id}

Route handlers are kept thin: validation and response shaping only.
All business logic is in project_service.
"""
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.api.v1.schemas.project import (
    DeleteResponse,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.core.audit import emit_security_event
from app.db.session import get_db
from app.services import project_service

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["projects"])


@router.post(
    "",
    response_model=ProjectDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ProjectDetailResponse:
    project = await project_service.create_project(
        db,
        user_id=current_user.id,
        user_email=current_user.email,
        user_name=current_user.name,
        user_role=current_user.role,
        name=body.name,
        description=body.description,
    )
    return ProjectDetailResponse(data=ProjectResponse.model_validate(project))


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List all projects for the current user",
)
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ProjectListResponse:
    projects = await project_service.list_projects(db, user_id=current_user.id)
    return ProjectListResponse(
        data=[ProjectResponse.model_validate(p) for p in projects],
        count=len(projects),
    )


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    summary="Get a project by ID",
)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ProjectDetailResponse:
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    return ProjectDetailResponse(data=ProjectResponse.model_validate(project))


@router.patch(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    summary="Update a project",
)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ProjectDetailResponse:
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    updated = await project_service.update_project(
        db,
        project=project,
        name=body.name,
        description=body.description,
    )
    return ProjectDetailResponse(data=ProjectResponse.model_validate(updated))


@router.delete(
    "/{project_id}",
    response_model=DeleteResponse,
    summary="Delete a project",
)
async def delete_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> DeleteResponse:
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    await project_service.delete_project(db, project=project)
    emit_security_event(
        "project_deleted",
        outcome="allowed",
        user_id=str(current_user.id),
        project_id=str(project_id),
    )
    return DeleteResponse(message=f"Project {project_id} deleted successfully.")
