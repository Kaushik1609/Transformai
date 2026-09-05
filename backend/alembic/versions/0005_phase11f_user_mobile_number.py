"""Phase 11F: add optional mobile_number to users

Revision ID: 0005_phase11f_user_mobile_number
Revises: 0004_phase6_transformation_output_error
Create Date: 2026-09-06 00:00:00.000000

Adds the nullable `mobile_number` column to `users` so the ORM model and the
live schema match. The column is used as the SMS OTP channel identifier and is
optional (NULL when a user has no mobile contact).
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_phase11f_user_mobile_number"
down_revision = "0004_phase6_transformation_output_error"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mobile_number", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "mobile_number")