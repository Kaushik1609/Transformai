"""Phase 4: canonical content and provenance."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_phase4_content_intelligence"
down_revision = "0002_phase3e_embedding_vector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "canonical_contents",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("source_id", uuid_type, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", uuid_type, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("title", sa.String(length=512)),
        sa.Column("summary", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("topics", postgresql.JSONB(), nullable=False),
        sa.Column("entities", postgresql.JSONB(), nullable=False),
        sa.Column("key_points", postgresql.JSONB(), nullable=False),
        sa.Column("claims", postgresql.JSONB(), nullable=False),
        sa.Column("statistics", postgresql.JSONB(), nullable=False),
        sa.Column("dates", postgresql.JSONB(), nullable=False),
        sa.Column("recommendations", postgresql.JSONB(), nullable=False),
        sa.Column("source_references", postgresql.JSONB(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_id", name="uq_canonical_contents_source_id"),
    )
    op.create_index("ix_canonical_contents_source_id", "canonical_contents", ["source_id"])
    op.create_index("ix_canonical_contents_project_id", "canonical_contents", ["project_id"])
    op.create_index("ix_canonical_contents_status", "canonical_contents", ["status"])
    op.create_table(
        "content_analysis_traces",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("canonical_content_id", uuid_type, sa.ForeignKey("canonical_contents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", uuid_type, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_chunk_id", uuid_type, sa.ForeignKey("source_chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.String(length=50), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer()),
        sa.Column("evidence", sa.Text()),
    )
    op.create_index("ix_content_analysis_traces_canonical_content_id", "content_analysis_traces", ["canonical_content_id"])
    op.create_index("ix_content_analysis_traces_source_id", "content_analysis_traces", ["source_id"])
    op.create_index("ix_content_analysis_traces_source_chunk_id", "content_analysis_traces", ["source_chunk_id"])


def downgrade() -> None:
    op.drop_table("content_analysis_traces")
    op.drop_table("canonical_contents")
