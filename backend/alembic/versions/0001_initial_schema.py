"""
TransformIQ — Initial database migration

Revision ID: 0001_initial_schema
Revises: (none)
Create Date: 2025-01-01 00:00:00.000000

Creates:
    - users
    - projects
    - sources
    - source_chunks  (embedding as TEXT — Phase 5 will ALTER to VECTOR)
    - generation_configurations
    - transformation_jobs
    - outputs
    - verification_results

pgvector extension is created here so Phase 5 can safely ALTER the
embedding column to VECTOR(1536) without a separate extension step.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enable pgvector extension (safe: CREATE IF NOT EXISTS)
    # Phase 5 will use it for the embedding column.
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="operator"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])

    # ------------------------------------------------------------------
    # sources
    # ------------------------------------------------------------------
    op.create_table(
        "sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(50), nullable=False, server_default="text"),
        sa.Column("original_filename", sa.String(512), nullable=True),
        sa.Column("storage_key", sa.String(1024), nullable=True),
        sa.Column("extracted_text", sa.Text, nullable=True),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("file_size", sa.BigInteger, nullable=True),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="uploaded",
        ),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_sources_project_id", "sources", ["project_id"])
    op.create_index("ix_sources_status", "sources", ["status"])

    # ------------------------------------------------------------------
    # source_chunks
    # NOTE: embedding stored as TEXT in Phase 2.
    #       Phase 5 migration will: ALTER COLUMN embedding TYPE VECTOR(1536)
    # ------------------------------------------------------------------
    op.create_table(
        "source_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("content", sa.Text, nullable=False),
        # Phase 2: TEXT placeholder for the future pgvector VECTOR column
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_source_chunks_source_id", "source_chunks", ["source_id"])

    # ------------------------------------------------------------------
    # generation_configurations
    # ------------------------------------------------------------------
    op.create_table(
        "generation_configurations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_audience", sa.String(255), nullable=True),
        sa.Column("tone", sa.String(100), nullable=True),
        sa.Column(
            "language",
            sa.String(50),
            nullable=False,
            server_default="English",
        ),
        sa.Column("detail_level", sa.String(50), nullable=True),
        sa.Column("communication_objective", sa.String(255), nullable=True),
        sa.Column("content_style", sa.String(100), nullable=True),
        sa.Column("custom_instructions", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_generation_configurations_project_id",
        "generation_configurations",
        ["project_id"],
    )

    # ------------------------------------------------------------------
    # transformation_jobs
    # ------------------------------------------------------------------
    op.create_table(
        "transformation_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "configuration_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_configurations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requested_outputs", postgresql.JSONB, nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_transformation_jobs_project_id",
        "transformation_jobs",
        ["project_id"],
    )
    op.create_index(
        "ix_transformation_jobs_source_id",
        "transformation_jobs",
        ["source_id"],
    )
    op.create_index(
        "ix_transformation_jobs_status",
        "transformation_jobs",
        ["status"],
    )

    # ------------------------------------------------------------------
    # outputs
    # ------------------------------------------------------------------
    op.create_table(
        "outputs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transformation_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("output_type", sa.String(50), nullable=False),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="generating",
        ),
        sa.Column("structured_content", postgresql.JSONB, nullable=True),
        sa.Column("text_content", sa.Text, nullable=True),
        sa.Column("storage_key", sa.String(1024), nullable=True),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_outputs_job_id", "outputs", ["job_id"])
    op.create_index("ix_outputs_status", "outputs", ["status"])

    # ------------------------------------------------------------------
    # verification_results
    # ------------------------------------------------------------------
    op.create_table(
        "verification_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "output_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outputs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "overall_status",
            sa.String(50),
            nullable=False,
            server_default="warning",
        ),
        sa.Column(
            "grounding_score",
            sa.Numeric(precision=5, scale=4),
            nullable=True,
        ),
        sa.Column(
            "consistency_score",
            sa.Numeric(precision=5, scale=4),
            nullable=True,
        ),
        sa.Column("claims_checked", sa.Integer, nullable=True),
        sa.Column("claims_supported", sa.Integer, nullable=True),
        sa.Column("warnings", postgresql.JSONB, nullable=True),
        sa.Column("details", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_verification_results_output_id",
        "verification_results",
        ["output_id"],
    )


def downgrade() -> None:
    op.drop_table("verification_results")
    op.drop_table("outputs")
    op.drop_table("transformation_jobs")
    op.drop_table("generation_configurations")
    op.drop_table("source_chunks")
    op.drop_table("sources")
    op.drop_table("projects")
    op.drop_table("users")
    # Note: we do NOT drop the vector extension — it may be used by other schemas.
