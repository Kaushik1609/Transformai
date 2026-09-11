"""Phase 11G — Real embeddings & RAG quality.

Verifies the configurable embedding-provider architecture:

  1.  Fake provider compatibility / determinism
  2.  Provider factory defaults to fake
  3.  OpenAI provider selection
  4.  Unknown provider fails clearly
  5.  OpenAI provider missing API key fails safely
  6.  OpenAI embedding response parsing
  7.  1536-dimensional vector validation
  8.  Wrong-dimension provider rejection
  9.  Provider injection
  10. Configuration validation
  11. Timeout configuration
  12. Retry configuration
  13. No real API calls in the normal test suite
  14. No secret leakage in exceptions/logging
  15. Embedding worker uses the configured provider
  16. Provider failure isolation
  17. No fake fallback when OpenAI explicitly selected
  18. Retrieval scope enforcement (fail closed)
  19. Python retrieval fallback (SQLite/no PostgreSQL)
  20. Hybrid retrieval compatibility
  21. top_k compatibility
  22. min_similarity compatibility
  23. RAG context limits remain enforced
  24. NO_CONTEXT behavior remains stable
  25. SQLite test compatibility
  26. Deterministic FakeEmbeddingProvider semantics preserved

The real-provider smoke test is opt-in and disabled by default.
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.core.config import Settings, settings
from app.core.resilience import CircuitState, RetryPolicy
from app.db.base import Base
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.db.models.user import User
from app.embeddings import (
    EmbeddingResilientProvider,
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
    build_embedding_provider,
    build_resilient_embedding_provider,
)
from app.embeddings.resilience import ProviderCallError
from app.embeddings.service import EmbeddingService
from app.ingestion.worker_processing import process_source_embeddings_with_session
from app.rag.service import RAGService
from app.retrieval.service import RetrievalService

DUMMY_KEY = "sk-test-not-real"
ZERO_1536 = [0.0] * 1536


# ---------------------------------------------------------------------------
# Shared fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_source(db: Session, *, content: str = "phase 11g embedding") -> Source:
    project_id = uuid.uuid4()
    user = User(id=uuid.uuid4(), email=f"g-{uuid.uuid4()}@example.test", name="G", role="operator")
    project = Project(id=project_id, user_id=user.id, name="Phase 11G")
    source = Source(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type="txt",
        original_filename="g.txt",
        mime_type="text/plain",
        file_size=len(content),
        language="en",
        status="ready",
        extracted_text=content,
    )
    db.add_all([user, project, source])
    db.flush()
    chunk = SourceChunk(
        id=uuid.uuid4(), source_id=source.id, chunk_index=0,
        content=content, embedding=None,
    )
    db.add(chunk)
    db.commit()
    db.refresh(source)
    return source


def _to_list(value) -> list[float]:
    """Normalize a stored embedding (pgvector numpy/str/list) to plain floats."""
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.startswith("[") and cleaned.endswith("]"):
            cleaned = cleaned[1:-1]
        return [float(part.strip()) for part in cleaned.split(",") if part.strip()]
    if hasattr(value, "tolist"):
        return [float(x) for x in value.tolist()]
    return [float(x) for x in value]


def _assert_embeddings_close(actual, expected, tol: float = 1e-6) -> None:
    """Elementwise float compare that avoids pytest's heavy list difflib diffing."""
    got = _to_list(actual)
    assert len(got) == len(expected), f"length {len(got)} != {len(expected)}"
    for i, (g, e) in enumerate(zip(got, expected)):
        assert abs(g - e) < tol, f"dim {i}: {g} != {e}"


def make_embedded_source(db: Session, *, content: str = "quarterly revenue grew") -> tuple[Project, Source]:
    user = User(id=uuid.uuid4(), email=f"g-{uuid.uuid4()}@example.test", name="G", role="operator")
    project = Project(id=uuid.uuid4(), user_id=user.id, name="Phase 11G project")
    source = Source(
        id=uuid.uuid4(), project_id=project.id, source_type="txt",
        original_filename="g.txt", mime_type="text/plain",
        file_size=len(content), language="en", status="ready", extracted_text=content,
    )
    db.add_all([user, project, source])
    db.flush()
    vec = [1.0] + [0.0] * 1535
    chunk = SourceChunk(
        id=uuid.uuid4(), source_id=source.id, chunk_index=0,
        content=content, embedding=vec,
    )
    db.add(chunk)
    db.commit()
    return project, source


