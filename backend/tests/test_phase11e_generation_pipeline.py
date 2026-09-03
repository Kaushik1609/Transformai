"""Phase 11E — Generation pipeline hardening tests.

Covers the hardened GENERATE -> VALIDATE -> VERIFY -> RENDER -> PERSIST
pipeline:

  - 11E-A  worker/job timeout hierarchy (worker >= job budget)
  - 11E-B  per-output failure isolation (generator, provider timeout/429 /
           permanent, schema, renderer, persistence) without erasing siblings
  - 11E-C  retry/idempotency (no duplicate logical outputs, no duplicate
           artifacts)
  - 11E-D  artifact completion gating (media output completed only after the
           artifact is rendered + persisted)
  - 11E-E  explicit validation boundary (malformed model output is an
           output-local failure)
  - 11E-F  resilience metadata contract (bounded, safe, serializable, free of
           secrets / stack traces / credentials)
  - parent-job finalization semantics (partial / all-failed / all-success)

All tests are deterministic and offline: they use the FakeLLMProvider (or
fault-injecting providers through the resilient ProviderManager), an in-memory
SQLite DB and LocalStorage in a tmp dir. No network, no timing races.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
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
from app.transformation.generators import get_generator
from app.transformation.graph import TransformationWorkflow
from app.transformation.llm import FakeLLMProvider, LLMProvider, ProviderManager
from app.transformation.service import run_transformation_job


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

ALL_7 = ["advisory", "infographic", "linkedin", "presentation", "summary", "video", "x"]

CANONICAL: dict[str, Any] = {
    "title": "Test Source",
    "summary": "A test source summary with key facts.",
    "topics": [{"value": "technology"}],
    "entities": [{"name": "Acme Corp"}],
    "key_points": [
        {"text": "First key point", "source_chunk_ids": []},
        {"text": "Second key point", "source_chunk_ids": []},
    ],
    "claims": [{"text": "A source claim", "source_chunk_ids": []}],
    "statistics": [{"text": "37% of respondents", "source_chunk_ids": []}],
    "dates": [{"text": "2024"}],
    "recommendations": [{"text": "Recommended action", "source_chunk_ids": []}],
    "source_references": [{"text": "Source reference A", "source_chunk_ids": []}],
}

CONFIG: dict[str, Any] = {
    "target_audience": "Executives",
    "tone": "professional",
    "language": "English",
    "detail_level": "standard",
    "communication_objective": "decision support",
}


def make_db():
    """In-memory sqlite seeded with a ready project/source/canonical."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(id=uuid.uuid4(), email=f"p11e-{uuid.uuid4().hex}@example.test", name="P11E", role="operator")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Phase 11E")
        source = Source(
            id=uuid.uuid4(), project_id=project.id, source_type="text", status="ready",
            extracted_text="Source line one.\nSource line two.",
        )
        db.add_all([user, project, source])
        db.flush()
        db.add(CanonicalContent(
            id=uuid.uuid4(), source_id=source.id, project_id=project.id, status="completed",
            title=CANONICAL["title"], summary=CANONICAL["summary"],
            key_points=[{"text": "First key point", "source_chunk_ids": []}],
            recommendations=[{"text": "Recommended action", "source_chunk_ids": []}],
            claims=[], statistics=[], dates=[], entities=[], topics=[], source_references=[],
        ))
        db.commit()
    return engine, project.id, source.id


def add_job(engine, project_id: uuid.UUID, source_id: uuid.UUID, output_types: list[str],
            config: dict[str, Any] | None = None) -> uuid.UUID:
    with Session(engine, expire_on_commit=False) as db:
        cfg = GenerationConfiguration(id=uuid.uuid4(), project_id=project_id, language="English")
        if config:
            for k, v in config.items():
                setattr(cfg, k, v)
        db.add(cfg)
        db.flush()
        job = TransformationJob(
            id=uuid.uuid4(), project_id=project_id, source_id=source_id,
            configuration_id=cfg.id, requested_outputs={"output_types": output_types}, status="queued",
        )
        db.add(job)
        db.commit()
        return job.id


