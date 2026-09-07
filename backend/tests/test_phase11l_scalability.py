"""Phase 11L — Scalability & production ops tests.

Covers the Phase 11L concerns, entirely offline and deterministic:

  11L-A  LLM output caching (backends, key isolation, service wiring).
  11L-B  background-job enforcement: atomic worker claim semantics.
  11L-C  Prometheus metrics (registry, rendering, /metrics endpoint, worker
         delta push/load fail-open, no secrets / no unbounded labels).
  11L-D  worker scaling: WORKER_COUNT config + no legacy WORKER_CONCURRENCY
         wiring in the worker entry point.
  11L-G  configuration validation for the new knobs.

Modeled on the Phase 11E helpers (StaticPool sqlite, make_db/add_job,
LocalStorage tmp dir, FakeLLMProvider).  No network, no RQ/Redis required.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.models.canonical_content import CanonicalContent
from app.db.models.generation_configuration import GenerationConfiguration
from app.db.models.output import Output
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.ingestion.storage import LocalStorage
from app.transformation.llm import FakeLLMProvider
from app.transformation.service import run_transformation_job

from app.core.cache import (
    CacheBackend,
    MemoryCacheBackend,
    RedisCacheBackend,
    build_cache_backend,
)
from app.core.metrics import (
    MetricsRegistry,
    metrics,
    push_worker_metrics,
    load_worker_metrics,
    render_metrics,
)
from app.transformation.llm.cache import CachingLLMProvider, build_cache_key


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

CANONICAL: dict[str, Any] = {
    "title": "Test Source",
    "summary": "A test source summary with key facts.",
    "topics": [{"value": "technology"}],
    "entities": [{"name": "Acme Corp"}],
    "key_points": [{"text": "First key point", "source_chunk_ids": []}],
    "claims": [{"text": "A source claim", "source_chunk_ids": []}],
    "statistics": [{"text": "37% of respondents", "source_chunk_ids": []}],
    "dates": [{"text": "2024"}],
    "recommendations": [{"text": "Recommended action", "source_chunk_ids": []}],
    "source_references": [{"text": "Source reference A", "source_chunk_ids": []}],
}


def make_project(db: Session, *, name: str = "Phase 11L") -> Project:
    user = User(
        id=uuid.uuid4(),
        email=f"p11l-{uuid.uuid4().hex}@example.test",
        name="P11L",
        role="operator",
    )
    project = Project(id=uuid.uuid4(), user_id=user.id, name=name)
    source = Source(
        id=uuid.uuid4(),
        project_id=project.id,
        source_type="text",
        status="ready",
        extracted_text="Source line one.\nSource line two.",
    )
    db.add_all([user, project, source])
    db.flush()
    db.add(
        CanonicalContent(
            id=uuid.uuid4(),
            source_id=source.id,
            project_id=project.id,
            status="completed",
            title=CANONICAL["title"],
            summary=CANONICAL["summary"],
            key_points=[{"text": "First key point", "source_chunk_ids": []}],
            recommendations=[{"text": "Recommended action", "source_chunk_ids": []}],
            claims=[],
            statistics=[],
            dates=[],
            entities=[],
            topics=[],
            source_references=[],
        )
    )
    return project


def make_db():
    """In-memory sqlite with a ready project/source/canonical."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        project = make_project(db)
        db.commit()
    return engine, project.id


def add_job(
    engine,
    project_id: uuid.UUID,
    source_id: uuid.UUID | None = None,
    output_types: list[str] | None = None,
) -> uuid.UUID:
    with Session(engine, expire_on_commit=False) as db:
        source_id = db.get(Project, project_id).sources[0].id
        cfg = GenerationConfiguration(id=uuid.uuid4(), project_id=project_id, language="English")
        db.add(cfg)
        db.flush()
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=project_id,
            source_id=source_id,
            configuration_id=cfg.id,
            requested_outputs={
                "output_types": output_types or ["summary"]
            },
            status="queued",
        )
        db.add(job)
        db.commit()
        return job.id


