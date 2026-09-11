"""
TransformIQ Backend — Project Service

Business logic for project CRUD operations.
Route handlers call this service; no business logic lives in router files.
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.user import User
from app.ingestion.storage import StorageAdapter, get_storage
from app.services.storage_lifecycle import (
    cleanup_storage_keys,
    collect_project_artifact_keys,
    keys_referenced_by_other_records,
)

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_user_exists(db: AsyncSession, user_id: uuid.UUID, email: str, name: str, role: str) -> User:
    """
    Retrieve the user by ID; create a new record if it does not exist.
    This supports the dev auth bypass where the DB user may not yet exist.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(id=user_id, email=email, name=name, role=role)
        db.add(user)
        await db.flush()
    return user


async def create_project(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    user_email: str,
    user_name: str,
    user_role: str,
    name: str,
    description: str | None,
) -> Project:
    """Create a new project for the current user."""
    await _ensure_user_exists(db, user_id, user_email, user_name, user_role)

    project = Project(
        id=uuid.uuid4(),
        user_id=user_id,
        name=name,
        description=description,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    logger.info("Project created", project_id=str(project.id), user_id=str(user_id))
    return project


async def list_projects(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> list[Project]:
    """Return all projects belonging to the current user."""
    result = await db.execute(
        select(Project)
        .where(Project.user_id == user_id)
        .order_by(Project.created_at.desc())
    )
    return list(result.scalars().all())


async def get_project(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Project | None:
    """Return a single project by ID, scoped to the current user."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def update_project(
    db: AsyncSession,
    *,
    project: Project,
    name: str | None,
    description: str | None,
) -> Project:
    """Apply a partial update to a project."""
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    project.updated_at = _utcnow()
    await db.flush()
    await db.refresh(project)
    logger.info("Project updated", project_id=str(project.id))
    return project


async def delete_project(
    db: AsyncSession,
    *,
    project: Project,
    storage: StorageAdapter | None = None,
) -> None:
    """
    Delete a project and all its cascaded children, including persisted artifacts.

    Storage files for every source original and job output under the project
    are removed before the database record so a transient storage failure
    leaves the record intact for a safe, idempotent retry. Keys still
    referenced by other live records are protected from deletion.
    """
    keys, source_ids, output_ids = await collect_project_artifact_keys(
        db, project_id=project.id
    )
    referenced_keys = await keys_referenced_by_other_records(
        db,
        keys=keys,
        exclude_source_ids=source_ids,
        exclude_output_ids=output_ids,
    )
    cleaner = storage if storage is not None else get_storage()
    cleanup_storage_keys(cleaner, keys=keys, referenced_keys=referenced_keys)
    await db.delete(project)
    await db.flush()
    logger.info("Project deleted", project_id=str(project.id))
