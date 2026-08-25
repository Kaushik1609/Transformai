"""Phase 3E: convert source_chunks.embedding from TEXT to VECTOR(1536)

Revision ID: 0002_phase3e_embedding_vector
Revises: 0001_initial_schema
Create Date: 2026-08-25 00:00:00.000000

Requirements:
- Preserve NULL embeddings as NULL.
- Do not silently coerce arbitrary legacy text into vector data.
- If any non-null legacy value cannot be converted safely, fail the migration.
- No vector indexes or retrieval logic are added in this phase.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_phase3e_embedding_vector"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def _safe_vector_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parts = [part.strip() for part in stripped.strip("[](){}").split(",")]
        cleaned = [part for part in parts if part]
        if not cleaned:
            return None
        for part in cleaned:
            float(part)
    except ValueError as exc:  # pragma: no cover - migration safety check
        raise ValueError(f"Legacy embedding value is not a valid vector literal: {value!r}") from exc
    return stripped


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, embedding FROM source_chunks WHERE embedding IS NOT NULL")).fetchall()
    for row in rows:
        _safe_vector_text(row[1])

    op.execute(
        "ALTER TABLE source_chunks ALTER COLUMN embedding TYPE VECTOR(1536) USING CASE "
        "WHEN embedding IS NULL THEN NULL "
        "ELSE CAST(embedding AS VECTOR(1536)) END"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE source_chunks ALTER COLUMN embedding TYPE TEXT USING CASE "
        "WHEN embedding IS NULL THEN NULL "
        "ELSE CAST(embedding AS TEXT) END"
    )
