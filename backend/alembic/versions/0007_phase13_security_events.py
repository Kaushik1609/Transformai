"""Phase 13D: durable security-events table.

Revision ID: 0007_phase13_security_events
Revises: 0006_retrieval_perf
Create Date: 2026-09-08 00:00:00.000000

Adds the ``security_events`` table — the durable sink behind
``SECURITY_AUDIT_SINK=database``. Stores only safe, already-redacted
operational fields (event type, outcome, timestamps, non-secret identifiers,
JSON ``details``). Identifiers are plain strings (no foreign keys) so audit
records survive entity deletion. Indexes mirror the owner-scoped read path of
the security-events API: by event_type, by occurred_at, and a composite owner
lookup on (project_id, user_id, occurred_at).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_phase13_security_events"
down_revision = "0006_retrieval_perf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("project_id", sa.String(64), nullable=True),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_security_events_event_type",
        "security_events",
        ["event_type"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_security_events_occurred_at",
        "security_events",
        ["occurred_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_security_events_owner_lookup",
        "security_events",
        ["project_id", "user_id", "occurred_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_security_events_owner_lookup", table_name="security_events", if_exists=True)
    op.drop_index("ix_security_events_occurred_at", table_name="security_events", if_exists=True)
    op.drop_index("ix_security_events_event_type", table_name="security_events", if_exists=True)
    op.drop_table("security_events")