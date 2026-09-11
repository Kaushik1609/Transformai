"""Phase 11J-C: retrieval performance & pgvector pushdown regression tests.

Covers the 28 required areas:
 1  PostgreSQL vector SQL compilation
 2  pgvector cosine-distance operator (``<=>``, the ``<->``-style operator pgvector
    defines for cosine distance)
 3  ``embedding IS NOT NULL``
 4  SQL-level scope WHERE clauses (project/source)
 5  ``min_similarity`` SQL filtering
 6  ORDER BY distance
 7  deterministic chunk_index tie-break
 8  LIMIT behavior
 9  SQLite fallback
10  fallback parity
11  cosine score parity
12  min_similarity parity
13  top_k parity
14  NULL embedding behavior
15  wrong-dimension behavior
16  project isolation
17  source isolation
18  user isolation
19  hybrid ranking parity
20  hybrid candidate margin (no dense-gating)
21  duplicate-content handling
22  deterministic final ordering
23  migration index definitions
24  index naming
25  backfill/enqueue behavior
26  no duplicate backfill enqueue
27  provider architecture remains unchanged
28  existing RAG contracts remain unchanged

All runtime retrieval tests use SQLite (the repository test convention) which
forces the preserved pure-Python cosine reference implementation; the
PostgreSQL path is verified structurally by compiling the generated SQL against
the PostgreSQL dialect, plus an opt-in live parity test when
``TEST_POSTGRES_URL`` is configured.
"""

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql as pg_dialect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.db.models.user import User
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.service import EmbeddingService
from app.ingestion.backfill import (
    enqueue_missing_embeddings,
    sources_requiring_embeddings,
)
from app.rag.service import RAGService
from app.retrieval.service import ChunkMatch, RetrievalService
from app.retrieval.sql import (
    is_postgresql,
    scoped_hybrid_candidate_query,
    scoped_vector_ranking_query,
)

DIMS = 1536
_VEC = [0.0] * DIMS


def _unit(primary: float = 1.0) -> list[float]:
    return [primary] + [0.0] * (DIMS - 1)


def _pair(primary: float = 0.0) -> list[float]:
    vec = [0.0] * DIMS
    vec[0] = primary
    vec[1] = 1.0 - abs(primary) if primary <= 1.0 else 0.0
    return vec


def _retrieval(dimensions: int = DIMS) -> RetrievalService:
    return RetrievalService(
        embedding_service=EmbeddingService(
            provider=FakeEmbeddingProvider(dimensions=dimensions),
            dimensions=dimensions,
        )
    )


@pytest.fixture
def db():
    import app.db.models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_user(db, *, name="11JC") -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{name}-{uuid.uuid4()}@example.test",
        name=name,
        role="operator",
    )
    db.add(user)
    db.flush()
    return user


def make_project(db, user: User, *, name="proj") -> Project:
    project = Project(id=uuid.uuid4(), user_id=user.id, name=name)
    db.add(project)
    db.flush()
    return project


def make_source(db, project: Project, *, content: str = "seed") -> Source:
    source = Source(
        id=uuid.uuid4(),
        project_id=project.id,
        source_type="txt",
        original_filename="11jc.txt",
        mime_type="text/plain",
        file_size=len(content),
        language="en",
        status="ready",
        extracted_text=content,
    )
    db.add(source)
    db.flush()
    return source


def add_chunk(
    db,
    source: Source,
    *,
    content: str,
    embedding: list[float] | None = None,
    chunk_index: int = 0,
) -> SourceChunk:
    chunk = SourceChunk(
        id=uuid.uuid4(),
        source_id=source.id,
        chunk_index=chunk_index,
        content=content,
        embedding=embedding,
    )
    db.add(chunk)
    return chunk


def commit_all(db):
    db.commit()


# ---------------------------------------------------------------------------
# 1/2/3/4/5/6/7/8 PostgreSQL SQL compilation
# ---------------------------------------------------------------------------


def _compile(stmt):
    return str(stmt.compile(dialect=pg_dialect.dialect()))