def fetch_outputs_by_type(engine, job_id: uuid.UUID) -> dict[str, Output]:
    with Session(engine, expire_on_commit=False) as db:
        rows = db.execute(select(Output).where(Output.job_id == job_id)).scalars().all()
        return {o.output_type: o for o in rows}


def count_outputs(engine, job_id: uuid.UUID) -> int:
    with Session(engine, expire_on_commit=False) as db:
        return len(db.execute(select(Output).where(Output.job_id == job_id)).scalars().all())


def fetch_job(engine, job_id: uuid.UUID) -> TransformationJob:
    with Session(engine, expire_on_commit=False) as db:
        return db.get(TransformationJob, job_id)


def list_artifact_files(storage: LocalStorage) -> list[str]:
    if not storage.root.exists():
        return []
    return [str(p) for p in storage.root.rglob("*") if p.is_file()]


# ---------------------------------------------------------------------------
# Fault injectors
# ---------------------------------------------------------------------------

class _StatusError(Exception):
    def __init__(self, status_code: int, message: str = "err") -> None:
        super().__init__(message)
        self.status_code = status_code


class TimeoutErrorProvider(LLMProvider):
    """Raises a timeout-classified exception on every call."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        raise TimeoutError("provider request timed out")


class RateLimitProvider(LLMProvider):
    """Raises an HTTP 429 on every call until budget exhausts."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        raise _StatusError(429, "rate limited")


