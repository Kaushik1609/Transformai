"""
TransformIQ Backend — User ORM Model

Represents an authenticated operator or admin user.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """
    System user (operator or admin).

    Relationships:
        projects: 1-N → Project
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="operator")
    mobile_number: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        default=None,
        doc="Optional numeric mobile contact used as the SMS OTP channel",
    )
    password_hash: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        doc="PBKDF2-HMAC-SHA256 password hash (Phase 15). Nullable so legacy "
        "seeded/imported users fail closed on password login until a hash is set.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        doc="Account activation state. New registrations are inactive until the "
        "registration OTP is verified (Phase 15).",
    )
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
    projects: Mapped[list["Project"]] = relationship(  # type: ignore[name-defined]
        "Project",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!s} email={self.email!r}>"