def fake_retrieval() -> RetrievalService:
    return RetrievalService(
        embedding_service=EmbeddingService(
            provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536
        )
    )


class FakeEmbeddingsClient:
    """Mimics ``openai.embeddings.create`` for offline tests."""

    def __init__(self, vectors: list[list[float]] | None = None, *, fail=None):
        self.vectors = vectors
        self.fail = fail
        self.calls = 0
        self.last_input: list[str] | None = None
        self.last_model: str | None = None
        self.embeddings = SimpleNamespace(create=self.create)

    def create(self, *, model=None, input=None):
        self.calls += 1
        self.last_model = model
        self.last_input = list(input)
        if self.fail is not None:
            error = self.fail
            self.fail = None
            raise error
        if self.vectors is None:
            self.vectors = [[0.1] * 1536 for _ in input]
        data = [
            SimpleNamespace(index=i, embedding=vec)
            for i, vec in enumerate(self.vectors)
        ]
        return SimpleNamespace(data=data)


class _StatusError(Exception):
    def __init__(self, status_code: int, message: str = "err") -> None:
        super().__init__(message)
        self.status_code = status_code


class _RetryAfterError(Exception):
    def __init__(self, retry_after: float) -> None:
        super().__init__("rate limited")
        self.status_code = 429
        self.retry_after = retry_after


class FlakyEmbeddingProvider:
    def __init__(self, fail_until: int, exc_factory, dimensions: int = 1536) -> None:
        self.calls = 0
        self.fail_until = fail_until
        self.exc_factory = exc_factory
        self.dimensions = dimensions

    def embed_texts(self, texts):
        self.calls += 1
        if self.calls <= self.fail_until:
            raise self.exc_factory()
        return [[float(index + 1) / 255.0 for index in range(self.dimensions)] for _ in texts]


class AlwaysFailEmbeddingProvider:
    def __init__(self, exc_factory) -> None:
        self.calls = 0
        self.exc_factory = exc_factory

    def embed_texts(self, texts):
        self.calls += 1
        raise self.exc_factory()


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []
        self.rand = 0.5

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def random(self) -> float:
        return self.rand


# ---------------------------------------------------------------------------
# 1/26 Fake provider compatibility
# ---------------------------------------------------------------------------

def test_fake_provider_remains_deterministic_and_offline():
    provider = FakeEmbeddingProvider(dimensions=1536)
    assert not hasattr(provider, "_client")
    left = provider.embed_texts(["hello world"])
    right = provider.embed_texts(["hello world"])
    assert left == right
    assert len(left[0]) == 1536
    assert all(isinstance(v, float) for v in left[0])


# ---------------------------------------------------------------------------
# 2/3/4 Factory: default, select, unknown
# ---------------------------------------------------------------------------

def test_factory_defaults_to_fake():
    provider = build_embedding_provider()
    assert isinstance(provider, FakeEmbeddingProvider)
    assert provider.dimensions == settings.EMBEDDING_DIMENSIONS == 1536


def test_factory_explicit_fake_with_dimensions():
    provider = build_embedding_provider("fake", dimensions=4)
    assert isinstance(provider, FakeEmbeddingProvider)
    assert provider.dimensions == 4


