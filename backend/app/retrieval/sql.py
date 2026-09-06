"""PostgreSQL/pgvector SQL layer for exact cosine retrieval (Phase 11J-C).

Isolates every PostgreSQL-specific vector expression from
``app.retrieval.service.RetrievalService`` so that:

* On PostgreSQL the service ranks with the native pgvector cosine-distance
  operator ``embedding <-> query_vector`` (exact ordering; the HNSW index added
  by migration ``0006_retrieval_perf`` is capacity infrastructure and is never
  used to silently switch to approximate ANN search).
* On any other dialect (SQLite in tests, etc.) the original pure-Python cosine
  implementation in ``RetrievalService`` remains the active path.

Every query keeps the same security boundary as the Python path: project and
source scope are enforced in SQL (never by post-filtering fetched rows), all
values are bound parameters (no client-supplied SQL), and ``embedding IS NOT
NULL`` is always applied.
"""

from __future__ import annotations

from typing import Sequence
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Select, bindparam, func, literal, select
from sqlalchemy.orm import Session

from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk


def is_postgresql(db: Session) -> bool:
    """Return True when the session's bind supports PostgreSQL vector operators."""
    dialect_name = db.get_bind().dialect.name
    return dialect_name.startswith("postgres")


def _query_vector_bind(query_vector: Sequence[float], dimensions: int) -> bindparam:
    """Build a typed, parameterized pgvector literal for the query embedding.

    The ``Vector(dimensions)`` type instructs the PostgreSQL driver to serialize
    the list as a bound ``vector`` value, so the operand is never interpolated
    into SQL text. Dimensions are validated before this function is called.
    """
    return bindparam(
        "query_vector",
        value=[float(value) for value in query_vector],
        type_=Vector(dimensions),
    )


def cosine_distance_expr(query_vector: Sequence[float], dimensions: int):
    """pgvector cosine distance ``1 - cosine_similarity`` (the ``<->`` operator)."""
    return SourceChunk.embedding.cosine_distance(_query_vector_bind(query_vector, dimensions))


def cosine_score_expr(query_vector: Sequence[float], dimensions: int):
    """Cosine similarity with the same clamp used by ``RetrievalService``.

    Python semantics: ``score = 1 - distance if distance <= 1 else 0.0``.
    pgvector cosine distance can reach 2.0, so the SQL score is clamped with
    ``greatest(0.0, 1 - distance)`` to keep filter parity at the boundary.
    """
    return func.greatest(literal(0.0), 1.0 - cosine_distance_expr(query_vector, dimensions))


def scoped_vector_ranking_query(
    *,
    query_vector: Sequence[float],
    dimensions: int,
    top_k: int,
    project_id: UUID | None,
    source_id: UUID | None,
    min_similarity: float | None,
) -> Select:
    """Exact top-K vector query with SQL-level scope and threshold filtering.

    Conceptual shape (all clauses preserved from the Python path):

        SELECT id, source_id, chunk_index, content, (embedding <-> :q) AS distance
        FROM source_chunks
        JOIN sources WHERE scope filters         -- project/source isolation in SQL
        WHERE embedding IS NOT NULL
          AND greatest(0.0, 1 - (embedding <-> :q)) >= :min_similarity
        ORDER BY distance ASC, chunk_index ASC   -- deterministic contract
        LIMIT :top_k

    The ``chunk_index ASC`` tie-break mirrors the deterministic ordering the
    RAG service applies when assembling context (strongest evidence first, ties
    by chunk order).
    """
    distance_expr = cosine_distance_expr(query_vector, dimensions)
    score_expr = cosine_score_expr(query_vector, dimensions)

    stmt = (
        select(
            SourceChunk.id,
            SourceChunk.source_id,
            SourceChunk.chunk_index,
            SourceChunk.content,
            distance_expr.label("distance"),
        )
        .where(SourceChunk.embedding.is_not(None))
        .order_by(distance_expr.asc(), SourceChunk.chunk_index.asc())
        .limit(top_k)
    )

    if source_id is not None:
        stmt = stmt.where(SourceChunk.source_id == source_id)

    if project_id is not None:
        stmt = stmt.join(Source, SourceChunk.source_id == Source.id).where(
            Source.project_id == project_id
        )

    if min_similarity is not None:
        stmt = stmt.where(score_expr >= literal(float(min_similarity)))

    return stmt


def scoped_hybrid_candidate_query(
    *,
    query_vector: Sequence[float],
    dimensions: int,
    project_id: UUID | None,
    source_id: UUID | None,
) -> Select:
    """All scoped candidates with their exact dense distance for hybrid fusion.

    Hybrid retrieval fuses dense cosine with lexical token overlap in Python
    over the FULL scoped candidate set (identical to the reference
    implementation, which also evaluates every candidate). Dense distance is
    computed by PostgreSQL; lexical scoring, weighting, deduplication and
    ordering remain unchanged in Python so hybrid semantics are preserved
    exactly.
    """
    distance_expr = cosine_distance_expr(query_vector, dimensions)

    stmt = select(
        SourceChunk.id,
        SourceChunk.source_id,
        SourceChunk.chunk_index,
        SourceChunk.content,
        distance_expr.label("distance"),
    ).where(SourceChunk.embedding.is_not(None))

    if source_id is not None:
        stmt = stmt.where(SourceChunk.source_id == source_id)

    if project_id is not None:
        stmt = stmt.join(Source, SourceChunk.source_id == Source.id).where(
            Source.project_id == project_id
        )

    return stmt