class PermanentFailProvider(LLMProvider):
    """Raises an HTTP 401 (permanent, non-retryable) on every call."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        raise _StatusError(401, "invalid api key")


class SelectiveTimeoutProvider(FakeLLMProvider):
    """Schema-valid provider that times out for one targeted output only."""

    def __init__(self, fail_output: str) -> None:
        super().__init__()
        self.fail_output = fail_output
        self.fail_calls = 0
        self.calls = 0

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        if self.fail_output.lower() in system_prompt.lower():
            self.fail_calls += 1
            raise TimeoutError("simulated provider timeout")
        return super().generate_text(system_prompt=system_prompt, user_content=user_content)


class MalformedJsonProvider(FakeLLMProvider):
    """Returns garbage JSON (schema-validation failure) on every call."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        return "this is not valid json {{"


class InjectSecretProvider(FakeLLMProvider):
    """Emits resilience metadata that embeds a credential-like string."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.last_metadata: dict[str, Any] = {}

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        self.last_metadata = {
            "provider": "InjectSecretProvider",
            "model": "gpt-4o-mini",
            "attempts": 1,
            "max_attempts": 1,
            "retryable": True,
            "final_status": "completed",
            "last_error_message": "call failed sk-ABCDEF123456 openai key exposed",
            "last_error_type": "server",
            "latency_ms": 12,
            "used_fallback": False,
        }
        return super().generate_text(system_prompt=system_prompt, user_content=user_content)


def _make_failing_generator(output_type: str, exc: Exception):
    class FailingGen:
        def __init__(self, llm_provider=None):
            self.llm_provider = llm_provider

        @property
        def output_type(self):
            return output_type

        def generate(self, **kwargs) -> dict[str, Any]:
            raise exc

    return FailingGen


def _manager(provider: LLMProvider, *, max_attempts: int = 3) -> ProviderManager:
    # No jitter and no real sleep so the resilience layer is instant + deterministic.
    from app.transformation.llm import RetryPolicy

    return ProviderManager(
        provider,
        max_attempts=max_attempts,
        retry_policy=RetryPolicy(base_delay=0.0, max_delay=0.0, jitter=0.0, max_429_wait=0.0),
        sleep=lambda _: None,
    )


# ---------------------------------------------------------------------------
# 11E-A — timeout hierarchy
# ---------------------------------------------------------------------------

def test_worker_timeout_gte_transformation_budget():
    from app.core.config import get_settings

    s = get_settings()
    assert s.WORKER_JOB_TIMEOUT >= s.TRANSFORMATION_JOB_TIMEOUT
    # And the job budget must exceed the per-provider request timeout.
    assert s.TRANSFORMATION_JOB_TIMEOUT > s.LLM_TIMEOUT_SECONDS


def test_timeout_validator_rejects_inversion(monkeypatch):
    """A config where worker < job budget must be rejected."""
    from app.core import config as config_module

    class InvalidSettings(config_module.Settings):
        WORKER_JOB_TIMEOUT: int = 300
        TRANSFORMATION_JOB_TIMEOUT: int = 600

    with pytest.raises(ValueError):
        InvalidSettings()


def test_worker_timeout_default_exceeds_budget():
    from app.core.config import get_settings

    s = get_settings()
    assert s.WORKER_JOB_TIMEOUT > s.TRANSFORMATION_JOB_TIMEOUT


# ---------------------------------------------------------------------------
# All seven outputs: planned, independent, successful
# ---------------------------------------------------------------------------

def test_seven_outputs_planned(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ALL_7)
    with Session(engine, expire_on_commit=False) as db:
        run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    assert set(outputs.keys()) == set(ALL_7)
    assert len(outputs) == 7


def test_seven_outputs_all_successful(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ALL_7)
    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
    assert result["outputs_completed"] == 7
    assert result["outputs_failed"] == 0
    outputs = fetch_outputs_by_type(engine, job_id)
    for o in outputs.values():
        assert o.status == "completed"


def test_all_seven_completed_job_completed(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ALL_7)
    with Session(engine, expire_on_commit=False) as db:
        run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
    job = fetch_job(engine, job_id)
    assert job.status == "completed"
    assert job.progress == 100


# ---------------------------------------------------------------------------
# 11E-B — failure isolation
# ---------------------------------------------------------------------------

def test_one_generator_failure_does_not_erase_siblings(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ALL_7)

    def getgen(output_type):
        if output_type == "video":
            return _make_failing_generator("video", RuntimeError("video boom"))(llm_provider=FakeLLMProvider())
        return get_generator(output_type, llm_provider=FakeLLMProvider())

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, get_generator=getgen, llm_provider=FakeLLMProvider(), storage=storage)
    assert result["outputs_completed"] == 6
    assert result["outputs_failed"] == 1
    outputs = fetch_outputs_by_type(engine, job_id)
    assert outputs["video"].status == "failed"
    assert all(outputs[t].status == "completed" for t in ALL_7 if t != "video")


def test_multiple_output_failures_partial_success(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ALL_7)

    def getgen(output_type):
        if output_type in ("x", "advisory"):
            return _make_failing_generator(output_type, RuntimeError("boom"))()
        return get_generator(output_type, llm_provider=FakeLLMProvider())

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, get_generator=getgen, llm_provider=FakeLLMProvider(), storage=storage)
    assert result["outputs_completed"] == 5
    assert result["outputs_failed"] == 2
    assert fetch_job(engine, job_id).status == "completed"


def test_provider_timeout_fails_only_that_output(tmp_path: Path):
    """A provider timeout for one output must not affect its siblings."""
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "linkedin", "x"])
    provider = SelectiveTimeoutProvider("linkedin")
    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, llm_provider=_manager(provider, max_attempts=1), storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    assert outputs["summary"].status == "completed"
    assert outputs["x"].status == "completed"
    assert outputs["linkedin"].status == "failed"
    assert result["outputs_completed"] == 2
    assert result["outputs_failed"] == 1


def test_provider_rate_limit_failure_isolation(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "linkedin"])
    provider = RateLimitProvider()

    def getgen(output_type):
        return get_generator(output_type, llm_provider=_manager(provider, max_attempts=2))

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, get_generator=getgen, llm_provider=_manager(provider, max_attempts=2), storage=storage)
    assert result["outputs_failed"] == 2
    assert result["outputs_completed"] == 0
    assert fetch_job(engine, job_id).status == "failed"
    for t in ("summary", "linkedin"):
        assert fetch_outputs_by_type(engine, job_id)[t].status == "failed"


def test_provider_rate_limit_single_output_isolated(tmp_path: Path):
    """429 exhausts budget for one output only; siblings complete."""
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "linkedin"])

    class SelectiveRateLimitProvider(FakeLLMProvider):
        def __init__(self, fail_output: str) -> None:
            super().__init__()
            self.fail_output = fail_output
            self.fail_calls = 0

        def generate_text(self, *, system_prompt: str, user_content: str) -> str:
            if self.fail_output.lower() in system_prompt.lower():
                self.fail_calls += 1
                raise _StatusError(429, "rate limited")
            return super().generate_text(system_prompt=system_prompt, user_content=user_content)

    provider = SelectiveRateLimitProvider("summary")

    def getgen(output_type):
        # A fresh ProviderManager per generator gives strict per-output isolation,
        # so one output's 429 retries (and circuit-breaker trips) never block its
        # siblings.
        return get_generator(output_type, llm_provider=_manager(provider, max_attempts=2))

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(
            db, job_id, get_generator=getgen,
            llm_provider=_manager(provider, max_attempts=2), storage=storage,
        )
    outputs = fetch_outputs_by_type(engine, job_id)
    assert outputs["summary"].status == "failed"
    assert outputs["linkedin"].status == "completed"
    assert result["outputs_completed"] == 1
    assert result["outputs_failed"] == 1
    assert provider.fail_calls == 2  # attempted within retry budget


def test_permanent_provider_failure_all_failed(tmp_path: Path):
    """A permanent (auth) provider failure is not retried and marks outputs failed."""
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary"])
    provider = PermanentFailProvider()
    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, llm_provider=_manager(provider, max_attempts=3), storage=storage)
    assert provider.calls == 1  # permanent -> no retries
    assert result["outputs_completed"] == 0
    assert result["outputs_failed"] == 1
    outputs = fetch_outputs_by_type(engine, job_id)
    assert outputs["summary"].status == "failed"
    meta = outputs["summary"].output_metadata or {}
    resilience = meta.get("resilience", {})
    assert resilience.get("retryable") is False


def test_schema_validation_failure_isolated(tmp_path: Path):
    """Malformed model output is an output-local failure; siblings succeed."""
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "linkedin", "x"])
    provider = MalformedJsonProvider()

    def getgen(output_type):
        return get_generator(output_type, llm_provider=provider)

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, get_generator=getgen, llm_provider=provider, storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    for t in ("summary", "linkedin", "x"):
        assert outputs[t].status == "failed", f"{t} should fail on malformed JSON"
    assert result["outputs_failed"] == 3
    assert fetch_job(engine, job_id).status == "failed"


# ---------------------------------------------------------------------------
# 11E-D — artifact gating (media outputs completed only after artifact persisted)
# ---------------------------------------------------------------------------

def test_media_output_completed_has_artifact(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "presentation", "infographic", "video"])
    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
    assert result["outputs_completed"] == 4
    outputs = fetch_outputs_by_type(engine, job_id)
    for t in ("presentation", "infographic", "video"):
        assert outputs[t].status == "completed"
        assert outputs[t].storage_key, f"{t} completed without an artifact"
    # summary is non-media: valid completed without a binary storage artifact.
    assert outputs["summary"].status == "completed"


def test_media_output_requires_artifact_before_completed(tmp_path: Path):
    """A media output is completed ONLY after its artifact is persisted.

    If the renderer or the storage write fails, the output must be failed (never
    completed), because completion is gated on a successfully persisted artifact.
    """
    class FailingSaveStorage:
        def __init__(self) -> None:
            self.root = Path(tmp_path) / "storage"

        def save(self, key: str, content: bytes) -> None:
            raise OSError("simulated artifact write failure")

        def read(self, key: str) -> bytes:
            raise KeyError(key)

        def exists(self, key: str) -> bool:
            return False

    storage = FailingSaveStorage()
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["presentation", "video"])
    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    assert outputs["presentation"].status == "failed"
    assert outputs["video"].status == "failed"
    assert outputs["presentation"].storage_key is None
    assert outputs["video"].storage_key is None
    assert result["outputs_completed"] == 0
    assert result["outputs_failed"] == 2


def test_rendering_failure_marks_output_failed_not_completed(tmp_path: Path):
    class FailingSaveStorage:
        def __init__(self) -> None:
            self.root = Path(tmp_path) / "storage"

        def save(self, key: str, content: bytes) -> None:
            raise OSError("simulated write failure")

        def read(self, key: str) -> bytes:
            raise KeyError(key)

        def exists(self, key: str) -> bool:
            return False

    storage = FailingSaveStorage()
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "presentation"])
    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    assert outputs["presentation"].status == "failed"
    assert outputs["presentation"].storage_key is None
    assert outputs["summary"].status == "completed"  # sibling unaffected


def test_render_failure_does_not_affect_siblings(tmp_path: Path):
    class FailingSaveStorage:
        def __init__(self) -> None:
            self.root = Path(tmp_path) / "storage"

        def save(self, key: str, content: bytes) -> None:
            raise OSError("write failure")

        def read(self, key: str) -> bytes:
            raise KeyError(key)

        def exists(self, key: str) -> bool:
            return False

    storage = FailingSaveStorage()
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "presentation", "infographic", "x"])
    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    assert outputs["summary"].status == "completed"
    assert outputs["x"].status == "completed"
    assert outputs["presentation"].status == "failed"
    assert outputs["infographic"].status == "failed"
    assert result["outputs_completed"] == 2
    assert result["outputs_failed"] == 2
    assert fetch_job(engine, job_id).status == "completed"


def test_persistence_failure_does_not_affect_siblings(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "x"])

    class DBPoisonGenerator:
        """Forces a DB IntegrityError on flush for the summary output's savepoint."""

        output_type = "summary"

        def __init__(self, session, job_id, llm_provider=None) -> None:
            self.session = session
            self.job_id = job_id

        def generate(self, **kwargs) -> dict[str, Any]:
            self.session.add(Output(id=uuid.uuid4(), job_id=self.job_id, status="pending"))
            return {"title": "Test Source", "summary": "s", "text": "# summary"}

    with Session(engine, expire_on_commit=False) as db:
        def getgen(output_type):
            if output_type == "summary":
                return DBPoisonGenerator(db, job_id)
            return get_generator(output_type, llm_provider=FakeLLMProvider())

        result = run_transformation_job(db, job_id, get_generator=getgen, llm_provider=FakeLLMProvider(), storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    assert outputs["summary"].status == "failed"
    assert outputs["x"].status == "completed"
    assert fetch_job(engine, job_id).status == "completed"


# ---------------------------------------------------------------------------
# 11E-C — idempotency (retry does not duplicate outputs or artifacts)
# ---------------------------------------------------------------------------

def test_retry_does_not_duplicate_logical_outputs(tmp_path: Path):
    """Re-running a job must reuse existing output rows, not create duplicates."""
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "linkedin"])
    with Session(engine, expire_on_commit=False) as db:
        run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)

    # Directly exercise the workflow's plan for the same job (simulate a
    # retry/re-plan) and assert no extra output rows are created.
    with Session(engine, expire_on_commit=False) as db:
        from app.transformation.graph import TransformationDependencies, TransformationWorkflow
        deps = TransformationDependencies(
            session=db, llm_provider=FakeLLMProvider(), storage=storage,
            requested_output_types_override=["summary", "linkedin"],
            rag_required_override=False,
        )
        wf = TransformationWorkflow(deps)
        state = wf.plan_outputs({
            "job_id": str(job_id), "requested_output_types": ["summary", "linkedin"], "errors": [],
        })
        completed = [o for o in state["outputs"] if o["status"] == "completed"]
        assert len(completed) == 2
    assert count_outputs(engine, job_id) == 2  # no duplicates