def test_factory_selects_openai_and_applies_resilience(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", DUMMY_KEY)
    provider = build_embedding_provider()
    assert isinstance(provider, EmbeddingResilientProvider)
    assert isinstance(provider._provider, OpenAIEmbeddingProvider)
    assert provider._provider._dimensions == 1536
    assert provider._provider._model == settings.EMBEDDING_MODEL


def test_factory_unknown_provider_fails_clearly():
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        build_embedding_provider("bogus")


def test_config_rejects_unknown_provider():
    with pytest.raises(Exception):
        Settings(EMBEDDING_PROVIDER="bogus")


# ---------------------------------------------------------------------------
# 5 OpenAI missing API key fails safely
# ---------------------------------------------------------------------------

def test_openai_missing_api_key_fails_safely(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "")
    with pytest.raises(ValueError) as exc:
        OpenAIEmbeddingProvider(api_key="")
    message = str(exc.value)
    assert "EMBEDDING_API_KEY" in message
    assert DUMMY_KEY not in message
    assert "sk-" not in message


def test_factory_openai_without_key_never_falls_back_to_fake(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "")
    with pytest.raises(ValueError, match="EMBEDDING_API_KEY"):
        build_embedding_provider()


# ---------------------------------------------------------------------------
# 6/7/8 OpenAI response parsing + dimensionality validation
# ---------------------------------------------------------------------------

def test_openai_embeddings_create_parses_batch_response(monkeypatch):
    vectors = [[1.0] + [0.0] * 1535, [0.0, 1.0] + [0.0] * 1534]
    client = FakeEmbeddingsClient(vectors)
    provider = OpenAIEmbeddingProvider(api_key=DUMMY_KEY, client=client)

    out = provider.embed_texts(["apples", "bananas"])

    assert client.calls == 1
    assert client.last_model == settings.EMBEDDING_MODEL
    assert client.last_input == ["apples", "bananas"]
    assert len(out) == 2
    assert all(len(vector) == 1536 for vector in out)


def test_openai_response_reordered_by_index(monkeypatch):
    # The API may return rows in any order; we sort by the index field.
    vectors = [[1.0] + [0.0] * 1535, [0.0, 1.0] + [0.0] * 1534]
    data = [
        SimpleNamespace(index=1, embedding=vectors[1]),  # returned out of order
        SimpleNamespace(index=0, embedding=vectors[0]),
    ]
    client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(data=data)
        )
    )
    provider = OpenAIEmbeddingProvider(api_key=DUMMY_KEY, client=client)

    out = provider.embed_texts(["a", "b"])

    assert out[0][0] == 1.0
    assert out[1][0] == 0.0


def test_openai_wrong_dimensions_rejected(monkeypatch):
    client = FakeEmbeddingsClient([[0.1, 0.2]])
    provider = OpenAIEmbeddingProvider(api_key=DUMMY_KEY, client=client)
    with pytest.raises(ValueError, match="dimensions mismatch"):
        provider.embed_texts(["too small"])


def test_service_rejects_wrong_dimension_provider():
    class TinyProvider:
        def embed_texts(self, texts):
            return [[0.1, 0.2] for _ in texts]

    with pytest.raises(ValueError, match="dimensions"):
        EmbeddingService(provider=TinyProvider(), dimensions=1536).embed_texts(["bad"])


def test_openai_response_count_mismatch_rejected():
    client = FakeEmbeddingsClient([[0.1] * 1536])
    provider = OpenAIEmbeddingProvider(api_key=DUMMY_KEY, client=client)
    with pytest.raises(ValueError, match="returned 1 vectors for 2 texts"):
        provider.embed_texts(["a", "b"])


# ---------------------------------------------------------------------------
# 9 Provider injection
# ---------------------------------------------------------------------------

def test_embedding_service_accepts_injected_provider():
    service = EmbeddingService(provider=FakeEmbeddingProvider(dimensions=4), dimensions=4)
    vectors = service.embed_texts(["apples", "bananas"])
    assert len(vectors) == 2
    assert all(len(vector) == 4 for vector in vectors)


def test_embedding_service_empty_batch_rejected():
    service = EmbeddingService(provider=FakeEmbeddingProvider(dimensions=4), dimensions=4)
    with pytest.raises(ValueError, match="batch"):
        service.embed_texts([])


def test_build_resilient_embedding_provider_passes_fake_through_unchanged():
    base = build_embedding_provider("fake")
    assert build_resilient_embedding_provider(base) is base


def test_build_resilient_embedding_provider_wraps_custom_provider():
    class CustomProvider:
        def embed_texts(self, texts):
            return [[0.1] * 1536 for _ in texts]

    base = CustomProvider()
    wrapped = build_resilient_embedding_provider(base)
    assert isinstance(wrapped, EmbeddingResilientProvider)
    assert wrapped._provider is base


# ---------------------------------------------------------------------------
# 10/11/12 Configuration validation
# ---------------------------------------------------------------------------

