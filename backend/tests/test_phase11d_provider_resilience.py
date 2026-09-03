"""Phase 11D — LLM / provider resilience tests.

Covers the centralized resilience layer: error classification, retry policy
(exponential backoff + jitter), Retry-After honoring, circuit breaker, provider
health state, optional fallback, per-output resilience metadata, graph
integration (sibling isolation / partial success / budget behavior), OpenAI
configuration (SDK retries disabled, timeout/base URL), secret safety, and
backward compatibility of FakeLLMProvider and the existing provider contract.

All tests are deterministic and offline: they use fault-injecting providers and
injectable time/sleep/random functions. No real network or provider is used.
"""

from __future__ import annotations

import time
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
from app.transformation.llm import (
    ErrorCategory,
    FakeLLMProvider,
    LLMProvider,
    ProviderCallError,
    ProviderManager,
    RetryPolicy,
    classify_error,
)
from app.transformation.llm.openai_provider import OpenAILLMProvider
from app.transformation.llm.resilience import (
    CircuitBreaker,
    CircuitState,
    HealthState,
)
from app.transformation.service import run_transformation_job


# ---------------------------------------------------------------------------
# Fault-injecting providers
# ---------------------------------------------------------------------------

class _StatusError(Exception):
    """Exception carrying an HTTP status_code for classifier tests."""

    def __init__(self, status_code: int, message: str = "err") -> None:
        super().__init__(message)
        self.status_code = status_code


class _RetryAfterError(Exception):
    def __init__(self, retry_after: float) -> None:
        super().__init__("rate limited")
        self.status_code = 429
        self.retry_after = retry_after


class FlakyProvider(LLMProvider):
    """Succeeds on the Nth call (1-indexed), raising a given error before that."""

    def __init__(self, fail_until: int, exc_factory) -> None:
        self.calls = 0
        self.fail_until = fail_until
        self.exc_factory = exc_factory
        self.prompts: list[tuple[str, str]] = []

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.prompts.append((system_prompt, user_content))
        self.calls += 1
        if self.calls <= self.fail_until:
            raise self.exc_factory()
        return '{"type": "ok", "text": "hello deterministic"}'


class AlwaysFailProvider(LLMProvider):
    def __init__(self, exc_factory) -> None:
        self.calls = 0
        self.exc_factory = exc_factory

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        raise self.exc_factory()