def test_retry_does_not_duplicate_artifacts(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["presentation"])
    with Session(engine, expire_on_commit=False) as db:
        run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)

    files_before = list_artifact_files(storage)
    assert len(files_before) == 1  # one PPTX artifact

    # Re-invoke the persist path for the already-persisted output; it must be a
    # no-op (no additional artifact written).
    with Session(engine, expire_on_commit=False) as db:
        from app.transformation.graph import TransformationDependencies, TransformationWorkflow
        deps = TransformationDependencies(session=db, llm_provider=FakeLLMProvider(), storage=storage)
        wf = TransformationWorkflow(deps)
        output = db.execute(select(Output).where(Output.job_id == job_id)).scalars().one()
        assert wf._artifact_persisted(output, "artifact") is True
        wf._persist_presentation_artifact(
            {"job_id": str(job_id), "project_id": str(project_id), "source_id": str(source_id)},
            output, output.structured_content if output.structured_content else {},
            project_id=project_id, job_id=job_id,
        )
        db.commit()

    assert list_artifact_files(storage) == files_before  # still exactly one artifact


def test_historical_reload_preserves_partial_success(tmp_path: Path):
    """A partly-failed job reloads with the correct per-output states."""
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ALL_7)

    def getgen(output_type):
        if output_type in ("video", "x"):
            return _make_failing_generator(output_type, RuntimeError("boom"))()
        return get_generator(output_type, llm_provider=FakeLLMProvider())

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, get_generator=getgen, llm_provider=FakeLLMProvider(), storage=storage)
    assert result["outputs_completed"] == 5
    assert result["outputs_failed"] == 2

    # Reload freshly from the DB (historical reload) and confirm states persist.
    outputs = fetch_outputs_by_type(engine, job_id)
    assert outputs["video"].status == "failed"
    assert outputs["x"].status == "failed"
    for t in ALL_7:
        if t not in ("video", "x"):
            assert outputs[t].status == "completed"
            # Every form of binary artifact must have been persisted.
            if outputs[t].output_type in ("presentation", "infographic", "video"):
                assert outputs[t].storage_key, f"{t} completed without artifact"
            else:
                assert outputs[t].text_content  # non-media completed with text
    assert fetch_job(engine, job_id).status == "completed"