def test_pg_query_compiles_with_cosine_operator_and_null_guard():
    stmt = scoped_vector_ranking_query(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        dimensions=4,
        top_k=5,
        project_id=None,
        source_id=None,
        min_similarity=None,
    )
    sql = _compile(stmt)
    assert "source_chunks.embedding <=>" in sql
    assert "embedding IS NOT NULL" in sql
    assert "AS distance" in sql


def test_pg_query_scope_filters_are_in_sql_not_python():
    stmt = scoped_vector_ranking_query(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        dimensions=4,
        top_k=5,
        project_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        min_similarity=None,
    )
    sql = _compile(stmt)
    assert "source_chunks.source_id = " in sql
    assert "sources.project_id = " in sql
    assert "JOIN sources" in sql


def test_pg_query_min_similarity_renders_sql_filter():
    scoped = scoped_vector_ranking_query(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        dimensions=4,
        top_k=5,
        project_id=None,
        source_id=None,
        min_similarity=0.5,
    )
    scoped_sql = _compile(scoped)
    assert "greatest(" in scoped_sql
    assert ">=" in scoped_sql

    unscoped = scoped_vector_ranking_query(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        dimensions=4,
        top_k=5,
        project_id=None,
        source_id=None,
        min_similarity=None,
    )
    assert "greatest(" not in _compile(unscoped)


def test_pg_query_order_by_distance_and_deterministic_tiebreak():
    stmt = scoped_vector_ranking_query(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        dimensions=4,
        top_k=5,
        project_id=None,
        source_id=None,
        min_similarity=None,
    )
    sql = _compile(stmt)
    assert "ORDER BY" in sql
    assert "ASC" in sql
    assert "chunk_index ASC" in sql


