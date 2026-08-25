"""
TransformIQ Backend — Project ORM Model

A project groups related sources, configurations, and transformation jobs
together under a single user.
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.user import User
    from app.db.models.source import Source
    from app.db.models.generation_configuration import GenerationConfiguration
    from app.db.models.transformation_job import TransformationJob


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    """
    A workspace that groups sources, configurations, and transformation jobs.

    Relationships:
        user:                   N-1 → User
        sources:                1-N → Source
        generation_configurations: 1-N → GenerationConfiguration
        transformation_jobs:    1-N → TransformationJob
    """
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="projects")
    sources: Mapped[list["Source"]] = relationship(
        "Source",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    generation_configurations: Mapped[list["GenerationConfiguration"]] = relationship(
        "GenerationConfiguration",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    transformation_jobs: Mapped[list["TransformationJob"]] = relationship(
        "TransformationJob",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id!s} name={self.name!r}>"