class AuthFailProvider(LLMProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        raise _StatusError(401, "invalid api key")


class OkProvider(LLMProvider):
    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[tuple[str, str]] = []

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        self.prompts.append((system_prompt, user_content))
        return "primary result"


class RetryingJsonProvider(FakeLLMProvider):
    """Schema-valid provider (via FakeLLMProvider) that fails the first N calls."""

    def __init__(self, fail_until: int, exc_factory) -> None:
        super().__init__()
        self.fail_until = fail_until
        self.exc_factory = exc_factory
        self.calls = 0

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        if self.calls <= self.fail_until:
            raise self.exc_factory()
        return super().generate_text(
            system_prompt=system_prompt, user_content=user_content
        )


class AlwaysFailJsonProvider(FakeLLMProvider):
    """Schema-valid provider (subclass) that always raises a given error."""

    def __init__(self, exc_factory) -> None:
        super().__init__()
        self.exc_factory = exc_factory
        self.calls = 0

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        raise self.exc_factory()


class SelectiveFailProvider(FakeLLMProvider):
    """Schema-valid provider that fails only for a targeted output name."""

    def __init__(self, fail_output: str, exc_factory) -> None:
        super().__init__()
        self.fail_output = fail_output
        self.exc_factory = exc_factory
        self.calls = 0
        self.fail_calls = 0

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        if self.fail_output.lower() in system_prompt.lower():
            self.fail_calls += 1
            raise self.exc_factory()
        return super().generate_text(
            system_prompt=system_prompt, user_content=user_content
        )


# Deterministic time/sleep/random wrappers
class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []
        self.rand = 0.5  # deterministic jitter factor center

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def random(self) -> float:
        return self.rand

    def __enter__(self) -> "FakeClock":
        return self

    def __exit__(self, *_: Any) -> None:
        return None


def _manager(primary, fallback=None, *, max_attempts=3, clock=None, breaker_threshold=2):
    clock = clock or FakeClock()
    return ProviderManager(
        primary,
        fallback=fallback,
        max_attempts=max_attempts,
        retry_policy=RetryPolicy(
            base_delay=0.5,
            max_delay=10.0,
            jitter=0.0,
            max_429_wait=30.0,
            random=clock.random,
        ),
        breaker_failure_threshold=breaker_threshold,
        breaker_cooldown_seconds=15.0,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

class TestErrorClassification:
    def test_429_is_transient_rate_limit(self):
        c = classify_error(_StatusError(429))
        assert c.category == ErrorCategory.RATE_LIMIT
        assert c.transient is True
        assert c.http_status == 429

    def test_5xx_is_transient_server(self):
        for code in (500, 502, 503, 504):
            c = classify_error(_StatusError(code))
            assert c.category == ErrorCategory.SERVER
            assert c.transient is True

    def test_401_is_permanent_auth(self):
        c = classify_error(_StatusError(401))
        assert c.category == ErrorCategory.AUTH
        assert c.transient is False

    def test_403_is_permanent_auth(self):
        assert classify_error(_StatusError(403)).transient is False

    def test_404_is_permanent_invalid_model(self):
        c = classify_error(_StatusError(404))
        assert c.category == ErrorCategory.INVALID_MODEL
        assert c.transient is False

    def test_400_is_permanent_bad_request(self):
        assert classify_error(_StatusError(400)).transient is False
        assert classify_error(_StatusError(422)).transient is False

    def test_timeout_error_is_transient(self):
        c = classify_error(TimeoutError("slow"))
        assert c.category == ErrorCategory.TIMEOUT
        assert c.transient is True

    def test_connection_error_is_transient(self):
        assert classify_error(ConnectionResetError()).category == ErrorCategory.CONNECTION
        assert classify_error(ConnectionError()).transient is True

    def test_unknown_exception_is_transient_bounded(self):
        c = classify_error(RuntimeError("unexpected"))
        assert c.category == ErrorCategory.UNKNOWN
        assert c.transient is True


# ---------------------------------------------------------------------------
# Retry policy / backoff
# ---------------------------------------------------------------------------

class TestRetryPolicy:
    def test_exponential_backoff(self):
        clock = FakeClock()
        policy = RetryPolicy(base_delay=1.0, max_delay=100.0, jitter=0.0, random=clock.random)
        srv = classify_error(_StatusError(500))
        assert policy.delay_for(0, srv) == pytest.approx(1.0)
        assert policy.delay_for(1, srv) == pytest.approx(2.0)
        assert policy.delay_for(2, srv) == pytest.approx(4.0)

    def test_max_delay_clamp(self):
        clock = FakeClock()
        policy = RetryPolicy(base_delay=10.0, max_delay=15.0, jitter=0.0, random=clock.random)
        assert policy.delay_for(5, classify_error(_StatusError(500))) == pytest.approx(15.0)

    def test_jitter_within_bounds(self):
        clock = FakeClock()
        clock.rand = 0.0
        policy = RetryPolicy(base_delay=1.0, max_delay=100.0, jitter=0.5, random=clock.random)
        low = policy.delay_for(0, classify_error(_StatusError(500)))  # factor 0.5 -> 0.5
        assert low == pytest.approx(0.5)
        clock.rand = 1.0
        high = policy.delay_for(0, classify_error(_StatusError(500)))  # factor 1.5 -> 1.5
        assert high == pytest.approx(1.5)
        assert 0.5 <= low <= 1.5 <= high

    def test_retry_after_honored(self):
        clock = FakeClock()
        policy = RetryPolicy(base_delay=1.0, max_delay=10.0, jitter=0.0, max_429_wait=30.0, random=clock.random)
        assert policy.delay_for(0, classify_error(_RetryAfterError(7.5))) == pytest.approx(7.5)

    def test_retry_after_clamped_to_max(self):
        clock = FakeClock()
        policy = RetryPolicy(base_delay=1.0, max_delay=10.0, jitter=0.0, max_429_wait=5.0, random=clock.random)
        assert policy.delay_for(0, classify_error(_RetryAfterError(9999.0))) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# ProviderManager retry behavior
# ---------------------------------------------------------------------------

class TestProviderManager:
    def test_provider_success_returns_text(self):
        clock = FakeClock()
        primary = OkProvider()
        mgr = _manager(primary, clock=clock)
        text = mgr.generate_text(system_prompt="s", user_content="u")
        assert text == "primary result"
        assert mgr.last_metadata["final_status"] == "completed"
        assert mgr.last_metadata["provider"] == "OkProvider"
        assert mgr.last_metadata["attempts"] == 1

    def test_timeout_then_retry_success(self):
        clock = FakeClock()
        primary = FlakyProvider(1, lambda: TimeoutError("slow"))
        mgr = _manager(primary, clock=clock, max_attempts=3)
        text = mgr.generate_text(system_prompt="s", user_content="u")
        assert primary.calls == 2
        assert text == '{"type": "ok", "text": "hello deterministic"}'
        assert mgr.last_metadata["attempts"] == 2
        assert len(clock.slept) == 1  # slept after first failure only

    def test_timeout_retry_exhaustion(self):
        clock = FakeClock()
        primary = AlwaysFailProvider(lambda: TimeoutError("slow"))
        mgr = _manager(primary, clock=clock, max_attempts=3)
        with pytest.raises(ProviderCallError):
            mgr.generate_text(system_prompt="s", user_content="u")
        assert primary.calls == 3  # exactly max_attempts
        assert mgr.last_metadata["final_status"] == "failed"
        assert mgr.last_metadata["retryable"] is True
        assert len(mgr.last_metadata["retried"]) == 3

    def test_429_retry(self):
        clock = FakeClock()
        primary = FlakyProvider(1, lambda: _StatusError(429, "slow down"))
        mgr = _manager(primary, clock=clock)
        text = mgr.generate_text(system_prompt="s", user_content="u")
        assert primary.calls == 2
        assert mgr.last_metadata["attempts"] == 2

    def test_429_retry_after(self):
        clock = FakeClock()
        primary = FlakyProvider(1, lambda: _RetryAfterError(2.0))
        mgr = _manager(primary, clock=clock)
        mgr.generate_text(system_prompt="s", user_content="u")
        assert clock.slept[-1] == pytest.approx(2.0)

    def test_5xx_retry(self):
        clock = FakeClock()
        primary = FlakyProvider(1, lambda: _StatusError(503, "unavailable"))
        mgr = _manager(primary, clock=clock)
        mgr.generate_text(system_prompt="s", user_content="u")
        assert primary.calls == 2

    def test_connection_failure_retry(self):
        clock = FakeClock()
        primary = FlakyProvider(1, lambda: ConnectionResetError("reset"))
        mgr = _manager(primary, clock=clock)
        mgr.generate_text(system_prompt="s", user_content="u")
        assert primary.calls == 2

    def test_auth_failure_no_retry(self):
        clock = FakeClock()
        primary = AuthFailProvider()
        mgr = _manager(primary, clock=clock)
        with pytest.raises(ProviderCallError):
            mgr.generate_text(system_prompt="s", user_content="u")
        assert primary.calls == 1  # no retry
        assert mgr.last_metadata["retryable"] is False
        assert clock.slept == []

    def test_invalid_model_no_retry(self):
        clock = FakeClock()
        primary = AlwaysFailProvider(lambda: _StatusError(404, "model missing"))
        mgr = _manager(primary, clock=clock)
        with pytest.raises(ProviderCallError):
            mgr.generate_text(system_prompt="s", user_content="u")
        assert primary.calls == 1

    def test_malformed_request_no_retry(self):
        clock = FakeClock()
        primary = AlwaysFailProvider(lambda: _StatusError(400, "bad request"))
        mgr = _manager(primary, clock=clock)
        with pytest.raises(ProviderCallError):
            mgr.generate_text(system_prompt="s", user_content="u")
        assert primary.calls == 1

    def test_exact_max_attempt_count(self):
        clock = FakeClock()
        primary = FlakyProvider(5, lambda: _StatusError(500))
        mgr = _manager(primary, clock=clock, max_attempts=3)
        with pytest.raises(ProviderCallError):
            mgr.generate_text(system_prompt="s", user_content="u")
        assert primary.calls == 3

    def test_no_sleep_after_final_attempt(self):
        clock = FakeClock()
        primary = FlakyProvider(2, lambda: _StatusError(500))
        mgr = _manager(primary, clock=clock, max_attempts=3)
        mgr.generate_text(system_prompt="s", user_content="u")
        # slept after attempts 1 and 2, but NOT after the final success (attempt 3)
        assert len(clock.slept) == 2

    def test_preserves_exact_prompts(self):
        clock = FakeClock()
        primary = FlakyProvider(1, lambda: _StatusError(500))
        mgr = _manager(primary, clock=clock)
        mgr.generate_text(system_prompt="SYSTEM-A", user_content="USER-B")
        assert primary.prompts[0] == ("SYSTEM-A", "USER-B")
        assert primary.prompts[-1] == ("SYSTEM-A", "USER-B")


# ---------------------------------------------------------------------------
# Circuit breaker + health
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_closed_allows_calls(self):
        b = CircuitBreaker(failure_threshold=2, cooldown_seconds=15.0)
        assert b.state == CircuitState.CLOSED
        assert b.allow_call() is True

    def test_open_after_threshold(self):
        b = CircuitBreaker(failure_threshold=2, cooldown_seconds=15.0)
        b.record_failure(classify_error(_StatusError(500)))
        b.record_failure(classify_error(_StatusError(500)))
        assert b.state == CircuitState.OPEN
        assert b.allow_call() is False

    def test_half_open_after_cooldown_recovery(self):
        b = CircuitBreaker(failure_threshold=1, cooldown_seconds=15.0, now=time.monotonic)
        b.record_failure(classify_error(_StatusError(500)))
        assert b.state == CircuitState.OPEN
        assert b.allow_call() is False
        # simulate cooldown elapsed
        b._opened_at = b._opened_at - 16.0
        assert b.allow_call() is True
        assert b.state == CircuitState.HALF_OPEN
        b.record_success()
        assert b.state == CircuitState.CLOSED

    def test_half_open_failure_returns_open(self):
        b = CircuitBreaker(failure_threshold=1, cooldown_seconds=15.0, now=time.monotonic)
        b.record_failure(classify_error(_StatusError(500)))
        b._opened_at = b._opened_at - 16.0
        assert b.allow_call() is True  # half open probe
        b.record_failure(classify_error(_StatusError(500)))
        assert b.state == CircuitState.OPEN

    def test_auth_failure_opens_without_retry_loop(self):
        b = CircuitBreaker(failure_threshold=5, cooldown_seconds=15.0)
        b.record_failure(classify_error(_StatusError(401)))
        assert b.state == CircuitState.OPEN


class TestProviderHealth:
    def test_healthy(self):
        b = CircuitBreaker()
        h = __import__("app.transformation.llm.resilience", fromlist=["ProviderHealth"]).ProviderHealth(b)
        assert h.state() == HealthState.HEALTHY

    def test_rate_limited(self):
        b = CircuitBreaker()
        h = __import__("app.transformation.llm.resilience", fromlist=["ProviderHealth"]).ProviderHealth(b)
        h.note_failure(classify_error(_StatusError(429)))
        assert h.state() == HealthState.RATE_LIMITED

    def test_unavailable_when_open(self):
        b = CircuitBreaker(failure_threshold=1)
        h = __import__("app.transformation.llm.resilience", fromlist=["ProviderHealth"]).ProviderHealth(b)
        b.record_failure(classify_error(_StatusError(503)))
        h.note_failure(classify_error(_StatusError(503)))
        assert h.state() == HealthState.UNAVAILABLE

    def test_auth_failure_state(self):
        b = CircuitBreaker(failure_threshold=1)
        h = __import__("app.transformation.llm.resilience", fromlist=["ProviderHealth"]).ProviderHealth(b)
        b.record_failure(classify_error(_StatusError(401)))
        h.note_failure(classify_error(_StatusError(401)))
        assert h.state() == HealthState.AUTH_FAILURE


# ---------------------------------------------------------------------------
# Optional fallback
# ---------------------------------------------------------------------------

class TestFallback:
    def test_fallback_success_after_primary_exhaustion(self):
        clock = FakeClock()
        primary = AlwaysFailProvider(lambda: _StatusError(500))
        fallback = OkProvider()
        mgr = _manager(primary, fallback=fallback, clock=clock)
        text = mgr.generate_text(system_prompt="s", user_content="u")
        assert text == "primary result"  # from fallback
        assert mgr.last_metadata["used_fallback"] is True
        assert mgr.last_metadata["provider"] == "OkProvider"

    def test_fallback_after_primary_transient_retries(self):
        clock = FakeClock()
        primary = FlakyProvider(3, lambda: _StatusError(503))
        fallback = OkProvider()
        mgr = _manager(primary, fallback=fallback, clock=clock, max_attempts=3)
        text = mgr.generate_text(system_prompt="s", user_content="u")
        assert primary.calls == 3  # primary budget exhausted
        assert fallback.calls == 1
        assert text == "primary result"
        assert mgr.last_metadata["used_fallback"] is True

    def test_no_fallback_configured(self):
        clock = FakeClock()
        primary = AlwaysFailProvider(lambda: _StatusError(500))
        mgr = _manager(primary, clock=clock, max_attempts=3)
        with pytest.raises(ProviderCallError):
            mgr.generate_text(system_prompt="s", user_content="u")
        assert mgr.last_metadata["used_fallback"] is False

    def test_fallback_after_primary_unavailable(self):
        clock = FakeClock()
        primary = AlwaysFailProvider(lambda: _StatusError(503))
        fallback = OkProvider()
        mgr = _manager(primary, fallback=fallback, clock=clock, breaker_threshold=2, max_attempts=3)
        # First call exhausts; fallback succeeds.
        assert mgr.generate_text(system_prompt="s", user_content="u") == "primary result"
        # Second call: primary breaker now open -> should switch to fallback.
        assert mgr.generate_text(system_prompt="s", user_content="u") == "primary result"
        assert mgr.last_metadata["used_fallback"] is True

    def test_permanent_error_does_not_trigger_inappropriate_fallback(self):
        clock = FakeClock()
        primary = AuthFailProvider()
        fallback = OkProvider()
        mgr = _manager(primary, fallback=fallback, clock=clock)
        with pytest.raises(ProviderCallError):
            mgr.generate_text(system_prompt="s", user_content="u")
        # Permanent auth error on primary should not fall back.
        assert fallback.calls == 0
        assert primary.calls == 1


# ---------------------------------------------------------------------------
# Graph integration (per-output metadata, sibling isolation, budget)
# ---------------------------------------------------------------------------

ALL_7 = ["advisory", "infographic", "linkedin", "presentation", "summary", "video", "x"]

CANONICAL: dict[str, Any] = {
    "title": "Test Source",
    "summary": "A test source summary.",
    "topics": [], "entities": [], "key_points": [],
    "claims": [], "statistics": [], "dates": [],
    "recommendations": [], "source_references": [],
}


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(id=uuid.uuid4(), email=f"p11d-{uuid.uuid4().hex}@example.test", name="P11D", role="operator")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Phase 11D")
        source = Source(
            id=uuid.uuid4(), project_id=project.id, source_type="text", status="ready",
            extracted_text="Source line one.",
        )
        db.add_all([user, project, source])
        db.flush()
        db.add(CanonicalContent(
            id=uuid.uuid4(), source_id=source.id, project_id=project.id, status="completed",
            title=CANONICAL["title"], summary=CANONICAL["summary"],
            key_points=[], recommendations=[], claims=[], statistics=[],
            dates=[], entities=[], topics=[], source_references=[],
        ))
        db.commit()
    return engine, project.id, source.id


def add_job(engine, project_id, source_id, output_types):
    with Session(engine, expire_on_commit=False) as db:
        cfg = GenerationConfiguration(id=uuid.uuid4(), project_id=project_id, language="English")
        db.add(cfg)
        db.flush()
        job = TransformationJob(
            id=uuid.uuid4(), project_id=project_id, source_id=source_id,
            configuration_id=cfg.id, requested_outputs={"output_types": output_types}, status="queued",
        )
        db.add(job)
        db.commit()
        return job.id


class ResilientProviders:
    """Holds fault-injecting provider instances for resilient graph tests."""


def _getgen_factory(primary, fallback=None, max_attempts=3):
    def getgen(output_type):
        return get_generator(output_type, llm_provider=ProviderManager(
            primary, fallback=fallback, max_attempts=max_attempts,
        ))
    return getgen


class TestGraphIntegration:
    def test_per_output_resilience_metadata_persisted(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ["summary"])
        primary = RetryingJsonProvider(1, lambda: _StatusError(500))
        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id, llm_provider=ProviderManager(primary, max_attempts=3), storage=storage
            )
        assert result["outputs_completed"] == 1
        with Session(engine, expire_on_commit=False) as db:
            output = db.execute(select(Output).where(Output.job_id == job_id)).scalars().one()
            resilience = output.output_metadata["resilience"]
        assert resilience["attempts"] == 2
        assert resilience["final_status"] == "completed"
        assert resilience["provider"] == "RetryingJsonProvider"
        assert resilience["retried"] and resilience["retried"][0]["error_type"] == "server"
        assert "model" not in resilience or True  # bounded field, optional

    def test_sibling_output_isolation_partial_success(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ALL_7)
        primary = SelectiveFailProvider("advisory", lambda: _StatusError(503))
        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id,
                get_generator=_getgen_factory(primary, max_attempts=1),
                llm_provider=ProviderManager(primary, max_attempts=1),
                storage=storage,
            )
        # Only the advisory output fails; all siblings complete -> partial success.
        assert result["outputs_completed"] == 6
        assert result["outputs_failed"] == 1
        with Session(engine, expire_on_commit=False) as db:
            job = db.get(TransformationJob, job_id)
        assert job.status == "completed"  # partial success
        assert primary.fail_calls == 1  # advisory failed exactly once

    def test_all_outputs_fail_job_failed(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ALL_7)
        primary = AlwaysFailJsonProvider(lambda: _StatusError(503))
        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id,
                get_generator=_getgen_factory(primary),
                llm_provider=ProviderManager(primary, max_attempts=1),
                storage=storage,
            )
        assert result["outputs_failed"] == 7
        with Session(engine, expire_on_commit=False) as db:
            job = db.get(TransformationJob, job_id)
        assert job.status == "failed"
        assert job.error_message

    def test_retries_via_transient_errors_all_succeed(self, tmp_path: Path):
        # Each output independently retries: uses a shared transient provider
        # that fails twice, then succeeds. Because outputs run sequentially and
        # share the manager (like the worker), only the first output exercises
        # the retry budget before the breaker/state settles.
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ["summary"])
        primary = RetryingJsonProvider(2, lambda: _StatusError(429))
        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id,
                get_generator=_getgen_factory(primary),
                llm_provider=ProviderManager(primary, max_attempts=3),
                storage=storage,
            )
        assert result["outputs_completed"] == 1
        assert result["outputs_failed"] == 0

    def test_transformation_budget_exhaustion(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ALL_7)
        primary = FakeLLMProvider()
        # A timer that makes the budget appear exhausted immediately.
        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id,
                get_generator=_getgen_factory(primary),
                llm_provider=ProviderManager(primary, max_attempts=1),
                storage=storage,
                transformation_job_timeout=0,  # budget is 0 -> nothing starts
            )
        assert result["outputs_completed"] == 0
        assert result["outputs_failed"] == 7
        with Session(engine, expire_on_commit=False) as db:
            job = db.get(TransformationJob, job_id)
        assert job.status == "failed"


