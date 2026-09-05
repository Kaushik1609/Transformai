"""Phase 11I-2 — Worker job-timeout enforcement (single source + DB write).

Verifies:

  1.  WORKER_JOB_TIMEOUT has ONE definition (config.py, default 605) and the
      worker module sources it from app config — no other default exists.
  2.  Every RQ ``job_timeout`` passed at enqueue time (worker, transformation,
      ingestion) is sourced from ``settings.WORKER_JOB_TIMEOUT`` — never a bare
      literal.
  3.  A transformation job that exceeds the worker timeout is written to the DB
      as ``failed`` with a clear timeout reason (never left stuck in
      ``running``/``queued``). RQ raises ``rq.timeouts.JobTimeoutException`` on
      timeout and the registered ``on_failure`` handler performs the DB write.
  4.  Non-timeout job failures still write a ``failed`` status with the generic
      error.
  5.  Terminal ``completed`` records are never clobbered by a failure handler.

All tests are deterministic and offline (no Redis, no real worker process).
"""

from __future__ import annotations

import ast
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.db.models  # noqa: F401
from app.core.config import get_settings, settings
from app.db.base import Base
from app.db.models.transformation_job import TransformationJob

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_DIR = REPO_ROOT / "worker"


def _import_worker(monkeypatch=None):
    """Import the repo worker module (test_phase1 pattern: path + fresh import)."""
    if "worker" in sys.modules:
        del sys.modules["worker"]
    if os.path.abspath(str(WORKER_DIR)) not in sys.path:
        sys.path.insert(0, os.path.abspath(str(WORKER_DIR)))
    import worker as worker_module  # noqa: PLC0415

    return worker_module


def _enqueue_job_timeout_sites() -> list[tuple[str, str]]:
    """Return (source file, expression) for every RQ ``job_timeout=...`` kwarg."""
    files = [
        WORKER_DIR / "worker.py",
        REPO_ROOT / "backend" / "app" / "transformation" / "queue.py",
        REPO_ROOT / "backend" / "app" / "ingestion" / "queue.py",
    ]
    sites: list[tuple[str, str]] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "enqueue"
            ):
                for keyword in node.keywords:
                    if keyword.arg == "job_timeout":
                        sites.append((path.name, ast.unparse(keyword.value)))
    return sites


def _config_worker_timeout_definition() -> int | None:
    """Return the single ``WORKER_JOB_TIMEOUT`` default defined in config.py."""
    config_path = REPO_ROOT / "backend" / "app" / "core" / "config.py"
    tree = ast.parse(config_path.read_text(encoding="utf-8"))
    defaults = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == "WORKER_JOB_TIMEOUT":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
                    defaults.append(node.value.value)
                else:
                    defaults.append(None)
    if len(defaults) == 1 and defaults[0] is not None:
        return defaults[0]
    return None


class _FakeRqJob:
    def __init__(self, job_id: str) -> None:
        self.args = (job_id,)


@pytest.fixture
def _sqlite_url(tmp_path) -> str:
    """File-backed sqlite URL shared with the handler's own engine."""
    return "sqlite:///" + (tmp_path / "timeout.db").as_posix()


def _seed_job(url: str, *, status: str) -> uuid.UUID:
    engine = create_engine(url, connect_args={"check_same_thread": False})
    try:
        Base.metadata.create_all(engine)
        job_id = uuid.uuid4()
        with Session(engine) as session:
            job = TransformationJob(
                id=job_id,
                project_id=uuid.uuid4(),
                source_id=uuid.uuid4(),
                configuration_id=uuid.uuid4(),
                requested_outputs={"output_types": ["summary"]},
                status=status,
            )
            session.add(job)
            session.commit()
        return job_id
    finally:
        engine.dispose()


def _fetch_job(url: str, job_id: uuid.UUID) -> TransformationJob:
    engine = create_engine(url, connect_args={"check_same_thread": False})
    try:
        with Session(engine) as session:
            return session.get(TransformationJob, job_id)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 1 Single source of WORKER_JOB_TIMEOUT
# ---------------------------------------------------------------------------