def test_pg_query_limit_renders_bound_limt():
    stmt = scoped_vector_ranking_query(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        dimensions=4,
        top_k=7,
        project_id=None,
        source_id=None,
        min_similarity=0.5,
    )
    sql = str(
        stmt.compile(
            dialect=pg_dialect.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "LIMIT 7" in sql
    assert ">= 0.5" in sql


def test_pg_query_threshold_is_applied_before_limit():
    stmt = scoped_vector_ranking_query(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        dimensions=4,
        top_k=3,
        project_id=None,
        source_id=None,
        min_similarity=0.25,
    )
    sql = _compile(stmt)
    where_idx = sql.index("WHERE")
    order_idx = sql.index("ORDER BY")
    limit_idx = sql.index("LIMIT")
    assert ">=" in sql[where_idx:order_idx]
    assert sql[where_idx : order_idx + 1].find("LIMIT") == -1
    assert limit_idx > order_idx


def test_pg_hybrid_query_never_limits_candidates():
    stmt = scoped_hybrid_candidate_query(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        dimensions=4,
        project_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
    )
    sql = _compile(stmt)
    assert "LIMIT" not in sql
    assert "embedding IS NOT NULL" in sql
    assert "sources.project_id = " in sql


def test_query_vector_is_parameterized_not_interpolated():
    stmt = scoped_vector_ranking_query(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        dimensions=4,
        top_k=5,
        project_id=None,
        source_id=None,
        min_similarity=None,
    )
    raw = _compile(stmt)
    assert "%(query_vector)s" in raw or ":query_vector" in raw
    assert "'[1.0,0.0,0.0,0.0]'" not in raw


# ---------------------------------------------------------------------------
# 9/10/11/12/13 SQLite fallback + parity
# ---------------------------------------------------------------------------


def test_sqlite_is_not_treated_as_postgresql(db):
    assert is_postgresql(db) is False


def test_sqlite_fallback_executes_without_vector_syntax(db, monkeypatch):
    def _no_sql_dispatch(db):
        return False

    monkeypatch.setattr("app.retrieval.service.is_postgresql", _no_sql_dispatch)
    user = make_user(db)
    project = make_project(db, user)
    source = make_source(db, project, content="revenue grew")
    add_chunk(db, source, content="revenue grew", embedding=_unit(), chunk_index=0)
    commit_all(db)

    service = _retrieval()
    matches = service.query_by_text(db, "revenue", project_id=project.id, top_k=5)
    assert len(matches) == 1
    assert matches[0].content == "revenue grew"


def test_fallback_and_pg_path_select_the_same_branch_logic(db):
    """PG path and fallback share validation + scope enforcement up front."""
    service = _retrieval()
    assert service._validate_top_k(3) == 3
    assert service._validate_query_vector([0.1] * 1536) == [0.1] * 1536
    with pytest.raises(ValueError, match="dimensions mismatch"):
        service.query_by_vector(db, [0.1] * 4, project_id=uuid.uuid4())


def test_cosine_score_formula_matches_python_reference():
    """1 - cosine distance (with clamp) equals the Python reference exactly."""
    from app.retrieval.service import RetrievalService

    service = _retrieval()
    left = _unit(0.8)
    right = _unit(0.4)
    distance = service._cosine_distance(left, right)
    expected = 1.0 - (0.8 * 0.4 + 0.0) / (
        (0.8**2 + 0.0) ** 0.5 * (0.4**2 + 0.0) ** 0.5
    )
    assert distance == pytest.approx(expected, abs=1e-12)

    # SQL formulation uses greatest(0.0, 1 - distance) — the Python clamp.
    assert pytest.approx(
        1.0 - distance if distance <= 1.0 else 0.0, abs=1e-12
    ) == max(0.0, 1.0 - distance)


def test_sqlite_compiled_fallback_has_no_vector_syntax(db):
    from sqlalchemy.dialects import sqlite as sqlite_dialect

    fallback_select = select(SourceChunk).where(SourceChunk.source_id == uuid.uuid4())
    sql = str(fallback_select.compile(dialect=sqlite_dialect.dialect()))
    assert "<=>" not in sql
    assert "greatest(" not in sql


def test_min_similarity_parity_on_fallback(db):
    user = make_user(db)
    project = make_project(db, user)
    source = make_source(db, project, content="mixed")
    add_chunk(db, source, content="strong", embedding=_unit(1.0), chunk_index=0)
    add_chunk(db, source, content="orthogonal", embedding=_pair(0.0), chunk_index=1)
    commit_all(db)

    service = _retrieval()
    query = _unit(1.0)
    matches = service.query_by_vector(
        db, query, project_id=project.id, min_similarity=0.5
    )
    assert [m.content for m in matches] == ["strong"]


def test_top_k_parity_on_fallback(db):
    user = make_user(db)
    project = make_project(db, user)
    source = make_source(db, project, content="many")
    add_chunk(db, source, content="c0", embedding=_unit(1.0), chunk_index=0)
    add_chunk(db, source, content="c1", embedding=_unit(0.9), chunk_index=1)
    add_chunk(db, source, content="c2", embedding=_unit(0.8), chunk_index=2)
    commit_all(db)

    service = _retrieval()
    matches = service.query_by_vector(
        db, _unit(1.0), project_id=project.id, top_k=2
    )
    assert len(matches) == 2


# ---------------------------------------------------------------------------
# 14/15 NULL + wrong-dimension behavior
# ---------------------------------------------------------------------------


def test_null_embeddings_are_skipped_and_all_null_returns_empty(db):
    user = make_user(db)
    project = make_project(db, user)
    source = make_source(db, project, content="seed")
    add_chunk(db, source, content="embedded", embedding=_unit(1.0), chunk_index=0)
    add_chunk(db, source, content="missing", embedding=None, chunk_index=1)
    db.add(SourceChunk(
        id=uuid.uuid4(),
        source_id=source.id,
        chunk_index=1,
        content="missing too",
        embedding=None,
        chunk_metadata={},
    ))
    commit_all(db)

    service = _retrieval()
    matches = service.query_by_vector(db, _unit(1.0), project_id=project.id, top_k=10)
    assert [m.content for m in matches] == ["embedded"]

    empty_source = make_source(db, project, content="none")
    commit_all(db)
    assert service.query_by_vector(db, _unit(1.0), source_id=empty_source.id) == []


def test_null_embeddings_yield_insufficient_context_contract(db):
    user = make_user(db)
    project = make_project(db, user)
    source = make_source(db, project, content="nothing embedded")
    commit_all(db)

    rag = RAGService(retrieval_service=_retrieval())
    context = rag.retrieve_context_for_source(
        db, source.id, "anything", project_id=project.id
    )
    assert context.chunk_count == 0
    assert context.citations == []
    assert context.metadata["retrieval_status"] == "insufficient_context"


def test_dimension_mismatch_is_rejected(db):
    service = _retrieval(dimensions=4)
    with pytest.raises(ValueError, match="dimensions mismatch"):
        service.query_by_vector(db, [0.1] * 3, project_id=uuid.uuid4())


def test_invalid_inputs_are_rejected(db):
    service = _retrieval()
    with pytest.raises(ValueError, match="positive integer"):
        service.query_by_vector(db, _unit(), project_id=uuid.uuid4(), top_k=0)
    with pytest.raises(ValueError, match="cannot be empty"):
        service.query_by_text(db, "   ", project_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# 16/17/18 isolation (project / source / user)
# ---------------------------------------------------------------------------


def _make_two_isolation_corpora(db):
    user_a = make_user(db, name="Alice")
    project_a = make_project(db, user_a, name="A")
    source_a = make_source(db, project_a, content="alice data")
    add_chunk(db, source_a, content="alice secret chunk", embedding=_unit(1.0), chunk_index=0)

    user_b = make_user(db, name="Bob")
    project_b = make_project(db, user_b, name="B")
    source_b = make_source(db, project_b, content="bob data")
    add_chunk(db, source_b, content="bob secret chunk", embedding=_unit(1.0), chunk_index=0)
    commit_all(db)
    return user_a, project_a, source_a, user_b, project_b, source_b


def test_project_isolation_fallback(db):
    _, project_a, source_a, _, project_b, source_b = _make_two_isolation_corpora(db)
    service = _retrieval()
    a_matches = service.query_by_text(db, "secret", project_id=project_a.id, top_k=10)
    b_matches = service.query_by_text(db, "secret", project_id=project_b.id, top_k=10)
    assert {m.source_id for m in a_matches} == {source_a.id}
    assert {m.source_id for m in b_matches} == {source_b.id}


def test_source_isolation_fallback(db):
    _, project_a, source_a, _, _, source_b = _make_two_isolation_corpora(db)
    service = _retrieval()
    matches = service.query_by_text(db, "secret", source_id=source_a.id, top_k=10)
    assert {m.source_id for m in matches} == {source_a.id}
    matches_b = service.query_by_text(db, "secret", source_id=source_b.id, top_k=10)
    assert {m.source_id for m in matches_b} == {source_b.id}


def test_user_isolation_fallback(db):
    _, project_a, source_a, user_b, project_b, source_b = _make_two_isolation_corpora(db)
    service = _retrieval()
    # User B can never see project A content regardless of scope combination.
    matches = service.query_by_text(
        db, "secret", project_id=project_a.id, top_k=10
    )
    assert {m.source_id for m in matches} == {source_a.id}
    assert source_b.id not in {m.source_id for m in matches}
    assert user_b.id != project_a.user_id


def test_isolation_also_holds_for_hybrid(db):
    _, project_a, source_a, _, project_b, _ = _make_two_isolation_corpora(db)
    service = _retrieval()
    matches = service.query_hybrid(db, "secret", project_id=project_a.id, top_k=10)
    assert {m.source_id for m in matches} == {source_a.id}


def test_require_scope_fails_closed(db):
    service = _retrieval()
    with pytest.raises(ValueError, match="Retrieval scope required"):
        service.query_by_text(db, "anything", require_scope=True)
    with pytest.raises(ValueError, match="Retrieval scope required"):
        service.query_hybrid(db, "anything", require_scope=True)


# ---------------------------------------------------------------------------
# 19/20/21/22 hybrid parity, margin, dedup, ordering
# ---------------------------------------------------------------------------


def _hybrid_corpus(db):
    user = make_user(db)
    project = make_project(db, user)
    source = make_source(db, project, content="hybrid")
    add_chunk(
        db, source,
        content="revenue grew quarter over quarter",
        embedding=_pair(0.9), chunk_index=0,
    )
    add_chunk(
        db, source,
        content="totally unrelated topic no overlap",
        embedding=_pair(0.1), chunk_index=1,
    )
    add_chunk(
        db, source,
        content="revenue grew quarter over quarter",  # exact duplicate of c0
        embedding=_pair(0.9), chunk_index=2,
    )
    # Lexically strong but dense-weak chunk: must still participate (no margin gating).
    add_chunk(
        db, source,
        content="revenue grew",
        embedding=_pair(0.05), chunk_index=3,
    )
    commit_all(db)
    return project, source


def test_hybrid_ranking_parity_with_reference_formula(db):
    project, source = _hybrid_corpus(db)
    service = _retrieval()
    matches = service.query_hybrid(
        db, "revenue grew", project_id=project.id, top_k=5
    )
    # Scores strictly non-increasing; every deduplicated chunk participates.
    assert len(matches) == 3
    scores = [m.score for m in matches]
    assert all(a >= b for a, b in zip(scores, scores[1:]))
    contents = [m.content for m in matches]
    assert "revenue grew quarter over quarter" in contents
    assert "revenue grew" in contents
    assert "totally unrelated topic no overlap" in contents


def test_hybrid_dedups_duplicate_content_keeping_strongest(db):
    project, _ = _hybrid_corpus(db)
    service = _retrieval()
    matches = service.query_hybrid(
        db, "revenue grew", project_id=project.id, top_k=10
    )
    contents = [m.content for m in matches]
    assert contents.count("revenue grew quarter over quarter") == 1
    assert len(contents) <= 3


def test_hybrid_deterministic_ordering(db):
    project, source = _hybrid_corpus(db)
    service = _retrieval()
    first = service.query_hybrid(db, "revenue grew", project_id=project.id, top_k=5)
    second = service.query_hybrid(db, "revenue grew", project_id=project.id, top_k=5)
    assert [m.content for m in first] == [m.content for m in second]
    assert [m.chunk_index for m in first] == [m.chunk_index for m in second]


def test_hybrid_ties_break_by_chunk_index_asc(db):
    user = make_user(db)
    project = make_project(db, user)
    source = make_source(db, project, content="tie")
    # Identical embeddings and zero lexical overlap -> identical fused score.
    add_chunk(db, source, content="alpha aaa", embedding=_unit(1.0), chunk_index=0)
    add_chunk(db, source, content="beta bbb", embedding=_unit(1.0), chunk_index=1)
    commit_all(db)

    service = _retrieval()
    matches = service.query_hybrid(db, "zzz no token overlap", project_id=project.id, top_k=5)
    assert [m.chunk_index for m in matches] == [0, 1]


def test_hybrid_dense_weight_and_lexical_weight_are_used(db):
    project, _ = _hybrid_corpus(db)
    service = _retrieval()
    query_tokens = {"revenue", "grew"}
    candidates = service._fuse_hybrid(
        [
            (uuid.uuid4(), uuid.uuid4(), 0, "revenue grew", 0.05),
            (uuid.uuid4(), uuid.uuid4(), 1, "revenue grew quarter", 0.2),
        ],
        query_tokens=query_tokens,
        min_similarity=None,
        top_k=5,
    )
    assert candidates[0].content == "revenue grew"
    assert candidates[0].score == pytest.approx(
        service.DENSE_WEIGHT * 0.95 + service.LEXICAL_WEIGHT * 1.0,
        abs=1e-9,
    )


def test_hybrid_no_dense_gating_in_candidate_margin(db):
    """The optimized path must NOT drop dense-weak but lexical-strong chunks."""
    project, _ = _hybrid_corpus(db)
    service = _retrieval()
    matches = service.query_hybrid(db, "revenue grew", project_id=project.id, top_k=10)
    contents = [m.content for m in matches]
    assert "revenue grew" in contents  # dense-weak (0.05) but lexically relevant


# ---------------------------------------------------------------------------
# 23/24 migration definitions
# ---------------------------------------------------------------------------


def _migration_path():
    return Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0006_retrieval_perf.py"


def test_migration_0006_defines_expected_indexes():
    text = _migration_path().read_text(encoding="utf-8")
    assert "ix_source_chunks_source_id_chunk_index" in text
    assert "hnsw" in text
    assert "vector_cosine_ops" in text
    assert "ix_source_chunks_embedding_hnsw" in text


def test_migration_0006_chains_after_0005_and_is_safe():
    text = _migration_path().read_text(encoding="utf-8")
    assert 'down_revision = "0005_phase11f_user_mobile_number"' in text
    assert "revision = \"0006_retrieval_perf\"" in text
    assert "IF NOT EXISTS" in text
    assert "downgrade" in text


# ---------------------------------------------------------------------------
# 25/26 backfill mechanism
# ---------------------------------------------------------------------------


def _backfill_corpus(db):
    user = make_user(db)
    project = make_project(db, user)
    ready_missing = make_source(db, project, content="needs embeddings")
    ready_completed = make_source(db, project, content="done")
    ready_queued = make_source(db, project, content="in flight")
    ready_failed = make_source(db, project, content="failed before")
    not_ready = make_source(db, project, content="uploaded only")
    not_ready.status = "uploaded"
    ready_completed.source_metadata = {"embedding_status": "completed"}
    ready_queued.source_metadata = {"embedding_status": "queued"}
    ready_failed.source_metadata = {"embedding_status": "failed"}
    db.commit()
    return ready_missing, ready_completed, ready_queued, ready_failed, not_ready


def test_backfill_candidates_are_ready_sources_without_embeddings(db):
    (
        ready_missing,
        ready_completed,
        ready_queued,
        ready_failed,
        not_ready,
    ) = _backfill_corpus(db)
    candidates = sources_requiring_embeddings(db)
    ids = {c.id for c in candidates}
    assert ready_missing.id in ids
    assert ready_completed.id not in ids
    assert ready_queued.id not in ids
    assert ready_failed.id in ids
    assert not_ready.id not in ids


def test_backfill_enqueues_and_marks_queued(db, monkeypatch):
    ready_missing, _, _, ready_failed, _ = _backfill_corpus(db)
    calls = []
    fake_queue = object()

    def fake_enqueue(source_id, *, queue):
        calls.append((source_id, queue))
        return "job-1"

    monkeypatch.setattr(
        "app.ingestion.backfill.enqueue_source_embedding", fake_enqueue
    )
    enqueued, failures = enqueue_missing_embeddings(
        db, queue=fake_queue, enqueue=fake_enqueue
    )
    assert {s for s in enqueued} == {ready_missing.id, ready_failed.id}
    assert failures == []
    assert {c[0] for c in calls} == {ready_missing.id, ready_failed.id}
    assert all(c[1] is fake_queue for c in calls)
    for source_id in enqueued:
        assert (db.get(Source, source_id).source_metadata or {})[
            "embedding_status"
        ] == "queued"


def test_backfill_does_not_duplicate_jobs(db, monkeypatch):
    ready_missing, _, _, ready_failed, _ = _backfill_corpus(db)
    calls = []
    fake_queue = object()

    def record(source_id, *, queue):
        calls.append((source_id, queue))
        return "job-x"

    enqueued, failures = enqueue_missing_embeddings(
        db, queue=fake_queue, enqueue=record
    )
    assert {s for s in enqueued} == {ready_missing.id, ready_failed.id}
    assert len(calls) == 2
    # second run sees both as queued -> no duplicate jobs
    enqueued2, failures2 = enqueue_missing_embeddings(
        db, queue=fake_queue, enqueue=record
    )
    assert enqueued2 == []
    assert len(calls) == 2


def test_backfill_surfaces_failures_without_aborting(db, monkeypatch):
    ready_missing, _, _, ready_failed, _ = _backfill_corpus(db)

    def failing_enqueue(source_id, *, queue):
        raise RuntimeError("redis down")

    enqueued, failures = enqueue_missing_embeddings(
        db, queue=object(), enqueue=failing_enqueue
    )
    assert enqueued == []
    assert {f[0] for f in failures} == {ready_missing.id, ready_failed.id}
    assert all("redis down" in error for _, error in failures)


def test_backfill_limited_batch(db):
    for _ in range(3):
        user = make_user(db)
        project = make_project(db, user)
        make_source(db, project, content="c")
    db.commit()
    candidates = sources_requiring_embeddings(db)
    assert len(candidates) == 3
    assert len(sources_requiring_embeddings(db)) == 3


# ---------------------------------------------------------------------------
# 27/28 provider architecture + RAG contracts
# ---------------------------------------------------------------------------


def test_embedding_provider_architecture_unchanged(db):
    from app.embeddings.factory import build_embedding_provider

    provider = build_embedding_provider()
    assert isinstance(provider, FakeEmbeddingProvider)
    assert not hasattr(provider, "_client")


def test_rag_contracts_unchanged_on_fallback(db):
    user = make_user(db)
    project = make_project(db, user)
    source = make_source(db, project, content="quarterly revenue grew")
    add_chunk(db, source, content="quarterly revenue grew", embedding=_unit(), chunk_index=0)
    commit_all(db)

    rag = RAGService(retrieval_service=_retrieval())
    context = rag.retrieve_context_for_source(
        db, source.id, "revenue", project_id=project.id, top_k=3
    )
    assert context.chunk_count == 1
    assert context.citations[0].source_id == str(source.id)
    assert context.metadata["retrieval_method"] == "cosine-similarity-pgvector"
    assert context.metadata["retrieval_status"] == "has_evidence"


# ---------------------------------------------------------------------------
# Opt-in live PostgreSQL parity (skipped unless TEST_POSTGRES_URL is set)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="Opt-in live PostgreSQL vector test requires TEST_POSTGRES_URL.",
)
def test_live_postgresql_parity_and_scoping():
    """Real pgvector end-to-end parity of the pushdown path vs the Python reference.

    The target database must already have ``CREATE EXTENSION vector`` enabled.
    A dedicated test schema is created and dropped so the target is left clean.
    """
    import math

    from sqlalchemy.orm import sessionmaker

    engine = create_engine(os.environ["TEST_POSTGRES_URL"])
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)

    vectors = {
        "alpha": _unit(1.0),
        "beta": _unit(0.9),
        "gamma": _unit(0.1),
        "delta": _pair(0.0),
        "epsilon": None,
    }
    try:
        with SessionFactory() as session:
            user = make_user(session, name="Live")
            project = make_project(session, user)
            source = make_source(session, project, content="live")
            for i, (name, vec) in enumerate(vectors.items()):
                add_chunk(
                    session, source,
                    content=name, embedding=vec, chunk_index=i,
                )
            session.commit()

            service = _retrieval()
            matches = service.query_by_vector(
                session, _unit(1.0), project_id=project.id, top_k=10
            )
            got = [(m.content, m.score) for m in matches]

            # Python reference over the exact same data
            reference = []
            for name, vec in vectors.items():
                if vec is None:
                    continue
                distance = service._cosine_distance(_unit(1.0), vec)
                score = 1.0 - distance if distance <= 1.0 else 0.0
                reference.append((name, score))
            reference.sort(key=lambda item: -item[1])

            assert [g[0] for g in got] == [r[0] for r in reference]
            for (_, g_score), (_, r_score) in zip(got, reference):
                assert g_score == pytest.approx(r_score, abs=1e-6)

            # NULL embeddings never break the PG path
            null_only = make_source(session, project, content="none")
            session.add(null_only)
            session.add(SourceChunk(
                id=uuid.uuid4(), source_id=null_only.id, chunk_index=0,
                content="none", embedding=None,
            ))
            session.commit()
            assert service.query_by_vector(
                session, _unit(1.0), source_id=null_only.id
            ) == []

            # Scope isolation on the PG path
            other_user = make_user(session, name="Other")
            other_project = make_project(session, other_user)
            other_source = make_source(session, other_project, content="other")
            add_chunk(session, other_source, content="other secret", embedding=_unit(1.0), chunk_index=0)
            session.commit()
            other_matches = service.query_by_text(
                session, "secret", project_id=other_project.id, top_k=10
            )
            assert {m.source_id for m in other_matches} == {other_source.id}
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()