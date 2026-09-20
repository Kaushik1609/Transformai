"""
Phase 14 tests — Productionization & Deployment Readiness.

These tests verify, without live infrastructure:
  1. Production Settings fail closed (fake providers, unkeyed real providers,
     memory-backed shared stores, disabled/in-memory audit, incomplete S3).
  2. Staging/development remain usable (deterministic offline providers) while
     still rejecting an incomplete S3 configuration.
  3. S3 misconfiguration fails loudly (no silent local fallback).
  4. docker-compose.prod.yml publishes nothing for PostgreSQL/Redis/MinIO/ClamAV,
     runs migrations before backend start, and uses a non-reloading command.
  5. .env.production.example contains only placeholders for secrets.
  6. Deploy artifacts are present (frontend standalone output, frontend/public,
     worker image PYTHONPATH, .dockerignore files).
  7. /ready reports a ClamAV check that fails closed when the scan is required
     and degrades (informational only) when it is not.
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.ingestion.storage import LocalStorage, StorageConfigurationError, build_storage

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.prod.yml"
ENV_TEMPLATE_PATH = REPO_ROOT / ".env.production.example"
WORKER_DOCKERFILE = REPO_ROOT / "worker" / "Dockerfile"
FRONTEND_APP_DIR = REPO_ROOT / "frontend" / "app"
NEXT_CONFIG = REPO_ROOT / "frontend" / "next.config.js"
FRONTEND_PUBLIC = REPO_ROOT / "frontend" / "public" / ".gitkeep"

_PLACEHOLDER_RE = re.compile(r"^<[A-Z_]+>$")
_SECRET_KEYS = {
    "AUTH_SECRET_KEY",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "STORAGE_ACCESS_KEY",
    "STORAGE_SECRET_KEY",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "LLM_API_KEY",
    "EMBEDDING_API_KEY",
    "NEXT_PUBLIC_API_URL",
}


# ---------------------------------------------------------------------------
# Production Settings — fail closed (14D)
# ---------------------------------------------------------------------------

def _prod(**overrides) -> Settings:
    kwargs = dict(
        ENVIRONMENT="production",
        AUTH_SECRET_KEY="a" * 64,
        OTP_PROVIDER="email",
        OTP_STORE_BACKEND="redis",
        ALLOWED_ORIGINS="https://app.transformiq.example",
        DATABASE_URL="postgresql+asyncpg://user:strongpass@db.example.com:5432/transformiq",
        LLM_API_KEY="test-llm-key",
        EMBEDDING_PROVIDER="openai",
        EMBEDDING_API_KEY="test-embedding-key",
        SECURITY_AUDIT_SINK="database",
        AUTH_TOKEN_REVOCATION_STORE="redis",
        RATE_LIMIT_BACKEND="redis",
        STORAGE_BACKEND="s3",
        STORAGE_BUCKET="transformiq-prod-bucket",
        STORAGE_ACCESS_KEY="test-access-key",
        STORAGE_SECRET_KEY="test-secret-key",
        INTEGRITY_PROVIDER="none",
        _env_file=None,
    )
    kwargs.update(overrides)
    return Settings(**kwargs)


class TestProductionSettingsFailClosed:
    def test_hardened_production_config_is_valid(self):
        assert _prod().ENVIRONMENT == "production"

    def test_production_refuses_fake_integrity_provider(self):
        with pytest.raises(ValidationError):
            _prod(INTEGRITY_PROVIDER="fake")

    def test_production_refuses_fake_llm_provider(self):
        with pytest.raises(ValidationError):
            _prod(LLM_PROVIDER="fake")

    def test_production_refuses_fake_embedding_provider(self):
        with pytest.raises(ValidationError):
            _prod(EMBEDDING_PROVIDER="fake")

    def test_production_requires_llm_api_key(self):
        with pytest.raises(ValidationError):
            _prod(LLM_API_KEY="")

    def test_production_requires_embedding_api_key_for_openai(self):
        with pytest.raises(ValidationError):
            _prod(EMBEDDING_API_KEY="")

    def test_production_requires_audit_enabled(self):
        with pytest.raises(ValidationError):
            _prod(SECURITY_AUDIT_ENABLED=False)

    def test_production_requires_database_audit_sink(self):
        with pytest.raises(ValidationError):
            _prod(SECURITY_AUDIT_SINK="memory")

    def test_production_requires_redis_revocation_store(self):
        with pytest.raises(ValidationError):
            _prod(AUTH_TOKEN_REVOCATION_STORE="memory")

    def test_production_requires_redis_rate_limit_backend(self):
        with pytest.raises(ValidationError):
            _prod(RATE_LIMIT_BACKEND="memory")

    def test_production_requires_redis_cache_when_enabled(self):
        with pytest.raises(ValidationError):
            _prod(CACHE_ENABLED=True, CACHE_BACKEND="memory")

    def test_production_refuses_incomplete_s3_config(self):
        with pytest.raises(ValidationError):
            _prod(
                STORAGE_BACKEND="s3",
                STORAGE_ACCESS_KEY="",
                STORAGE_SECRET_KEY="",
            )

    def test_production_accepts_complete_s3_config(self):
        cfg = _prod(
            STORAGE_BACKEND="s3",
            STORAGE_ACCESS_KEY="minio-root",
            STORAGE_SECRET_KEY="minio-secret",
            STORAGE_ENDPOINT="http://minio:9000",
        )
        assert cfg.STORAGE_BACKEND == "s3"


class TestStagingAndDevelopmentPermissive:
    def test_staging_allows_fake_providers(self):
        cfg = _prod(
            ENVIRONMENT="staging",
            LLM_PROVIDER="fake",
            EMBEDDING_PROVIDER="fake",
        )
        assert cfg.ENVIRONMENT == "staging"
        assert cfg.LLM_PROVIDER == "fake"

    def test_staging_refuses_incomplete_s3_config(self):
        with pytest.raises(ValidationError):
            _prod(
                ENVIRONMENT="staging",
                STORAGE_BACKEND="s3",
                STORAGE_ACCESS_KEY="k",
                STORAGE_SECRET_KEY="",
            )

    def test_development_keeps_offline_providers(self):
        cfg = Settings(_env_file=None)
        assert cfg.ENVIRONMENT == "development"
        assert cfg.EMBEDDING_PROVIDER == "fake"
        assert cfg.OTP_PROVIDER == "console"
        assert cfg.AUTH_TOKEN_REVOCATION_STORE == "memory"


class TestStorageSelectionNoFallback:
    def test_s3_misconfiguration_raises_not_falls_back(self, monkeypatch):
        monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
        monkeypatch.setattr(settings, "STORAGE_BUCKET", "transformiq")
        monkeypatch.setattr(settings, "STORAGE_ACCESS_KEY", "")
        monkeypatch.setattr(settings, "STORAGE_SECRET_KEY", "")
        with pytest.raises(StorageConfigurationError):
            build_storage()

    def test_local_backend_still_constructs(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
        monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
        assert isinstance(build_storage(), LocalStorage)


# ---------------------------------------------------------------------------
# docker-compose.prod.yml structure (14B/14I)
# ---------------------------------------------------------------------------

class TestProdComposeStructure:
    @pytest.fixture(scope="class")
    def text(self) -> str:
        assert COMPOSE_PATH.is_file(), "docker-compose.prod.yml must exist"
        return COMPOSE_PATH.read_text(encoding="utf-8")

    def test_data_network_is_internal(self, text):
        assert "internal: true" in text

    def test_only_backend_and_frontend_are_published(self, text):
        assert '"${BACKEND_BIND_PORT:-8000}:8000"' in text
        assert '"${FRONTEND_BIND_PORT:-3000}:3000"' in text

    def test_no_infrastructure_ports_published(self, text):
        for leaked in (
            '"5432:5432"',   # PostgreSQL
            '"6379:6379"',   # Redis
            '"3310:3310"',   # ClamAV
            '"9000:9000"',   # MinIO API
            '"9001:9001"',   # MinIO console
        ):
            assert leaked not in text, f"infrastructure port {leaked} must not be published"

    def test_migrations_run_before_backend(self, text):
        assert '["alembic", "upgrade", "head"]' in text
        assert "service_completed_successfully" in text

    def test_backend_command_has_no_reload(self, text):
        assert '"--reload"' not in text

    def test_frontend_builds_production_target(self, text):
        assert "target: production" in text

    def test_no_container_name(self, text):
        # container_name prevents `--scale worker=N`; the worker is meant to scale.
        assert "container_name:" not in text

    def test_named_volumes_declared(self, text):
        for volume in ("postgres_data", "redis_data", "clamav_data", "minio_data", "storage_data"):
            assert volume in text

    def test_egress_and_edge_networks_declared(self, text):
        assert "egress:" in text
        assert "edge:" in text
        assert "data:" in text


# ---------------------------------------------------------------------------
# .env.production.example (14C)
# ---------------------------------------------------------------------------

class TestEnvTemplate:
    @pytest.fixture(scope="class")
    def entries(self) -> dict[str, str]:
        assert ENV_TEMPLATE_PATH.is_file()
        result: dict[str, str] = {}
        for raw in ENV_TEMPLATE_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and value and key not in result:
                result[key] = value
        return result

    def test_required_keys_present(self, entries):
        required = {
            "ENVIRONMENT",
            "DEV_AUTH_BYPASS",
            "AUTH_SECRET_KEY",
            "ALLOWED_ORIGINS",
            "OTP_PROVIDER",
            "OTP_STORE_BACKEND",
            "SMTP_HOST",
            "SMTP_PASSWORD",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "STORAGE_BACKEND",
            "STORAGE_ACCESS_KEY",
            "STORAGE_SECRET_KEY",
            "MINIO_ROOT_USER",
            "MINIO_ROOT_PASSWORD",
            "LLM_PROVIDER",
            "LLM_API_KEY",
            "EMBEDDING_PROVIDER",
            "EMBEDDING_API_KEY",
            "SECURITY_AUDIT_ENABLED",
            "SECURITY_AUDIT_SINK",
            "AUTH_TOKEN_REVOCATION_STORE",
            "RATE_LIMIT_BACKEND",
            "NEXT_PUBLIC_API_URL",
        }
        assert required <= set(entries)

    def test_mandatory_values(self, entries):
        assert entries["ENVIRONMENT"] == "production"
        assert entries["DEV_AUTH_BYPASS"] == "false"
        assert entries["OTP_PROVIDER"] == "email"
        assert entries["STORAGE_BACKEND"] == "s3"
        assert entries["SECURITY_AUDIT_SINK"] == "database"
        assert entries["LLM_PROVIDER"] == "openai"
        assert entries["EMBEDDING_PROVIDER"] == "openai"

    def test_secret_values_are_placeholders_only(self, entries):
        for key in _SECRET_KEYS:
            value = entries.get(key, "")
            assert value, f"{key} must be present in the template"
            assert _PLACEHOLDER_RE.match(value), (
                f"{key}={value!r} must be a <PLACEHOLDER>, not a real value"
            )

    def test_no_stray_secret_literals(self, entries):
        for key, value in entries.items():
            assert "changeme" not in value.lower(), f"{key} contains 'changeme'"
            assert not re.fullmatch(r"[0-9a-f]{32,}", value), (
                f"{key} looks like a committed credential ({value!r})"
            )
            assert "sk-" not in value.lower(), f"{key} looks like a provider key"


# ---------------------------------------------------------------------------
# Deploy artifacts (14E/14F/14H)
# ---------------------------------------------------------------------------

class TestDeployArtifacts:
    def test_frontend_uses_standalone_output(self):
        assert NEXT_CONFIG.is_file()
        content = NEXT_CONFIG.read_text(encoding="utf-8")
        assert "output:" in content
        assert '"standalone"' in content

    def test_frontend_public_dir_exists_for_copy(self):
        assert FRONTEND_PUBLIC.is_file()

    def test_worker_image_bakes_pythonpath(self):
        assert WORKER_DOCKERFILE.is_file()
        assert "PYTHONPATH=/backend:/app" in WORKER_DOCKERFILE.read_text(encoding="utf-8")

    def test_dockerignore_files_exist(self):
        for path in (
            REPO_ROOT / ".dockerignore",
            REPO_ROOT / "backend" / ".dockerignore",
            REPO_ROOT / "frontend" / ".dockerignore",
        ):
            assert path.is_file(), f"{path} must exist"

    def test_backend_dockerignore_excludes_secrets(self):
        content = (REPO_ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8")
        assert ".env.*" in content

    def test_root_dockerignore_excludes_test_suites(self):
        content = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
        assert "backend/tests" in content

    def test_alembic_env_widens_version_table(self):
        # A fresh alembic_version is VARCHAR(32) by default, which cannot hold
        # revision ids like 0004_phase6_transformation_output_error (40 chars).
        env_py = (REPO_ROOT / "backend" / "alembic" / "env.py").read_text(
            encoding="utf-8"
        )
        assert "_ensure_wide_version_table" in env_py
        assert "VARCHAR(100)" in env_py


# ---------------------------------------------------------------------------
# /ready ClamAV check (14I)
# ---------------------------------------------------------------------------

class _FakePingConn:
    def ping(self):
        return True

    def close(self):
        pass


class _FakePgConn:
    def close(self):
        pass


class TestReadyClamavCheck:
    @pytest.fixture
    def client(self):
        from app.main import app

        with TestClient(app) as c:
            yield c

    def _configure(
        self, monkeypatch, *, enabled, required, reachable, db_redis_ok=True
    ):
        import app.api.v1.health as health
        import psycopg2
        import redis as redis_lib

        monkeypatch.setattr(health.settings, "MALWARE_SCAN_ENABLED", enabled)
        monkeypatch.setattr(health.settings, "MALWARE_SCANNER", "clamav")
        monkeypatch.setattr(health.settings, "MALWARE_SCAN_REQUIRED", required)
        monkeypatch.setattr(health, "_clamav_reachable", lambda: reachable)
        if db_redis_ok:
            monkeypatch.setattr(redis_lib, "from_url", lambda *a, **k: _FakePingConn())
            monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: _FakePgConn())

    def test_disabled_scan_adds_no_clamav_check(self, client, monkeypatch):
        self._configure(
            monkeypatch, enabled=False, required=False, reachable=False
        )
        data = client.get("/ready").json()
        assert "clamav" not in data["checks"]

    def test_required_unreachable_fails_closed(self, client, monkeypatch):
        self._configure(
            monkeypatch, enabled=True, required=True, reachable=False
        )
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["clamav"] == "unavailable"

    def test_required_reachable_reports_ok(self, client, monkeypatch):
        self._configure(
            monkeypatch, enabled=True, required=True, reachable=True
        )
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["checks"]["clamav"] == "ok"

    def test_not_required_unreachable_degrades_informational(self, client, monkeypatch):
        self._configure(
            monkeypatch, enabled=True, required=False, reachable=False
        )
        response = client.get("/ready")
        data = response.json()
        assert response.status_code == 200
        assert data["checks"]["clamav"] == "unavailable"