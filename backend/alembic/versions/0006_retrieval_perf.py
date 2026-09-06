"""Phase 11J-C: retrieval performance indexes.

Revision ID: 0006_retrieval_perf
Revises: 0005_phase11f_user_mobile_number
Create Date: 2026-09-06 00:00:00.000000

Adds two PostgreSQL/pgvector indexes to ``source_chunks`` to support exact
cosine retrieval pushdown (Phase 11J-C):

1. Composite B-tree ``(source_id, chunk_index)`` — fast scoped candidate
   fetch by ``source_id`` (matching the existing SQL-level project/source
   isolation filters) with a deterministic ``chunk_index`` tie-break, and the
   same read pattern used by the embedding worker.

2. HNSW index on ``embedding vector_cosine_ops`` — capacity infrastructure.
   Retrieval continues to use EXACT pgvector ordering (``embedding <-> query``),
   never approximate ANN search, unless a future phase explicitly opts in.

This migration is PostgreSQL-only: it depends on the ``vector`` extension
enabled by ``0002_phase3e_embedding_vector`` and on pgvector >= 0.5.0 for the
HNSW access method (the deployment uses pgvector 0.8.6). The embedding column
type, dimension, primary key, existing indexes, and data are untouched.
"""

from alembic import op

revision = "0006_retrieval_perf"
down_revision = "0005_phase11f_user_mobile_number"
branch_labels = None
depends_on = None

_COMPOSITE_INDEX = "ix_source_chunks_source_id_chunk_index"
_HNSW_INDEX = "ix_source_chunks_embedding_hnsw"


def upgrade() -> None:
    op.create_index(
        _COMPOSITE_INDEX,
        "source_chunks",
        ["source_id", "chunk_index"],
        if_not_exists=True,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        f"{_HNSW_INDEX} ON source_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_HNSW_INDEX}")
    op.drop_index(_COMPOSITE_INDEX, table_name="source_chunks", if_exists=True)