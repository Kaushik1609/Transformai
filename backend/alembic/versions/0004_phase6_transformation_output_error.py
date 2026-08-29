"""Phase 6: per-output independent failure tracking.

Adds an optional `error_message` column to the `outputs` table so a single
output can fail (and record a controlled error) without destroying the
successful outputs of the same transformation job.
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_phase6_transformation_output_error"
down_revision = "0003_phase4_content_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outputs",
        sa.Column("error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outputs", "error_message")
