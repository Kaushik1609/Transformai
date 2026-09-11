"""Phase 11I-2 — Retry amplification bound (embedding stack, single ceiling).

Verifies that embedding retries happen in exactly ONE layer with ONE documented
ceiling:

  1.  SDK-level auto-retries are disabled (EMBEDDING_SDK_MAX_RETRIES == 0).
  2.  EMBEDDING_MAX_TOTAL_ATTEMPTS is the single ceiling and is always
      EMBEDDING_MAX_RETRIES + 1.
  3.  The resilient wrapper never exceeds that ceiling — total attempts are
      bounded, so SDK + app-layer retries can never amplify (worst case was
      (retries + 1) * (retries + 1) = 9 before the fix).
  4.  Transient errors still recover within budget (no infinite loop).
  5.  The factory wires the named ceiling into the resilient wrapper.
  6.  EMBEDDING_SDK_MAX_RETRIES is validated (0..10).

Deterministic and offline: fault-injecting providers + injected clock/sleep.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings, settings
from app.core.resilience import RetryPolicy
from app.embeddings import (
    EmbeddingResilientProvider,
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
    build_embedding_provider,
)
from app.embeddings.resilience import ProviderCallError

DUMMY_KEY = "sk-test-not-real"
DUMMY_VECTOR = [0.1] * 1536


class _FakeEmbeddingsClient:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, *, model=None, input=None):
        self.calls += 1
        raise AssertionError("embeddings.create must not be reached in these tests")


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []
        self.rand = 0.5

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def random(self) -> float:
        return self.rand


class _StatusError(Exception):
    def __init__(self, status_code: int, message: str = "err") -> None:
        super().__init__(message)
        self.status_code = status_code


class _AlwaysFailProvider:
    def __init__(self, exc_factory) -> None:
        self.calls = 0
        self.exc_factory = exc_factory

    def embed_texts(self, texts):
        self.calls += 1
        raise self.exc_factory()


class _FlakyProvider:
    def __init__(self, fail_until: int, exc_factory) -> None:
        self.calls = 0
        self.fail_until = fail_until
        self.exc_factory = exc_factory

    def embed_texts(self, texts):
        self.calls += 1
        if self.calls <= self.fail_until:
            raise self.exc_factory()
        return [DUMMY_VECTOR for _ in texts]


def _resilient(provider, clock, *, max_attempts):
    return EmbeddingResilientProvider(
        provider,
        max_attempts=max_attempts,
        retry_policy=RetryPolicy(
            base_delay=1.0, max_delay=10.0, jitter=0.0, random=clock.random
        ),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


# ---------------------------------------------------------------------------
# 1 Single ceiling semantics
# ---------------------------------------------------------------------------

def test_single_ceiling_constant():
    assert Settings().EMBEDDING_MAX_TOTAL_ATTEMPTS == 3
    assert settings.EMBEDDING_MAX_TOTAL_ATTEMPTS == settings.EMBEDDING_MAX_RETRIES + 1
    assert settings.EMBEDDING_SDK_MAX_RETRIES == 0


def test_resilient_default_uses_named_ceiling():
    clock = _FakeClock()
    provider = EmbeddingResilientProvider(
        _AlwaysFailProvider(lambda: TimeoutError("slow")),
        retry_policy=RetryPolicy(base_delay=1.0, max_delay=10.0, jitter=0.0),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert provider._max_attempts == settings.EMBEDDING_MAX_TOTAL_ATTEMPTS


def test_factory_wraps_using_named_ceiling(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", DUMMY_KEY)
    provider = build_embedding_provider()
    assert isinstance(provider, EmbeddingResilientProvider)
    assert provider._max_attempts == settings.EMBEDDING_MAX_TOTAL_ATTEMPTS == 3


# ---------------------------------------------------------------------------
# 2 SDK layer is disabled (no amplification source)
# ---------------------------------------------------------------------------

def test_sdk_retries_disabled_by_default(monkeypatch):
    default = OpenAIEmbeddingProvider(api_key=DUMMY_KEY, client=_FakeEmbeddingsClient())
    assert default._max_retries == 0
    assert default._max_retries == settings.EMBEDDING_SDK_MAX_RETRIES


# ---------------------------------------------------------------------------
# 3 Total attempts are bounded by the single ceiling
# ---------------------------------------------------------------------------

def test_total_attempts_never_exceed_ceiling():
    """Persistent transient failure: exactly EMBEDDING_MAX_TOTAL_ATTEMPTS calls.

    Before the amplification fix the SDK could also retry per app-layer attempt,
    yielding (retries + 1) * (retries + 1) = 9 calls. With SDK retries disabled
    the total stays at the documented ceiling (3).
    """
    clock = _FakeClock()
    flaky = _AlwaysFailProvider(lambda: TimeoutError("slow"))
    provider = _resilient(flaky, clock, max_attempts=settings.EMBEDDING_MAX_TOTAL_ATTEMPTS)

    with pytest.raises(ProviderCallError):
        provider.embed_texts(["amplified?"])

    assert flaky.calls == settings.EMBEDDING_MAX_TOTAL_ATTEMPTS == 3
    assert flaky.calls < 9  # the pre-fix amplification upper bound
    assert provider.last_metadata["final_status"] == "failed"
    assert provider.last_metadata["attempts"] == flaky.calls


def test_transient_error_recovers_within_ceiling():
    """One transient failure then success: only one retry, no excess attempts."""
    clock = _FakeClock()
    flaky = _FlakyProvider(1, lambda: ConnectionResetError("reset"))
    provider = _resilient(flaky, clock, max_attempts=settings.EMBEDDING_MAX_TOTAL_ATTEMPTS)

    vectors = provider.embed_texts(["recover"])
    assert len(vectors) == 1
    assert flaky.calls == 2
    assert provider.last_metadata["final_status"] == "completed"
    assert provider.last_metadata["attempts"] == 2


def test_no_retry_beyond_ceiling_even_for_429():
    clock = _FakeClock()
    flaky = _AlwaysFailProvider(lambda: _StatusError(429, "slow down"))
    provider = _resilient(flaky, clock, max_attempts=settings.EMBEDDING_MAX_TOTAL_ATTEMPTS)

    with pytest.raises(ProviderCallError):
        provider.embed_texts(["limited"])
    assert flaky.calls == settings.EMBEDDING_MAX_TOTAL_ATTEMPTS == 3


# ---------------------------------------------------------------------------
# 4 Configuration validation
# ---------------------------------------------------------------------------

def test_config_rejects_invalid_sdk_retries():
    with pytest.raises(ValueError):
        Settings(EMBEDDING_SDK_MAX_RETRIES=-1)
    with pytest.raises(ValueError):
        Settings(EMBEDDING_SDK_MAX_RETRIES=11)
    assert Settings(EMBEDDING_SDK_MAX_RETRIES=0).EMBEDDING_SDK_MAX_RETRIES == 0