def test_config_rejects_invalid_embedding_values():
    with pytest.raises(Exception):
        Settings(EMBEDDING_DIMENSIONS=0)
    with pytest.raises(Exception):
        Settings(EMBEDDING_DIMENSIONS=-5)
    with pytest.raises(Exception):
        Settings(EMBEDDING_TIMEOUT_SECONDS=0)
    with pytest.raises(Exception):
        Settings(EMBEDDING_TIMEOUT_SECONDS=-1)
    with pytest.raises(Exception):
        Settings(EMBEDDING_MAX_RETRIES=-1)
    with pytest.raises(Exception):
        Settings(EMBEDDING_MAX_RETRIES=11)

    s = Settings(EMBEDDING_DIMENSIONS=1536, EMBEDDING_TIMEOUT_SECONDS=10, EMBEDDING_MAX_RETRIES=2)
    assert s.EMBEDDING_DIMENSIONS == 1536
    assert s.EMBEDDING_TIMEOUT_SECONDS == 10
    assert s.EMBEDDING_MAX_RETRIES == 2


def test_budget_cannot_exceed_worker_timeout():
    with pytest.raises(Exception, match="Embedding request budget"):
        # 500s * 3 attempts = 1500s > WORKER_JOB_TIMEOUT (605s).
        Settings(EMBEDDING_TIMEOUT_SECONDS=500, EMBEDDING_MAX_RETRIES=2)


def test_provider_defaults_and_pinned_dimensions():
    s = Settings()
    assert s.EMBEDDING_PROVIDER == "fake"
    assert s.EMBEDDING_MODEL == "text-embedding-3-small"
    assert s.EMBEDDING_DIMENSIONS == 1536


def test_timeout_forwarded_to_provider(monkeypatch):
    provider = OpenAIEmbeddingProvider(
        api_key=DUMMY_KEY, timeout=17, client=FakeEmbeddingsClient()
    )
    assert provider._timeout == 17


def test_retry_count_drives_resilience_budget(monkeypatch):
    assert settings.EMBEDDING_MAX_RETRIES == 2
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", DUMMY_KEY)
    provider = build_embedding_provider()
    assert isinstance(provider, EmbeddingResilientProvider)
    assert provider._max_attempts == settings.EMBEDDING_MAX_RETRIES + 1


# ---------------------------------------------------------------------------
# 13 No real API calls in the normal test suite
# ---------------------------------------------------------------------------

def test_injected_client_never_constructs_real_sdk(monkeypatch):
    def _forbid(*args, **kwargs):
        raise AssertionError("A real OpenAI client was constructed during tests.")

    monkeypatch.setattr(
        "app.embeddings.openai_provider.openai.OpenAI", _forbid
    )
    client = FakeEmbeddingsClient([[0.1] * 1536])
    provider = OpenAIEmbeddingProvider(api_key=DUMMY_KEY, client=client)
    vectors = provider.embed_texts(["offline"])
    assert len(vectors[0]) == 1536
    assert client.calls == 1


# ---------------------------------------------------------------------------
# 14 No secret leakage
# ---------------------------------------------------------------------------

