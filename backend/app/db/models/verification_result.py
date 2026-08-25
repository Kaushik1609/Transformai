"""
TransformIQ Backend — VerificationResult ORM Model

Stores quality check results for a generated output.
Verification is triggered automatically after generation (Phase 8).
In Phase 2, only the persistence model is established.
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy import JSON as JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.output import Output


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VerificationResult(Base):
    """
    Quality assurance result for a generated output.

    overall_status values: passed | warning | failed

    Note: Scores are internal quality indicators, not factual accuracy guarantees.

    Relationships:
        output: N-1 → Output
    """
    __tablename__ = "verification_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    output_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outputs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    overall_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="warning",
    )
    grounding_score: Mapped[float | None] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=True,
    )
    consistency_score: Mapped[float | None] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=True,
    )
    claims_checked: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claims_supported: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warnings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    # Relationships
    output: Mapped["Output"] = relationship(
        "Output",
        back_populates="verification_results",
    )

    def __repr__(self) -> str:
        return (
            f"<VerificationResult id={self.id!s} "
            f"output_id={self.output_id!s} "
            f"status={self.overall_status!r}>"
        )
