"""
Phase 1 tests — Worker initialization and demo job.

Verifies:
1. Worker module imports cleanly.
2. demo_job function exists and is callable.
3. demo_job returns the expected structure.
4. Queue names are defined correctly.
5. wait_for_redis raises SystemExit (rather than hanging) when Redis is unavailable.
"""
import os
import sys
import time

import pytest


class TestWorkerModule:
    def test_worker_imports(self):
        """Worker module must be importable without side effects."""
        import importlib

        # Ensure fresh import in case of module caching across test runs
        if "worker" in sys.modules:
            del sys.modules["worker"]

        # Add worker directory to path if needed
        worker_dir = os.path.join(os.path.dirname(__file__), "..", "..", "worker")
        worker_dir = os.path.abspath(worker_dir)
        if worker_dir not in sys.path:
            sys.path.insert(0, worker_dir)

        import worker as worker_module  # noqa: F401

        assert worker_module is not None

    def test_queue_names_defined(self):
        """QUEUE_NAMES must include the three standard priority levels."""
        if "worker" in sys.modules:
            del sys.modules["worker"]

        worker_dir = os.path.join(os.path.dirname(__file__), "..", "..", "worker")
        if os.path.abspath(worker_dir) not in sys.path:
            sys.path.insert(0, os.path.abspath(worker_dir))

        import worker as worker_module

        assert "high" in worker_module.QUEUE_NAMES
        assert "default" in worker_module.QUEUE_NAMES
        assert "low" in worker_module.QUEUE_NAMES

    def test_demo_job_exists(self):
        """demo_job function must be importable."""
        worker_dir = os.path.join(os.path.dirname(__file__), "..", "..", "worker")
        if os.path.abspath(worker_dir) not in sys.path:
            sys.path.insert(0, os.path.abspath(worker_dir))

        import worker as worker_module

        assert callable(worker_module.demo_job)

    def test_demo_job_returns_expected_structure(self):
        """demo_job must return a dict with status, message, worker, timestamp."""
        worker_dir = os.path.join(os.path.dirname(__file__), "..", "..", "worker")
        if os.path.abspath(worker_dir) not in sys.path:
            sys.path.insert(0, os.path.abspath(worker_dir))

        import worker as worker_module

        result = worker_module.demo_job("phase1-test")

        assert isinstance(result, dict)
        assert result["status"] == "completed"
        assert result["message"] == "phase1-test"
        assert "worker" in result
        assert "timestamp" in result
        assert isinstance(result["timestamp"], float)

    def test_demo_job_default_message(self):
        """demo_job must work with no arguments (default message)."""
        worker_dir = os.path.join(os.path.dirname(__file__), "..", "..", "worker")
        if os.path.abspath(worker_dir) not in sys.path:
            sys.path.insert(0, os.path.abspath(worker_dir))

        import worker as worker_module

        result = worker_module.demo_job()
        assert result["status"] == "completed"
        assert result["message"] == "hello"

    def test_wait_for_redis_exits_when_unavailable(self, monkeypatch):
        """
        wait_for_redis must call sys.exit(1) after exhausting retries
        rather than hanging indefinitely.
        """
        worker_dir = os.path.join(os.path.dirname(__file__), "..", "..", "worker")
        if os.path.abspath(worker_dir) not in sys.path:
            sys.path.insert(0, os.path.abspath(worker_dir))

        if "worker" in sys.modules:
            del sys.modules["worker"]
        import worker as worker_module

        # Patch time.sleep so the test doesn't wait
        monkeypatch.setattr(time, "sleep", lambda _: None)

        with pytest.raises(SystemExit) as exc_info:
            # Use a port that is (virtually) guaranteed to refuse connections
            worker_module.wait_for_redis(
                "redis://localhost:19999/99",
                retries=2,
                delay=0.0,
            )

        assert exc_info.value.code == 1
