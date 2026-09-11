"""Phase 15: password auth + prompt-only transformation inputs.

Revision ID: 0008_phase15_password_and_prompt_inputs
Revises: 0007_phase13_security_events
Create Date: 2026-09-09 00:00:00.000000

Adds the schema changes required for Phase 15:

users
  - ``password_hash`` (Text, nullable): PBKDF2-HMAC-SHA256 digest. Nullable so
    legacy seeded/imported users remain valid in the database but fail closed
    on password login until a hash is set.
  - ``is_active`` (Boolean, NOT NULL, server default true): new registrations
    are created inactive and become active only after the registration OTP is
    verified.

transformation_jobs
  - ``source_id`` becomes nullable: prompt-only transformations have no source.
  - ``prompt`` (Text, nullable): the operator prompt for prompt-only /
    prompt+source input modes. At least one of source_id / prompt is required
    at the API layer.
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_phase15_password_and_prompt_inputs"
down_revision = "0007_phase13_security_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "transformation_jobs",
        sa.Column("prompt", sa.Text(), nullable=True),
    )
    op.alter_column(
        "transformation_jobs",
        "source_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "transformation_jobs",
        "source_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_column("transformation_jobs", "prompt")
    op.drop_column("users", "is_active")
    op.drop_column("users", "password_hash")