"""
TransformIQ Backend — Generation Configuration API Router

Endpoints:
    POST   /api/v1/projects/{project_id}/configurations
    GET    /api/v1/projects/{project_id}/configurations
    GET    /api/v1/configurations/{configuration_id}
    PATCH  /api/v1/configurations/{configuration_id}
    DELETE /api/v1/configurations/{configuration_id}
"""
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.api.v1.schemas.configuration import (
    ConfigurationCreate,
    ConfigurationDetailResponse,
    ConfigurationListResponse,
    ConfigurationResponse,
    ConfigurationUpdate,
    DeleteResponse,
)
from app.db.session import get_db
from app.services import configuration_service, project_service

logger = structlog.get_logger(__name__)

# Two separate routers for nested and standalone endpoints
project_configs_router = APIRouter(tags=["configurations"])
configs_router = APIRouter(tags=["configurations"])


# ---------------------------------------------------------------------------
# Nested under projects
# ---------------------------------------------------------------------------

@project_configs_router.post(
    "/{project_id}/configurations",
    response_model=ConfigurationDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a generation configuration for a project",
)
async def create_configuration(
    project_id: uuid.UUID,
    body: ConfigurationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ConfigurationDetailResponse:
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    config = await configuration_service.create_configuration(
        db,
        project_id=project_id,
        target_audience=body.target_audience,
        tone=body.tone,
        language=body.language,
        detail_level=body.detail_level,
        communication_objective=body.communication_objective,
        content_style=body.content_style,
        custom_instructions=body.custom_instructions,
    )
    return ConfigurationDetailResponse(
        data=ConfigurationResponse.model_validate(config)
    )


@project_configs_router.get(
    "/{project_id}/configurations",
    response_model=ConfigurationListResponse,
    summary="List configurations for a project",
)
async def list_configurations(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ConfigurationListResponse:
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    configs = await configuration_service.list_configurations(
        db, project_id=project_id
    )
    return ConfigurationListResponse(
        data=[ConfigurationResponse.model_validate(c) for c in configs],
        count=len(configs),
    )


# ---------------------------------------------------------------------------
# Standalone configuration endpoints
# ---------------------------------------------------------------------------

async def _get_config_with_auth(
    configuration_id: uuid.UUID,
    db: AsyncSession,
    user_id: uuid.UUID,
):
    """Helper: fetch config and verify ownership via project."""
    config = await configuration_service.get_configuration(
        db, configuration_id=configuration_id
    )
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration {configuration_id} not found.",
        )
    project = await project_service.get_project(
        db, project_id=config.project_id, user_id=user_id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration {configuration_id} not found.",
        )
    return config


@configs_router.get(
    "/{configuration_id}",
    response_model=ConfigurationDetailResponse,
    summary="Get a configuration by ID",
)
async def get_configuration(
    configuration_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ConfigurationDetailResponse:
    config = await _get_config_with_auth(configuration_id, db, current_user.id)
    return ConfigurationDetailResponse(
        data=ConfigurationResponse.model_validate(config)
    )


@configs_router.patch(
    "/{configuration_id}",
    response_model=ConfigurationDetailResponse,
    summary="Update a configuration",
)
async def update_configuration(
    configuration_id: uuid.UUID,
    body: ConfigurationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ConfigurationDetailResponse:
    config = await _get_config_with_auth(configuration_id, db, current_user.id)
    updated = await configuration_service.update_configuration(
        db,
        config=config,
        target_audience=body.target_audience,
        tone=body.tone,
        language=body.language,
        detail_level=body.detail_level,
        communication_objective=body.communication_objective,
        content_style=body.content_style,
        custom_instructions=body.custom_instructions,
    )
    return ConfigurationDetailResponse(
        data=ConfigurationResponse.model_validate(updated)
    )


@configs_router.delete(
    "/{configuration_id}",
    response_model=DeleteResponse,
    summary="Delete a configuration",
)
async def delete_configuration(
    configuration_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> DeleteResponse:
    config = await _get_config_with_auth(configuration_id, db, current_user.id)
    await configuration_service.delete_configuration(db, config=config)
    return DeleteResponse(
        message=f"Configuration {configuration_id} deleted successfully."
    )