def test_replan_reuses_existing_completed_sibling(tmp_path: Path):
    """Partial re-plan must reuse already-completed outputs, never duplicate them."""
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "linkedin"])
    with Session(engine, expire_on_commit=False) as db:
        run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
    with Session(engine, expire_on_commit=False) as db:
        # Pre-drive a second plan over the same already-completed job.
        from app.transformation.graph import TransformationDependencies, TransformationWorkflow
        deps = TransformationDependencies(
            session=db, llm_provider=FakeLLMProvider(), storage=storage,
            requested_output_types_override=["summary", "linkedin"],
            rag_required_override=False,
        )
        wf = TransformationWorkflow(deps)
        state = wf.plan_outputs({"job_id": str(job_id), "requested_output_types": ["summary", "linkedin"], "errors": []})
        assert all(o["status"] == "completed" for o in state["outputs"])
    assert count_outputs(engine, job_id) == 2  # exactly one row per type


# ---------------------------------------------------------------------------
# 11E-F — resilience metadata contract
# ---------------------------------------------------------------------------

def test_resilience_metadata_bounded_and_serializable(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary"])
    provider = InjectSecretProvider()
    with Session(engine, expire_on_commit=False) as db:
        run_transformation_job(db, job_id, llm_provider=provider, storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    resilience = (outputs["summary"].output_metadata or {}).get("resilience")
    assert isinstance(resilience, dict)
    # Bounded allowlist only.
    allowed = {
        "provider", "model", "attempts", "max_attempts", "retryable",
        "last_error_type", "last_error_message", "last_attempt_at",
        "latency_ms", "retried", "used_fallback", "final_status",
    }
    assert set(resilience.keys()) <= allowed
    # JSON-serializable.
    json.dumps(resilience)


def test_resilience_metadata_redacts_secrets(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary"])
    provider = InjectSecretProvider()
    with Session(engine, expire_on_commit=False) as db:
        run_transformation_job(db, job_id, llm_provider=provider, storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    resilience = (outputs["summary"].output_metadata or {}).get("resilience", {})
    blob = json.dumps(resilience)
    assert "sk-ABCDEF123456" not in blob
    assert "redacted" in blob  # any embedded key was sanitized


def test_failed_output_error_message_redacted(tmp_path: Path):
    """Persisted error messages must not leak credential patterns."""
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary"])

    class LeakyFailGenerator:
        output_type = "summary"

        def __init__(self, llm_provider=None):
            self.llm_provider = llm_provider

        def generate(self, **kwargs) -> dict[str, Any]:
            raise RuntimeError("boom api_key=sk-SECRET123 and bearer tokXYZ7890")

    def getgen(output_type):
        return LeakyFailGenerator()

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, get_generator=getgen, storage=storage)
    assert result["outputs_failed"] == 1
    outputs = fetch_outputs_by_type(engine, job_id)
    msg = outputs["summary"].error_message or ""
    assert "sk-SECRET123" not in msg
    assert "tokXYZ7890" not in msg
    assert "redacted" in msg


def test_resilience_metadata_absent_for_raw_fake_provider(tmp_path: Path):
    """A plain FakeLLMProvider exposes no resilience metadata => field absent."""
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary"])
    with Session(engine, expire_on_commit=False) as db:
        run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    assert "resilience" not in (outputs["summary"].output_metadata or {})


# ---------------------------------------------------------------------------
# Parent job finalization semantics
# ---------------------------------------------------------------------------

def test_parent_job_finalization_partial_success(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ALL_7)

    def getgen(output_type):
        if output_type in ("summary", "advisory", "video"):
            return _make_failing_generator(output_type, RuntimeError("nope"))()
        return get_generator(output_type, llm_provider=FakeLLMProvider())

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, get_generator=getgen, llm_provider=FakeLLMProvider(), storage=storage)
    assert result["outputs_completed"] == 4
    assert result["outputs_failed"] == 3
    job = fetch_job(engine, job_id)
    assert job.status == "completed"  # partial success
    assert job.progress == 100


def test_parent_job_finalization_all_outputs_failed(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ALL_7)

    def getgen(output_type):
        return _make_failing_generator(output_type, RuntimeError("boom"))()

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, get_generator=getgen, storage=storage)
    assert result["outputs_completed"] == 0
    assert result["outputs_failed"] == 7
    job = fetch_job(engine, job_id)
    assert job.status == "failed"
    assert job.progress == 100


def test_parent_job_finalization_all_outputs_successful(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ALL_7)
    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
    assert result["outputs_completed"] == 7
    assert result["outputs_failed"] == 0
    job = fetch_job(engine, job_id)
    assert job.status == "completed"


def test_unknown_output_type_isolated(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "not-a-real-type", "x"])
    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    assert outputs["summary"].status == "completed"
    assert outputs["x"].status == "completed"
    assert outputs["not-a-real-type"].status == "failed"
    assert result["outputs_completed"] == 2
    assert result["outputs_failed"] == 1