def test_no_secret_leak_in_resilient_error(monkeypatch):
    flaky = AlwaysFailEmbeddingProvider(
        lambda: _StatusError(500, "upstream saw api key sk-super-secret")
    )
    clock = FakeClock()
    provider = EmbeddingResilientProvider(
        flaky,
        max_attempts=2,
        retry_policy=RetryPolicy(
            base_delay=1.0, max_delay=10.0, jitter=0.0, random=clock.random
        ),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    with pytest.raises(ProviderCallError) as exc:
        provider.embed_texts(["secret"])
    assert "sk-super-secret" not in str(exc.value)
    assert "sk-super-secret" not in str(provider.last_error)
    assert "sk-super-secret" not in str(provider.last_metadata)
    assert "<redacted>" in str(exc.value)


# ---------------------------------------------------------------------------
# 15 Embedding worker uses the configured provider
# ---------------------------------------------------------------------------

def test_worker_uses_configured_fake_provider(db):
    source = make_source(db)
    result = process_source_embeddings_with_session(db, source.id)

    metadata = result.source_metadata
    assert metadata["embedding_status"] == "completed"
    assert metadata["embedding_provider"] == "fake"
    assert metadata["embedding_model"] == settings.EMBEDDING_MODEL
    assert metadata["embedding_dimensions"] == 1536
    chunks = db.execute(select(SourceChunk).where(SourceChunk.source_id == source.id)).scalars().all()
    assert len(chunks) == 1
    expected = FakeEmbeddingProvider(dimensions=1536).embed_texts(["phase 11g embedding"])[0]
    _assert_embeddings_close(chunks[0].embedding, expected)


def test_worker_uses_injected_provider(db):
    source = make_source(db)
    provider = FakeEmbeddingProvider(dimensions=1536)
    result = process_source_embeddings_with_session(db, source.id, provider=provider)
    assert result.source_metadata["embedding_status"] == "completed"
    chunks = db.execute(select(SourceChunk).where(SourceChunk.source_id == source.id)).scalars().all()
    _assert_embeddings_close(chunks[0].embedding, provider.embed_texts(["phase 11g embedding"])[0])


# ---------------------------------------------------------------------------
# 16 Provider failure isolation
# ---------------------------------------------------------------------------

def test_provider_failure_marks_source_failed_without_partial_writes(db):
    source = make_source(db)

    class Malformed:
        def embed_texts(self, texts):
            return [[0.1] * 1536, [0.2] * 1536]  # more vectors than chunks

    with pytest.raises(ValueError, match="returned 2 vectors for 1 texts"):
        process_source_embeddings_with_session(db, source.id, provider=Malformed())

    stored = db.get(Source, source.id)
    assert stored.status == "ready"
    assert (stored.source_metadata or {})["embedding_status"] == "failed"
    assert "embedding_error" in (stored.source_metadata or {})
    chunk = db.execute(select(SourceChunk).where(SourceChunk.source_id == source.id)).scalar_one()
    assert chunk.embedding is None  # nothing partially persisted


def test_transient_retry_then_success(monkeypatch):
    clock = FakeClock()
    flaky = FlakyEmbeddingProvider(2, lambda: TimeoutError("slow"))
    provider = EmbeddingResilientProvider(
        flaky,
        max_attempts=3,
        retry_policy=RetryPolicy(
            base_delay=1.0, max_delay=10.0, jitter=0.0, random=clock.random
        ),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    vectors = provider.embed_texts(["retry me"])
    assert flaky.calls == 3
    assert len(vectors) == 1
    assert len(vectors[0]) == 1536
    assert len(clock.slept) == 2
    assert provider.last_metadata["final_status"] == "completed"


def test_permanent_auth_failure_no_retry():
    clock = FakeClock()
    flaky = AlwaysFailEmbeddingProvider(lambda: _StatusError(401, "invalid key"))
    provider = EmbeddingResilientProvider(
        flaky,
        max_attempts=3,
        retry_policy=RetryPolicy(
            base_delay=1.0, max_delay=10.0, jitter=0.0, max_429_wait=5.0, random=clock.random
        ),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    with pytest.raises(ProviderCallError):
        provider.embed_texts(["nope"])
    assert flaky.calls == 1
    assert clock.slept == []
    assert provider.last_metadata["retryable"] is False


def test_retry_after_honored_and_429_transient():
    clock = FakeClock()
    flaky = FlakyEmbeddingProvider(1, lambda: _RetryAfterError(2.5))
    provider = EmbeddingResilientProvider(
        flaky,
        max_attempts=3,
        retry_policy=RetryPolicy(
            base_delay=1.0, max_delay=10.0, jitter=0.0, max_429_wait=30.0, random=clock.random
        ),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    vectors = provider.embed_texts(["later"])
    assert flaky.calls == 2
    assert clock.slept[-1] == pytest.approx(2.5)
    assert len(vectors[0]) == 1536


def test_circuit_opens_after_repeated_failures():
    clock = FakeClock()
    flaky = AlwaysFailEmbeddingProvider(lambda: _StatusError(503))
    provider = EmbeddingResilientProvider(
        flaky,
        max_attempts=1,
        breaker_failure_threshold=2,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    with pytest.raises(ProviderCallError):
        provider.embed_texts(["x"])
    with pytest.raises(ProviderCallError):
        provider.embed_texts(["y"])
    assert provider.circuit_state() == CircuitState.OPEN


# ---------------------------------------------------------------------------
# 17 No fake fallback when OpenAI explicitly selected
# ---------------------------------------------------------------------------

def test_worker_explicit_openai_without_key_fails_explicitly(db, monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "")
    source = make_source(db)

    with pytest.raises(Exception, match="EMBEDDING_API_KEY"):
        process_source_embeddings_with_session(db, source.id)

    stored = db.get(Source, source.id)
    assert (stored.source_metadata or {})["embedding_status"] == "failed"
    assert "EMBEDDING_API_KEY" in (stored.source_metadata or {}).get("embedding_error", "")


# ---------------------------------------------------------------------------
# 18 Retrieval scope enforcement (fail closed)
# ---------------------------------------------------------------------------

def test_retrieval_refuses_unscoped_query(db):
    retrieval = fake_retrieval()
    vec = [1.0] + [0.0] * 1535
    with pytest.raises(ValueError, match="Retrieval scope required"):
        retrieval.query_by_text(db, "anything", require_scope=True)
    with pytest.raises(ValueError, match="Retrieval scope required"):
        retrieval.query_by_vector(db, vec, require_scope=True)
    with pytest.raises(ValueError, match="Retrieval scope required"):
        retrieval.query_hybrid(db, "anything", require_scope=True)


def test_retrieval_scope_enforced_only_when_opt_in(db):
    project, source = make_embedded_source(db, content="quarterly revenue grew 12%")
    retrieval = fake_retrieval()

    # Unscoped-with-flag raises even though data exists.
    with pytest.raises(ValueError, match="Retrieval scope required"):
        retrieval.query_by_text(db, "revenue", require_scope=True)

    # Scoped call succeeds.
    matches = retrieval.query_by_text(db, "revenue", project_id=project.id, require_scope=True)
    assert len(matches) == 1
    assert matches[0].source_id == source.id

    # Source-only scope also satisfies the guard.
    matches_by_source = retrieval.query_by_text(
        db, "revenue", source_id=source.id, require_scope=True
    )
    assert len(matches_by_source) == 1


# ---------------------------------------------------------------------------
# 19/20/21/22 Retrieval behavior compatibility (SQLite fallback)
# ---------------------------------------------------------------------------

def test_python_cosine_retrieval_works_on_sqlite(db):
    project, source = make_embedded_source(db, content="quarterly revenue grew 12%")
    retrieval = fake_retrieval()
    matches = retrieval.query_by_vector(
        db, [1.0] + [0.0] * 1535, project_id=project.id
    )
    assert len(matches) == 1
    assert matches[0].chunk_index == 0
    assert matches[0].score == pytest.approx(1.0, abs=1e-6)


def test_min_similarity_filters(db):
    user = User(id=uuid.uuid4(), email=f"g-{uuid.uuid4()}@example.test", name="G", role="operator")
    project = Project(id=uuid.uuid4(), user_id=user.id, name="min sim")
    source = Source(
        id=uuid.uuid4(), project_id=project.id, source_type="txt",
        original_filename="m.txt", mime_type="text/plain", file_size=1,
        language="en", status="ready", extracted_text="m",
    )
    db.add_all([user, project, source])
    db.add(SourceChunk(
        id=uuid.uuid4(), source_id=source.id, chunk_index=0,
        content="strong match", embedding=[1.0] + [0.0] * 1535,
    ))
    db.add(SourceChunk(
        id=uuid.uuid4(), source_id=source.id, chunk_index=1,
        content="orthogonal no match", embedding=[0.0, 1.0] + [0.0] * 1534,
    ))
    db.commit()

    retrieval = fake_retrieval()
    query = [1.0] + [0.0] * 1535
    results = retrieval.query_by_vector(db, query, project_id=project.id, min_similarity=0.5)
    assert len(results) == 1
    assert results[0].content == "strong match"


def test_top_k_respected(db):
    project, source = make_embedded_source(db)
    db.add(SourceChunk(
        id=uuid.uuid4(), source_id=source.id, chunk_index=1,
        content="another chunk about revenue", embedding=[1.0] + [0.0] * 1535,
    ))
    db.commit()
    retrieval = fake_retrieval()
    matches = retrieval.query_by_text(db, "revenue", project_id=project.id, top_k=1)
    assert len(matches) == 1


def test_hybrid_retrieval_compatibility(db):
    user = User(id=uuid.uuid4(), email=f"g-{uuid.uuid4()}@example.test", name="G", role="operator")
    project = Project(id=uuid.uuid4(), user_id=user.id, name="hybrid")
    source_a = Source(
        id=uuid.uuid4(), project_id=project.id, source_type="txt",
        original_filename="a.txt", mime_type="text/plain", file_size=1,
        language="en", status="ready", extracted_text="revenue",
    )
    source_b = Source(
        id=uuid.uuid4(), project_id=project.id, source_type="txt",
        original_filename="b.txt", mime_type="text/plain", file_size=1,
        language="en", status="ready", extracted_text="unrelated",
    )
    db.add_all([user, project, source_a, source_b])
    db.add(SourceChunk(
        id=uuid.uuid4(), source_id=source_a.id, chunk_index=0,
        content="revenue grew quarter over quarter", embedding=[0.1] + [1.0] + [0.0] * 1534,
    ))
    db.add(SourceChunk(
        id=uuid.uuid4(), source_id=source_b.id, chunk_index=0,
        content="totally unrelated topic no overlap", embedding=[1.0, 0.1] + [0.0] * 1534,
    ))
    db.commit()

    retrieval = fake_retrieval()
    matches = retrieval.query_hybrid(
        db, "revenue grew quarter over quarter", project_id=project.id, top_k=5
    )
    assert any("revenue grew quarter" in m.content for m in matches)


# ---------------------------------------------------------------------------
# 23/24 RAG context limits + NO_CONTEXT behavior
# ---------------------------------------------------------------------------

def _rag_with(monkeypatch, *, top_k=5, min_sim=0.0, max_chars=4000) -> RAGService:
    monkeypatch.setattr(settings, "RAG_TOP_K", top_k)
    monkeypatch.setattr(settings, "RAG_MIN_SIMILARITY", min_sim)
    monkeypatch.setattr(settings, "RAG_MAX_CONTEXT_CHARS", max_chars)
    return RAGService(retrieval_service=fake_retrieval())


def test_rag_context_limit_enforced(db, monkeypatch):
    project, source = make_embedded_source(db, content="word " * 200)
    rag = _rag_with(monkeypatch, max_chars=100)
    context = rag.retrieve_context_for_source(db, source.id, "word", project_id=project.id)
    assert len(context.assembled_text) <= 100
    assert context.metadata["truncated"] is True


def test_rag_no_context_behavior_stable(db, monkeypatch):
    user = User(id=uuid.uuid4(), email=f"g-{uuid.uuid4()}@example.test", name="G", role="operator")
    project = Project(id=uuid.uuid4(), user_id=user.id, name="empty")
    source = Source(
        id=uuid.uuid4(), project_id=project.id, source_type="txt",
        original_filename="e.txt", mime_type="text/plain", file_size=1,
        language="en", status="ready", extracted_text="",
    )
    db.add_all([user, project, source])
    db.commit()

    rag = _rag_with(monkeypatch)
    context = rag.retrieve_context_for_source(db, source.id, "nothing", project_id=project.id)
    assert context.chunk_count == 0
    assert context.citations == []
    assert context.assembled_text == RAGService.NO_CONTEXT
    assert context.metadata["retrieval_status"] == "insufficient_context"


# ---------------------------------------------------------------------------
# 25 SQLite test compatibility (whole file uses SQLite; explicit check)
# ---------------------------------------------------------------------------

def test_rag_metadata_retrieval_method_unchanged(db, monkeypatch):
    project, source = make_embedded_source(db, content="quarterly revenue grew 12%")
    rag = _rag_with(monkeypatch)
    context = rag.retrieve_context_for_source(db, source.id, "revenue", project_id=project.id)
    assert context.metadata["retrieval_method"] == "cosine-similarity-pgvector"


# ---------------------------------------------------------------------------
# 26 Deterministic fake semantics preserved end to end
# ---------------------------------------------------------------------------

def test_fake_vectors_identical_across_calls_and_services():
    provider = FakeEmbeddingProvider(dimensions=1536)
    via_provider = provider.embed_texts(["identical sentence 2026"])[0]
    via_service = EmbeddingService(
        provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536
    ).embed_texts(["identical sentence 2026"])[0]
    via_factory = EmbeddingService().embed_texts(["identical sentence 2026"])[0]
    assert via_provider == via_service == via_factory
    assert len(via_factory) == 1536


# ---------------------------------------------------------------------------
# 11G-N Optional real-provider smoke test (opt-in, disabled by default)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("EMBEDDING_API_KEY"),
    reason="Real OpenAI embedding smoke test not run because credentials are unavailable.",
)
def test_real_openai_embedding_smoke_opt_in():
    """Opt-in smoke test against the real provider (requires EMBEDDING_API_KEY).

    Never prints the key, never submits source documents, and persists nothing.
    """
    provider = OpenAIEmbeddingProvider()
    vectors = provider.embed_texts(["TransformIQ embedding smoke test string"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1536