def fetch_job(engine, job_id: uuid.UUID) -> TransformationJob:
    with Session(engine, expire_on_commit=False) as db:
        return db.get(TransformationJob, job_id)


class CountingProvider(FakeLLMProvider):
    """FakeLLMProvider that counts provider calls for cache tests."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        return super().generate_text(
            system_prompt=system_prompt, user_content=user_content
        )


class RaisingStubClient:
    """Redis client stand-in that raises on every operation."""

    def __getattr__(self, name: str) -> Any:
        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(f"redis {name} unavailable")
        return _boom


# ---------------------------------------------------------------------------
# 11L-A — cache backends
# ---------------------------------------------------------------------------

class TestMemoryCacheBackend:
    def test_roundtrip_and_hit(self):
        backend = MemoryCacheBackend()
        backend.set("k", b"v", 60)
        assert backend.get("k") == b"v"

    def test_ttl_expiry_via_clock(self):
        backend = MemoryCacheBackend()
        now = [1_000.0]
        backend._time = lambda: now[0]
        backend.set("k", b"v", 60)
        assert backend.get("k") == b"v"
        now[0] += 60.001
        assert backend.get("k") is None

    def test_bounded_entries(self):
        backend = MemoryCacheBackend(max_entries=2)
        backend.set("a", b"1", 60)
        backend.set("b", b"2", 60)
        backend.set("c", b"3", 60)
        assert backend.get("a") is None
        assert backend.get("b") == b"2"
        assert backend.get("c") == b"3"

    def test_invalid_arguments_rejected(self):
        backend = MemoryCacheBackend()
        with pytest.raises(ValueError):
            backend.set("", b"v", 60)
        with pytest.raises(ValueError):
            backend.set("k", b"v", 0)
        with pytest.raises(ValueError):
            MemoryCacheBackend(max_entries=0)

    def test_delete_expired_entry(self):
        backend = MemoryCacheBackend()
        now = [0.0]
        backend._time = lambda: now[0]
        backend.set("k", b"v", 10)
        now[0] = 99.0
        assert backend.get("k") is None
        assert len(backend) == 0


class TestRedisCacheBackend:
    def test_fail_open_on_get_and_set(self):
        backend = RedisCacheBackend(client=RaisingStubClient())
        assert backend.get("k") is None
        backend.set("k", b"v", 60)  # must not raise

    def test_invalid_arguments_rejected(self):
        backend = RedisCacheBackend(client=RaisingStubClient())
        with pytest.raises(ValueError):
            backend.get("")
        with pytest.raises(ValueError):
            backend.set("k", "not-bytes", 60)
        with pytest.raises(ValueError):
            backend.set("k", b"v", 0)

    def test_builder_selects_backend(self):
        assert isinstance(build_cache_backend("memory"), MemoryCacheBackend)
        assert isinstance(build_cache_backend("redis"), RedisCacheBackend)
        with pytest.raises(ValueError):
            build_cache_backend("memcached")


# ---------------------------------------------------------------------------
# 11L-A — caching provider + key design
# ---------------------------------------------------------------------------

class TestCachingLLMProvider:
    def test_hit_served_without_provider_call(self):
        provider = CountingProvider()
        backend = MemoryCacheBackend()
        wrapped = CachingLLMProvider(
            provider, backend, scope="proj-a", ttl_seconds=60,
            provider_name="fake", model="m", enabled=True,
        )
        first = wrapped.generate_text(system_prompt="s", user_content="u")
        second = wrapped.generate_text(system_prompt="s", user_content="u")
        assert first == second
        assert provider.calls == 1

    def test_miss_when_disabled(self):
        provider = CountingProvider()
        backend = MemoryCacheBackend()
        wrapped = CachingLLMProvider(
            provider, backend, scope="proj-a", ttl_seconds=60,
            provider_name="fake", model="m", enabled=False,
        )
        wrapped.generate_text(system_prompt="s", user_content="u")
        wrapped.generate_text(system_prompt="s", user_content="u")
        assert provider.calls == 2

    def test_prompt_change_is_a_miss(self):
        provider = CountingProvider()
        backend = MemoryCacheBackend()
        wrapped = CachingLLMProvider(
            provider, backend, scope="proj-a", ttl_seconds=60,
            provider_name="fake", model="m", enabled=True,
        )
        wrapped.generate_text(system_prompt="s", user_content="u")
        wrapped.generate_text(system_prompt="s", user_content="u2")
        wrapped.generate_text(system_prompt="s2", user_content="u")
        assert provider.calls == 3

    def test_key_isolation_between_projects(self):
        k_a = build_cache_key(
            scope="proj-a", provider="fake", model="m",
            system_prompt="s", user_content="u", key_version="v1",
        )
        k_b = build_cache_key(
            scope="proj-b", provider="fake", model="m",
            system_prompt="s", user_content="u", key_version="v1",
        )
        assert k_a != k_b

    def test_key_version_changes_key(self):
        k1 = build_cache_key(
            scope="proj-a", provider="fake", model="m",
            system_prompt="s", user_content="u", key_version="v1",
        )
        k2 = build_cache_key(
            scope="proj-a", provider="fake", model="m",
            system_prompt="s", user_content="u", key_version="v2",
        )
        assert k1 != k2

    def test_metadata_contract_delegates_to_wrapped_provider(self):
        class _MetaProvider(FakeLLMProvider):
            provider_name = "fake"
            model = "m"

            def __init__(self) -> None:
                super().__init__()
                self.last_metadata = {"tokens_used": 12}

        provider = _MetaProvider()
        wrapped = CachingLLMProvider(
            provider, MemoryCacheBackend(), scope="proj-a", ttl_seconds=60,
            provider_name="fake", model="m", enabled=True,
        )
        assert wrapped.last_metadata == {"tokens_used": 12}


# ---------------------------------------------------------------------------
# 11L-A — service wiring (disabled by default, cacheable per project)
# ---------------------------------------------------------------------------

class TestServiceCacheWiring:
    def test_second_job_misses_without_cache(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id = make_db()
        job1 = add_job(engine, project_id)
        job2 = add_job(engine, project_id)
        provider = CountingProvider()
        with Session(engine, expire_on_commit=False) as db:
            run_transformation_job(db, job1, llm_provider=provider, storage=storage)
        with Session(engine, expire_on_commit=False) as db:
            run_transformation_job(db, job2, llm_provider=provider, storage=storage)
        assert provider.calls == 2  # default = no caching

    def test_second_identical_job_hits_cache(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id = make_db()
        job1 = add_job(engine, project_id)
        job2 = add_job(engine, project_id)
        provider = CountingProvider()
        backend = MemoryCacheBackend()
        with Session(engine, expire_on_commit=False) as db:
            run_transformation_job(
                db, job1, llm_provider=provider, storage=storage,
                cache_backend=backend, cache_enabled=True,
            )
        with Session(engine, expire_on_commit=False) as db:
            run_transformation_job(
                db, job2, llm_provider=provider, storage=storage,
                cache_backend=backend, cache_enabled=True,
            )
        assert fetch_job(engine, job1).status == "completed"
        assert fetch_job(engine, job2).status == "completed"
        assert provider.calls == 1  # job2 fully served from cache

    def test_cache_never_crosses_projects(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine_a, pa = make_db()
        backend = MemoryCacheBackend()
        provider = CountingProvider()
        job_a = add_job(engine_a, pa)
        with Session(engine_a, expire_on_commit=False) as db:
            run_transformation_job(
                db, job_a, llm_provider=provider, storage=storage,
                cache_backend=backend, cache_enabled=True,
            )
        # Separate engine/DB for a different project.
        engine_b, pb = make_db()
        job_b = add_job(engine_b, pb)
        with Session(engine_b, expire_on_commit=False) as db:
            run_transformation_job(
                db, job_b, llm_provider=provider, storage=storage,
                cache_backend=backend, cache_enabled=True,
            )
        assert provider.calls == 2  # different project scope => miss


# ---------------------------------------------------------------------------
# 11L-B / 11L-D — atomic worker claim
# ---------------------------------------------------------------------------

class TestAtomicClaim:
    def test_single_winner(self):
        engine, project_id = make_db()
        job_id = add_job(engine, project_id)
        with Session(engine, expire_on_commit=False) as db:
            claimed = db.execute(
                update(TransformationJob)
                .where(
                    TransformationJob.id == job_id,
                    TransformationJob.status.in_(("queued", "failed")),
                )
                .values(status="running")
            )
            assert claimed.rowcount == 1
            db.commit()
        with Session(engine, expire_on_commit=False) as db:
            second = db.execute(
                update(TransformationJob)
                .where(
                    TransformationJob.id == job_id,
                    TransformationJob.status.in_(("queued", "failed")),
                )
                .values(status="running")
            )
            assert second.rowcount == 0

    def test_claim_denied_runs_are_skipped(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id = make_db()
        job_id = add_job(engine, project_id)
        # Simulate another worker already holding the lease.
        with Session(engine, expire_on_commit=False) as db:
            db.execute(
                update(TransformationJob)
                .where(TransformationJob.id == job_id)
                .values(status="running")
            )
            db.commit()
        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id, llm_provider=CountingProvider(), storage=storage
            )
        assert result["skipped"] is True
        assert result["reason"] == "claim_denied_already_running_or_terminal"

    def test_failed_job_can_be_reclaimed_for_retry(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id = make_db()
        job_id = add_job(engine, project_id)
        with Session(engine, expire_on_commit=False) as db:
            db.execute(
                update(TransformationJob)
                .where(TransformationJob.id == job_id)
                .values(status="failed")
            )
            db.commit()
        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id, llm_provider=CountingProvider(), storage=storage
            )
        assert result["outputs_completed"] == 1
        assert fetch_job(engine, job_id).status == "completed"

    def test_completed_run_is_skipped_on_reentry(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id = make_db()
        job_id = add_job(engine, project_id)
        with Session(engine, expire_on_commit=False) as db:
            run_transformation_job(
                db, job_id, llm_provider=CountingProvider(), storage=storage
            )
        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id, llm_provider=CountingProvider(), storage=storage
            )
        assert result["skipped"] is True
        assert result["reason"] == "already_completed"


# ---------------------------------------------------------------------------
# 11L-C — metrics registry + rendering
# ---------------------------------------------------------------------------

class TestMetricsRegistry:
    def test_default_families_registered(self):
        text = render_metrics()
        for family in (
            "http_requests_total",
            "http_request_duration_seconds",
            "transformations_requested_total",
            "transformation_jobs_enqueued_total",
            "transformation_jobs_total",
            "transformation_outputs_total",
            "llm_requests_total",
            "llm_cache_hits_total",
            "artifacts_saved_total",
            "rag_retrievals_total",
            "rate_limit_triggered_total",
            "authn_denials_total",
            "authz_denials_total",
        ):
            assert f"# TYPE {family}" in text, family

    def test_counters_and_histograms_render(self):
        metrics.reset()
        metrics.inc("authn_denials_total", {"reason": "missing_token"})
        metrics.observe(
            "http_request_duration_seconds", 0.25,
            {"method": "GET", "route": "/health"},
        )
        text = render_metrics()
        assert 'authn_denials_total{reason="missing_token"} 1' in text
        assert 'http_request_duration_seconds_sum' in text
        assert 'http_request_duration_seconds_count' in text

    def test_no_high_cardinality_identifiers_in_output(self):
        metrics.reset()
        for _ in range(5):
            metrics.inc("llm_cache_hits_total", {"provider": "fake"})
            metrics.inc("transformations_requested_total")
        text = render_metrics()
        uuid_pattern = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        )
        assert uuid_pattern.search(text) is None

    def test_inc_rejects_zero_and_float(self):
        from app.core.metrics import MetricsRegistry

        reg = MetricsRegistry()
        reg.register_counter("c", "help")
        with pytest.raises(ValueError):
            reg.inc("c", amount=0)
        with pytest.raises(ValueError):
            reg.inc("c", amount=1.0)

    def test_unregistered_family_rejected(self):
        from app.core.metrics import MetricsRegistry

        reg = MetricsRegistry()
        with pytest.raises(KeyError):
            reg.inc("does_not_exist")
        with pytest.raises(KeyError):
            reg.observe("does_not_exist", 1.0)

    def test_unknown_label_rejected(self):
        from app.core.metrics import MetricsRegistry

        reg = MetricsRegistry()
        reg.register_counter("c", "help", labelnames=("allowed",))
        with pytest.raises(ValueError):
            reg.inc("c", {"never": "x"})


# ---------------------------------------------------------------------------
# 11L-C — worker push / backend load (fail-open, no data loss)
# ---------------------------------------------------------------------------

class FakePipe:
    def __init__(self, store: dict[bytes, int]) -> None:
        self.ops: list[tuple[str, Any, Any]] = []
        self.transaction = False
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def incrby(self, key: str, value: Any) -> None:
        self.ops.append(("incrby", key, value))

    def execute(self) -> None:
        for _kind, key, value in self.ops:
            encoded = key.encode()
            self.store[encoded] = self.store.get(encoded, 0) + int(value)


class FakeGoodConn:
    """In-memory fake for both pipeline pushes and keys/mget loads."""

    def __init__(self) -> None:
        self.store: dict[bytes, int] = {}
        self.last_pipe: FakePipe | None = None

    def pipeline(self, transaction: bool = False) -> "FakePipe":
        self.last_pipe = FakePipe(self.store)
        self.last_pipe.transaction = transaction
        return self.last_pipe

    def keys(self, pattern: str) -> list[bytes]:
        return sorted(self.store.keys())

    def mget(self, keys: list[bytes]) -> list[int | None]:
        return [self.store.get(k) for k in keys]


class TestWorkerMetricPushLoad:
    def test_push_fail_open_preserves_deltas(self):
        reg = MetricsRegistry()
        reg.register_counter("c_worker", "help", labelnames=("provider",))
        reg.inc("c_worker", {"provider": "fake"})
        conn = RaisingStubClient()
        result = push_worker_metrics(conn, registry=reg)
        assert result == 0
        assert reg.snapshot()["counters"]["c_worker"]  # deltas absorbed

    def test_load_fail_open_returns_empty(self):
        assert load_worker_metrics(RaisingStubClient()) == {
            "counters": {}, "histograms": {}
        }

    def test_push_writes_cumulative_redis_totals(self):
        reg = MetricsRegistry()
        reg.register_counter("c_worker", "help", labelnames=("provider",))
        reg.register_histogram("h_worker", "help", labelnames=("provider",))
        reg.inc("c_worker", {"provider": "fake"})
        reg.observe("h_worker", 0.5, {"provider": "fake"})
        conn = FakeGoodConn()
        commands = push_worker_metrics(conn, registry=reg)
        assert commands > 0
        keys = {k.decode() for k in conn.store}
        assert any(k.startswith("tq:metric:c:c_worker:") for k in keys)
        assert any(k.startswith("tq:metric:hs:h_worker:") for k in keys)
        assert any(k.startswith("tq:metric:hn:h_worker:") for k in keys)
        # Second push of the same delta must not rewrite (deltas consumed).
        assert push_worker_metrics(conn, registry=reg) == 0
        # Load round-trips the pushed totals.
        loaded = load_worker_metrics(conn)
        assert loaded["counters"]["c_worker"][(("provider", "fake"),)] == 1
        assert loaded["histograms"]["h_worker"][(("provider", "fake"),)]["count"] == 1


# ---------------------------------------------------------------------------
# 11L-C — /metrics endpoint + HTTP middleware
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        metrics.reset()
        with TestClient(app) as c:
            yield c
        metrics.reset()

    def test_metrics_endpoint_unauthenticated(self, client):
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_content_type(self, client):
        response = client.get("/metrics")
        assert response.headers["content-type"].startswith(
            "text/plain; version=0.0.4"
        )

    def test_metrics_body_has_families(self, client):
        text = client.get("/metrics").text
        assert "# TYPE http_requests_total" in text
        assert "# TYPE http_request_duration_seconds" in text
        assert "# TYPE llm_cache_misses_total" in text

    def test_metrics_body_has_no_secrets(self, client):
        text = client.get("/metrics").text.lower()
        for secret_token in ("bearer ", "a8f9", "api_key=", "password="):
            assert secret_token not in text

    def test_http_middleware_records_requests(self, client):
        client.get("/health")
        client.get("/health")
        client.get("/health")
        text = render_metrics()
        assert 'http_requests_total{method="GET",route="/health",status="200"} 3' in text

    def test_metrics_scrape_does_not_hang_on_redis_down(self, client):
        # The endpoint must stay healthy even if Redis (worker metrics) is down.
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_body_merges_worker_only_family(self, client):
        # A family pushed by the worker but never observed locally (e.g.
        # ingestion_jobs_total after a real worker run) must render instead of
        # raising a KeyError (regression: RHS evaluated before setdefault).
        from app.core.metrics import render_metrics

        worker = {
            "counters": {"ingestion_jobs_total": {(("kind", "source"), ("result", "completed")): 7}},
            "histograms": {},
        }
        text = render_metrics(worker_metrics=worker)
        assert 'ingestion_jobs_total{kind="source",result="completed"} 7' in text


# ---------------------------------------------------------------------------
# 11L-D — worker scaling entry point (source-level guard)
# ---------------------------------------------------------------------------

class TestWorkerScalingSourceGuard:
    WORKER_PATH = Path(__file__).resolve().parents[2] / "worker" / "worker.py"

    def test_entry_point_uses_worker_count(self):
        source = self.WORKER_PATH.read_text(encoding="utf-8")
        assert "WORKER_COUNT" in source
        assert "--worker-single" in source or "SINGLE_WORKER_FLAG" in source

    def test_legacy_concurrency_knob_no_longer_wired(self):
        source = self.WORKER_PATH.read_text(encoding="utf-8")
        assert "WORKER_CONCURRENCY" not in source
        assert "concurrency=" not in source


# ---------------------------------------------------------------------------
# 11L-G — configuration validation
# ---------------------------------------------------------------------------

class TestScalabilityConfig:
    def test_defaults_preserve_historical_behavior(self):
        from app.core.config import settings

        assert settings.CACHE_ENABLED is False
        assert settings.WORKER_COUNT == 1
        assert settings.CACHE_BACKEND == "memory"

    def test_worker_count_bounds(self):
        from app.core.config import Settings

        assert Settings(WORKER_COUNT=4).WORKER_COUNT == 4
        assert Settings(WORKER_COUNT=128).WORKER_COUNT == 128
        with pytest.raises(ValueError):
            Settings(WORKER_COUNT=0)
        with pytest.raises(ValueError):
            Settings(WORKER_COUNT=129)
        with pytest.raises(ValueError):
            Settings(WORKER_COUNT="four")

    def test_cache_ttl_bounds(self):
        from app.core.config import Settings

        assert Settings(CACHE_ENABLED=True, CACHE_TTL_SECONDS=600).CACHE_TTL_SECONDS == 600
        with pytest.raises(ValueError):
            Settings(CACHE_TTL_SECONDS=10)
        with pytest.raises(ValueError):
            Settings(CACHE_TTL_SECONDS=604801)

    def test_redis_backend_selector(self):
        from app.core.config import Settings

        assert Settings(CACHE_BACKEND="redis").CACHE_BACKEND == "redis"
        with pytest.raises(ValueError):
            Settings(CACHE_BACKEND="filesystem")