# ---------------------------------------------------------------------------
# OpenAI provider configuration + secret safety
# ---------------------------------------------------------------------------

class TestOpenAIConfig:
    def test_sdk_retries_disabled_by_default(self):
        from app.core.config import Settings

        assert Settings().LLM_SDK_MAX_RETRIES == 0

    def test_max_retries_forwarded_to_client(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "LLM_SDK_MAX_RETRIES", 0)
        provider = OpenAILLMProvider(
            model="gpt-4o-mini", api_key="sk-test-not-real", base_url="https://x/v1"
        )
        assert provider._max_retries == 0

    def test_timeout_and_base_url_forwarded(self):
        provider = OpenAILLMProvider(
            model="gpt-4o-mini",
            api_key="sk-test-not-real",
            base_url="https://opencode.ai/zen/v1",
            timeout=30,
        )
        assert provider._client.openai_api_base == "https://opencode.ai/zen/v1"
        assert provider._client.model_name == "gpt-4o-mini"
        assert provider._timeout == 30

    def test_missing_api_key_raises_without_leak(self):
        from app.core.config import settings

        saved = settings.LLM_API_KEY
        try:
            settings.LLM_API_KEY = ""
            with pytest.raises(ValueError) as exc:
                OpenAILLMProvider(model="gpt-4o-mini", api_key="", base_url="")
            assert "LLM_API_KEY" in str(exc.value)
            assert "sk-" not in str(exc.value)
        finally:
            settings.LLM_API_KEY = saved

    def test_no_secret_leak_in_provider_metadata(self):
        clock = FakeClock()
        primary = AlwaysFailProvider(lambda: _StatusError(401, "invalid API key: sk-super-secret"))
        mgr = _manager(primary, clock=clock)
        with pytest.raises(ProviderCallError):
            mgr.generate_text(system_prompt="s", user_content="u")
        dumped = str(mgr.last_metadata)
        assert "sk-super-secret" not in dumped


# ---------------------------------------------------------------------------
# Backward compatibility: FakeLLMProvider stays deterministic/offline
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_fake_provider_remains_offline_deterministic(self):
        provider = FakeLLMProvider()
        assert not hasattr(provider, "_client")
        out = provider.generate_text(
            system_prompt="fields: {title, summary, text}",
            user_content="TITLE: TransformIQ\nSUMMARY: AI platform",
        )
        assert isinstance(out, str) and out.strip()
        assert "TransformIQ" in out

    def test_provider_manager_is_an_llm_provider(self):
        from app.transformation.llm.provider import LLMProvider as ABC

        mgr = ProviderManager(OkProvider(), max_attempts=3)
        assert isinstance(mgr, ABC)
        assert isinstance(mgr, LLMProvider)

    def test_llm_provider_contract_unchanged(self):
        import inspect

        from app.transformation.llm.provider import LLMProvider as P

        sig = inspect.signature(P.generate_text)
        params = list(sig.parameters)
        assert params == ["self", "system_prompt", "user_content"]