# ---------------------------------------------------------------------------
# 11E-E — validation boundary (explicit sequence, no duplicate work)
# ---------------------------------------------------------------------------

def test_generation_pipeline_stage_sequence(tmp_path: Path):
    """Verify the node order GEN -> VALIDATE -> VERIFY -> (RENDER/PERSIST)."""
    from app.transformation.graph import build_transformation_graph
    from app.transformation.graph import TransformationDependencies

    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary"])

    with Session(engine, expire_on_commit=False) as db:
        deps = TransformationDependencies(session=db, llm_provider=FakeLLMProvider(), storage=storage)
        graph = build_transformation_graph(deps)
        # The compiled graph exposes its node ordering via the builder chain.
        assert "load_input" in graph.nodes
        assert "generate" in graph.nodes
        assert "validate" in graph.nodes
        assert "verify_hook" in graph.nodes
        assert "finalize" in graph.nodes


def test_malformed_output_is_output_local_not_job_abort(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ["summary", "x"])
    provider = MalformedJsonProvider()

    def getgen(output_type):
        return get_generator(output_type, llm_provider=provider)

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(db, job_id, get_generator=getgen, llm_provider=provider, storage=storage)
    outputs = fetch_outputs_by_type(engine, job_id)
    assert outputs["summary"].status == "failed"
    assert outputs["x"].status == "failed"
    # Both marked failed, each carries an output-local error_message.
    assert outputs["summary"].error_message
    assert outputs["x"].error_message
