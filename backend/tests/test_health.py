"""
Phase 0 smoke tests — Backend health endpoints.

These tests verify:
1. The FastAPI application loads correctly.
2. /health returns 200 with expected fields.
3. /ready returns 200 with dependency checks.
4. No secrets are exposed in responses.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    """Create a test client for the FastAPI app."""
    from app.main import app

    with TestClient(app) as c:
        yield c


class TestHealth:
    def test_health_returns_200(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self, client: TestClient):
        data = client.get("/health").json()
        assert data["status"] == "ok"

    def test_health_contains_service_name(self, client: TestClient):
        data = client.get("/health").json()
        assert data["service"] == "transformiq-backend"

    def test_health_contains_version(self, client: TestClient):
        data = client.get("/health").json()
        assert "version" in data

    def test_health_contains_environment(self, client: TestClient):
        data = client.get("/health").json()
        assert "environment" in data

    def test_health_contains_uptime(self, client: TestClient):
        data = client.get("/health").json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0

    def test_health_does_not_expose_secrets(self, client: TestClient):
        """Ensure no sensitive fields are returned."""
        data = client.get("/health").json()
        sensitive_keys = {"api_key", "secret", "password", "token", "auth"}
        response_keys_lower = {k.lower() for k in data}
        assert not sensitive_keys.intersection(response_keys_lower), (
            f"Health endpoint exposed sensitive keys: "
            f"{sensitive_keys.intersection(response_keys_lower)}"
        )


class TestReady:
    def test_ready_returns_200_or_503(self, client: TestClient):
        """
        Phase 1: /ready performs real connectivity checks.
        In CI/test environments Redis and PostgreSQL may not be running,
        so both 200 (all connected) and 503 (deps unavailable) are valid.
        The important thing is that it never crashes (4xx/5xx from an exception).
        """
        response = client.get("/ready")
        assert response.status_code in (200, 503)

    def test_ready_returns_status_field(self, client: TestClient):
        data = client.get("/ready").json()
        assert "status" in data
        assert data["status"] in ("ready", "not_ready")

    def test_ready_returns_checks_field(self, client: TestClient):
        data = client.get("/ready").json()
        assert "checks" in data
        assert isinstance(data["checks"], dict)

    def test_ready_checks_contain_database(self, client: TestClient):
        data = client.get("/ready").json()
        assert "database" in data["checks"]

    def test_ready_checks_contain_redis(self, client: TestClient):
        data = client.get("/ready").json()
        assert "redis" in data["checks"]

    def test_ready_does_not_expose_secrets(self, client: TestClient):
        data = client.get("/ready").json()
        text = str(data)
        sensitive = ["api_key", "password", "secret", "AUTH_SECRET"]
        for s in sensitive:
            assert s not in text, f"Ready endpoint exposed sensitive value: {s}"


class TestAPIStructure:
    def test_openapi_schema_accessible(self, client: TestClient):
        response = client.get("/openapi.json")
        assert response.status_code == 200

    def test_docs_accessible(self, client: TestClient):
        response = client.get("/docs")
        assert response.status_code == 200