def test_worker_timeout_single_source_defined_once():
    from rq.timeouts import JobTimeoutException  # noqa: F401

    worker_module = _import_worker()

    # Config is the ONE definition; worker reads it, and it is 605 (unchanged).
    assert _config_worker_timeout_definition() == 605
    assert get_settings().WORKER_JOB_TIMEOUT == 605
    assert worker_module.WORKER_JOB_TIMEOUT == settings.WORKER_JOB_TIMEOUT == 605

    # Every enqueue-site timeout must come from settings, never a bare literal.
    sites = _enqueue_job_timeout_sites()
    assert sites, "expected at least one RQ enqueue job_timeout site"
    for source_name, expression in sites:
        assert (
            "settings.WORKER_JOB_TIMEOUT" in expression
        ), f"{source_name}: job_timeout must be settings.WORKER_JOB_TIMEOUT, got {expression!r}"
        assert expression != "300", f"{source_name}: bare literal timeout still present"

    # None of the queue/worker files may redefine the value as a raw literal.
    for source_name, expression in sites:
        assert not expression.isdigit()


def test_timeout_failure_reason_detection(monkeypatch):
    from rq.timeouts import JobTimeoutException

    worker_module = _import_worker()
    assert worker_module._is_timeout_failure(JobTimeoutException("too slow")) is True
    assert worker_module._is_timeout_failure(RuntimeError("boom")) is False
    assert worker_module._is_timeout_failure(TimeoutError("slow")) is False


# ---------------------------------------------------------------------------
# 2 Timeout -> DB status write (not a stuck running state)
# ---------------------------------------------------------------------------

def test_timeout_failure_writes_failed_with_timeout_reason(monkeypatch, _sqlite_url):
    from rq.timeouts import JobTimeoutException

    worker_module = _import_worker()
    timeout_error = JobTimeoutException("Task exceeded maximum timeout value (605 seconds)")
    job_id = _seed_job(_sqlite_url, status="running")
    monkeypatch.setattr(settings, "DATABASE_SYNC_URL", _sqlite_url)

    worker_module.transformation_failure_handler(
        _FakeRqJob(str(job_id)), None, type(timeout_error), timeout_error, None
    )

    record = _fetch_job(_sqlite_url, job_id)
    assert record.status == "failed"
    assert "timed out after 605 seconds" in record.error_message
    assert record.completed_at is not None


def test_generic_failure_writes_failed_with_reason(monkeypatch, _sqlite_url):
    worker_module = _import_worker()
    error = RuntimeError("boom")
    job_id = _seed_job(_sqlite_url, status="running")
    monkeypatch.setattr(settings, "DATABASE_SYNC_URL", _sqlite_url)

    worker_module.transformation_failure_handler(
        _FakeRqJob(str(job_id)), None, type(error), error, None
    )

    record = _fetch_job(_sqlite_url, job_id)
    assert record.status == "failed"
    assert record.error_message.startswith("Worker job failed:")
    assert "boom" in record.error_message


def test_queue_state_never_stuck_after_timeout(monkeypatch, _sqlite_url):
    """A queued (never started) transformation job must reach a terminal DB state."""
    from rq.timeouts import JobTimeoutException

    worker_module = _import_worker()
    timeout_error = JobTimeoutException("Task exceeded maximum timeout value (605 seconds)")
    job_id = _seed_job(_sqlite_url, status="queued")
    monkeypatch.setattr(settings, "DATABASE_SYNC_URL", _sqlite_url)

    worker_module.transformation_failure_handler(
        _FakeRqJob(str(job_id)), None, type(timeout_error), timeout_error, None
    )

    record = _fetch_job(_sqlite_url, job_id)
    assert record.status == "failed"
    assert "timed out after 605 seconds" in record.error_message


def test_failure_handler_never_clobbers_completed(monkeypatch, _sqlite_url):
    worker_module = _import_worker()
    error = RuntimeError("late failure")
    job_id = _seed_job(_sqlite_url, status="completed")
    monkeypatch.setattr(settings, "DATABASE_SYNC_URL", _sqlite_url)

    worker_module.transformation_failure_handler(
        _FakeRqJob(str(job_id)), None, type(error), error, None
    )

    record = _fetch_job(_sqlite_url, job_id)
    assert record.status == "completed"