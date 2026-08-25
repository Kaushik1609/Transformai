"""
TransformIQ Backend — Generation Configuration Service

Business logic for generation configuration CRUD.
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.generation_configuration import GenerationConfiguration

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_configuration(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    target_audience: str | None,
    tone: str | None,
    language: str,
    detail_level: str | None,
    communication_objective: str | None,
    content_style: str | None,
    custom_instructions: str | None,
) -> GenerationConfiguration:
    """Create a new generation configuration record."""
    config = GenerationConfiguration(
        id=uuid.uuid4(),
        project_id=project_id,
        target_audience=target_audience,
        tone=tone,
        language=language,
        detail_level=detail_level,
        communication_objective=communication_objective,
        content_style=content_style,
        custom_instructions=custom_instructions,
        created_at=_utcnow(),
    )
    db.add(config)
    await db.flush()
    await db.refresh(config)
    logger.info(
        "Configuration created",
        configuration_id=str(config.id),
        project_id=str(project_id),
    )
    return config


async def list_configurations(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
) -> list[GenerationConfiguration]:
    """Return all configurations for a project."""
    result = await db.execute(
        select(GenerationConfiguration)
        .where(GenerationConfiguration.project_id == project_id)
        .order_by(GenerationConfiguration.created_at.desc())
    )
    return list(result.scalars().all())


async def get_configuration(
    db: AsyncSession,
    *,
    configuration_id: uuid.UUID,
) -> GenerationConfiguration | None:
    """Return a single configuration by ID."""
    result = await db.execute(
        select(GenerationConfiguration).where(
            GenerationConfiguration.id == configuration_id
        )
    )
    return result.scalar_one_or_none()


async def update_configuration(
    db: AsyncSession,
    *,
    config: GenerationConfiguration,
    target_audience: str | None = None,
    tone: str | None = None,
    language: str | None = None,
    detail_level: str | None = None,
    communication_objective: str | None = None,
    content_style: str | None = None,
    custom_instructions: str | None = None,
) -> GenerationConfiguration:
    """Apply a partial update to a configuration."""
    if target_audience is not None:
        config.target_audience = target_audience
    if tone is not None:
        config.tone = tone
    if language is not None:
        config.language = language
    if detail_level is not None:
        config.detail_level = detail_level
    if communication_objective is not None:
        config.communication_objective = communication_objective
    if content_style is not None:
        config.content_style = content_style
    if custom_instructions is not None:
        config.custom_instructions = custom_instructions
    await db.flush()
    await db.refresh(config)
    logger.info("Configuration updated", configuration_id=str(config.id))
    return config


async def delete_configuration(
    db: AsyncSession,
    *,
    config: GenerationConfiguration,
) -> None:
    """Delete a configuration record."""
    await db.delete(config)
    await db.flush()
    logger.info("Configuration deleted", configuration_id=str(config.id))
