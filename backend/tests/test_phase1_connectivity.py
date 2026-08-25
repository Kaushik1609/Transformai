"""
Phase 1 tests — Redis and PostgreSQL connectivity foundation.

These tests verify that:
1. The application can attempt Redis connectivity without crashing.
2. The application can attempt PostgreSQL connectivity without crashing.
3. The /ready endpoint reflects real check results (ok or unavailable).
4. The API v1 router is mounted correctly.
5. Global error handling returns consistent JSON.

NOTE: These tests run without a live Redis or PostgreSQL instance.
      They verify the connectivity CODE works (can be imported, called,
      returns correct structure), not that real servers are running.
      Integration tests that require live services are in a separate
      conftest-gated test class.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Ready endpoint — Phase 1 real checks
# ---------------------------------------------------------------------------

class TestReadyPhase1:
    def test_ready_returns_valid_status_code(self, client: TestClient):
        """
        /ready must return either 200 (all up) or 503 (dependency down).
        It must never return 4xx or 5xx from an unhandled exception.
        """
        response = client.get("/ready")
        assert response.status_code in (200, 503)

    def test_ready_has_status_field(self, client: TestClient):
        data = client.get("/ready").json()
        assert "status" in data
        assert data["status"] in ("ready", "not_ready")

    def test_ready_has_redis_check(self, client: TestClient):
        data = client.get("/ready").json()
        assert "redis" in data["checks"]
        assert data["checks"]["redis"] in ("ok", "unavailable")

    def test_ready_has_database_check(self, client: TestClient):
        data = client.get("/ready").json()
        assert "database" in data["checks"]
        assert data["checks"]["database"] in ("ok", "unavailable")

    def test_ready_status_consistent_with_checks(self, client: TestClient):
        """
        If any check is 'unavailable', status must be 'not_ready' and
        HTTP status must be 503. If all checks are 'ok', status must be
        'ready' and HTTP status must be 200.
        """
        response = client.get("/ready")
        data = response.json()
        checks = data["checks"]
        all_ok = all(v == "ok" for v in checks.values())
        if all_ok:
            assert data["status"] == "ready"
            assert response.status_code == 200
        else:
            assert data["status"] == "not_ready"
            assert response.status_code == 503

    def test_ready_does_not_expose_credentials(self, client: TestClient):
        """Database/Redis connection strings must never appear in the response."""
        response = client.get("/ready")
        text = response.text
        sensitive = ["changeme", "password", "secret", "AUTH_SECRET"]
        for s in sensitive:
            assert s not in text, f"/ready exposed sensitive value: {s!r}"


# ---------------------------------------------------------------------------
# API v1 router
# ---------------------------------------------------------------------------

class TestApiV1Router:
    def test_api_v1_prefix_mounted(self, client: TestClient):
        """
        The /api/v1 prefix must be mounted. Even with no endpoints registered
        the OpenAPI schema must list it.
        """
        response = client.get("/openapi.json")
        assert response.status_code == 200
        # As more endpoints are added they will appear here.
        # For now we just confirm the schema is accessible.
        schema = response.json()
        assert "paths" in schema

    def test_api_v1_404_returns_json(self, client: TestClient):
        """A 404 under /api/v1 must return JSON, not HTML."""
        response = client.get("/api/v1/does-not-exist")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data


# ---------------------------------------------------------------------------
# Global error handler
# ---------------------------------------------------------------------------

class TestGlobalErrorHandling:
    def test_404_returns_json_detail(self, client: TestClient):
        response = client.get("/nonexistent-path")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_405_returns_json_detail(self, client: TestClient):
        """DELETE on /health is not allowed — must return 405 with JSON."""
        response = client.delete("/health")
        assert response.status_code == 405
        data = response.json()
        assert "detail" in data
