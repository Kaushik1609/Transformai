"""
Phase 13 — Production Hardening & Operational Security for TransformIQ.

Covers the Phase 13 hardening layers:

    13A  JWT ``jti`` claims + server-side token revocation (logout replay
         protection, bounded memory store with expiry sweep + cap eviction).
    13B  Analyst-tier RBAC on the security-events API.
    13C  Bounded in-memory rate limiter (key-track cap + per-key deque prune).
    13D  Durable database audit sink: persist -> drain -> owner-scoped reads,
         with preserved redacted details and strict project isolation.
    13E  Bounded ingestion budgets: PDF page caps, extraction char caps,
         DOCX char caps, magic-byte type-confusion guards, direct-text caps,
         chunk-count caps.
    13F  Production settings hardening: fail-closed boot validators and
         bounded Phase 13 knobs.
    13G  Stale transformation-job reaper (fails orphaned ``running`` jobs,
         emits ``job_failed`` security events, counts metrics).
    13H  Phase 13 metric families registered.
"""
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

import fitz
import pytest
from docx import Document
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401  (registers every table incl. Phase 13D)
from app.core.audit import (
    clear_security_events,
    drain_pending_audit_events,
    emit_security_event,
    security_events,
)
from app.core.config import Settings, settings
from app.core.metrics import labels_key, metrics, render_metrics
from app.core.ratelimit import MemoryRateLimiter
from app.core.security import create_access_token, decode_access_token
from app.core.token_revocation import (
    MemoryTokenRevocationStore,
    revoke_access_token,
)
from app.db.base import Base
from app.db.models.project import Project
from app.db.models.transformation_job import TransformationJob


def _counter(name: str, labels: dict | None = None) -> int:
    """Read one counter series from the shared MetricsRegistry."""
    family = metrics.snapshot().get("counters", {}).get(name, {})
    return int(family.get(labels_key(labels or {}), 0))


# ---------------------------------------------------------------------------
# Shared SQLite fixtures (async + sync, mirroring existing phase tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def model_metadata():
    return Base.metadata


@pytest.fixture
async def async_db_session(model_metadata) -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(model_metadata.create_all)
    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


@pytest.fixture
def sync_db(model_metadata) -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    model_metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def _isolated_audit_stream():
    clear_security_events()
    yield
    clear_security_events()


class HardeningCtx:
    """Isolated FastAPI app wired to the shared async session."""

    def __init__(self, app, db, store):
        self.app = app
        self.db = db
        self.store = store

    async def client(self) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")

    @staticmethod
    def auth(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def app_ctx(async_db_session, monkeypatch):
    """Real router stack with the JWT path enabled (no DEV_AUTH_BYPASS)."""
    import app.api.deps as deps_module
    from app.api.v1 import router as api_v1_router
    from app.api.v1.health import router as health_router
    from app.auth.otp_delivery import (
        ConsoleOtpProvider,
        get_otp_delivery_provider,
    )
    from app.auth.otp_store import MemoryOtpStore, get_otp_store
    from app.db.models.user import User
    from app.db.session import get_db

    app = FastAPI()
    app.include_router(health_router)
    app.include_router(api_v1_router, prefix="/api/v1")

    store = MemoryTokenRevocationStore()
    app.state.transformiq_token_revocation_store = store

    async def override_get_db():
        yield async_db_session

    async def override_get_otp_store():
        return MemoryOtpStore()

    async def override_get_otp_provider():
        return ConsoleOtpProvider()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_otp_store] = override_get_otp_store
    app.dependency_overrides[get_otp_delivery_provider] = override_get_otp_provider

    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)

    async def fake_get_user_record(user_id):
        return await async_db_session.get(User, user_id)

    monkeypatch.setattr(deps_module, "_get_user_record", fake_get_user_record)

    async def make_user(email: str, role: str = "operator") -> User:
        user = User(id=uuid.uuid4(), email=email, name="Hardening", role=role)
        async_db_session.add(user)
        await async_db_session.flush()
        return user

    async def token_for(user: User) -> str:
        return create_access_token(
            subject=user.id, email=user.email, role=user.role
        )

    ctx = HardeningCtx(app, async_db_session, store)
    ctx.make_user = make_user  # type: ignore[attr-defined]
    ctx.token_for = token_for  # type: ignore[attr-defined]
    yield ctx


# ===========================================================================
# 13A — JWT jti + server-side revocation
# ===========================================================================


class TestJwtJti:
    SUBJECT = "11111111-1111-4111-8111-111111111111"

    def _token(self) -> str:
        return create_access_token(
            subject=self.SUBJECT, email="hard@example.test", role="operator"
        )

    def test_access_tokens_carry_unique_jti(self):
        token = self._token()
        payload = decode_access_token(token)
        assert payload["jti"]
        assert payload["type"] == "access"

        other = self._token()
        assert decode_access_token(other)["jti"] != payload["jti"]

    def test_memory_store_revokes_and_sweeps_expired(self):
        store = MemoryTokenRevocationStore(max_entries=100)
        assert not store.is_revoked("never-revoked")

        assert store.revoke("active-jti") is True
        assert store.is_revoked("active-jti") is True

        store.revoke(
            "already-expired",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        # Lazy sweep happens on access: the expired entry is gone.
        assert store.is_revoked("already-expired") is False

    def test_memory_store_cap_evicts_oldest(self):
        store = MemoryTokenRevocationStore(max_entries=2)
        store.revoke("one")
        store.revoke("two")
        assert store.revoke("three") is True
        assert len(store) == 2
        assert not store.is_revoked("one")
        assert store.is_revoked("two") and store.is_revoked("three")

    def test_revoke_garbage_token_is_false(self):
        assert revoke_access_token("not-a-jwt") is False
        assert revoke_access_token(None) is False


class TestRevocationAtLogout:
    async def test_logout_revokes_token_and_blocks_replay(self, app_ctx):
        user = await app_ctx.make_user("revoke@example.test")
        token = await app_ctx.token_for(user)
        headers = app_ctx.auth(token)
        async with await app_ctx.client() as client:
            me = await client.get("/api/v1/auth/me", headers=headers)
            assert me.status_code == 200

            before = _counter("token_revoked_total", {"result": "revoked"})
            logout = await client.post("/api/v1/auth/logout", headers=headers)
            assert logout.status_code == 200

            assert (
                _counter("token_revoked_total", {"result": "revoked"})
                == before + 1
            )

            replay = await client.get("/api/v1/auth/me", headers=headers)
            assert replay.status_code == 401

            events = [
                e
                for e in security_events()
                if e.get("event_type") == "logout"
            ]
            assert events and events[0].get("reason") == "token_revoked"

    async def test_logout_without_token_is_rejected(self, app_ctx):
        # Logout is an authenticated endpoint (like /me): a request with no
        # credentials gets the generic 401 and never reaches revocation.
        async with await app_ctx.client() as client:
            for headers in ({}, {"Authorization": "Bearer not.a.jwt"}):
                resp = await client.post("/api/v1/auth/logout", headers=headers)
                assert resp.status_code == 401
                assert resp.json()["detail"] == TestGeneric401.GENERIC

    def test_explicit_empty_store_is_never_swapped_for_singleton(self):
        # Regression: MemoryTokenRevocationStore.__len__ makes an empty store
        # falsy, so ``store or get_revocation_store()`` used to silently swap
        # the caller-provided store for the module singleton.
        store = MemoryTokenRevocationStore()
        token = create_access_token(
            subject=uuid.uuid4(), email="regress@example.test", role="operator"
        )
        assert len(store) == 0
        assert revoke_access_token(token, store=store) is True
        assert store.is_revoked(str(decode_access_token(token)["jti"])) is True
        assert len(store) == 1


class TestGeneric401:
    """Every authentication failure must be indistinguishable."""

    GENERIC = "Authentication required. Provide a valid Bearer access token."

    async def test_all_authn_failures_share_identical_401(self, app_ctx):
        user = await app_ctx.make_user("generic@example.test")
        valid = await app_ctx.token_for(user)
        expired = create_access_token(
            subject=user.id,
            email=user.email,
            role=user.role,
            expires_delta=timedelta(minutes=-5),
        )
        revocable = await app_ctx.token_for(user)
        app_ctx.store.revoke(
            decode_access_token(revocable)["jti"]
        )

        cases = {
            "missing": {},
            "invalid": {"Authorization": "Bearer not.a.jwt"},
            "expired": {"Authorization": f"Bearer {expired}"},
            "revoked": {"Authorization": f"Bearer {revocable}"},
        }

        received = {}
        async with await app_ctx.client() as client:
            # Sanity: the valid token genuinely works.
            ok = await client.get(
                "/api/v1/auth/me", headers=app_ctx.auth(valid)
            )
            assert ok.status_code == 200

            for name, headers in cases.items():
                resp = await client.get("/api/v1/auth/me", headers=headers)
                assert resp.status_code == 401, name
                assert (
                    resp.headers.get("www-authenticate", "").startswith(
                        "Bearer"
                    )
                )
                received[name] = resp.json()["detail"]

        assert set(received.values()) == {self.GENERIC}
        for name, detail in received.items():
            assert "expired" not in detail.lower(), name
            assert "revoked" not in detail.lower(), name


# ===========================================================================
# 13B — Analyst-tier RBAC on the security-events API
# ===========================================================================


class TestSecurityEventsRBAC:
    async def test_low_privilege_role_denied(self, app_ctx):
        viewer = await app_ctx.make_user("viewer@example.test", role="viewer")
        token = await app_ctx.token_for(viewer)
        async with await app_ctx.client() as client:
            resp = await client.get(
                "/api/v1/operations/security-events",
                headers=app_ctx.auth(token),
            )
            assert resp.status_code == 403

    async def test_analyst_tier_roles_allowed(self, app_ctx):
        for role in ("operator", "analyst", "admin"):
            user = await app_ctx.make_user(f"{role}@example.test", role=role)
            token = await app_ctx.token_for(user)
            async with await app_ctx.client() as client:
                resp = await client.get(
                    "/api/v1/operations/security-events",
                    headers=app_ctx.auth(token),
                )
                assert resp.status_code == 200, role


# ===========================================================================
# 13C — Bounded in-memory rate limiter
# ===========================================================================


class TestBoundedRateLimiter:
    def test_track_cap_evicts_oldest_tracks(self):
        limiter = MemoryRateLimiter(max_tracked_keys=3)
        for index in range(6):
            limiter.hit("bucket", f"key-{index}", limit=100, window_seconds=3600)
        assert len(limiter._hits) <= 3
        # The oldest tracks are gone; the newest survive.
        assert ("bucket", "key-0") not in limiter._hits
        assert ("bucket", "key-5") in limiter._hits

    def test_per_key_samples_are_bounded(self):
        limiter = MemoryRateLimiter(max_tracked_keys=100)
        limit = 50
        for _ in range(2000):
            limiter.hit("bucket", "same-key", limit=limit, window_seconds=3600)
        samples = limiter._hits[("bucket", "same-key")]
        assert len(samples) <= limit + MemoryRateLimiter._PER_KEY_OVERFLOW

    def test_limit_still_rejects(self):
        limiter = MemoryRateLimiter(max_tracked_keys=100)
        limit = 2
        statuses = [
            limiter.hit("bucket", "key", limit=limit, window_seconds=3600)
            for _ in range(4)
        ]
        assert [s.allowed for s in statuses] == [True, True, False, False]


# ===========================================================================
# 13D — Durable database audit sink
# ===========================================================================


class TestDatabaseAuditSink:
    async def test_persist_drain_and_owner_scoped_reads(
        self, app_ctx, monkeypatch
    ):
        monkeypatch.setattr(settings, "SECURITY_AUDIT_SINK", "database")

        owner = await app_ctx.make_user("owner@example.test")
        other = await app_ctx.make_user("other@example.test")
        project = Project(id=uuid.uuid4(), user_id=owner.id, name="Owned")
        foreign_project = Project(
            id=uuid.uuid4(), user_id=other.id, name="Foreign"
        )
        app_ctx.db.add_all([project, foreign_project])
        await app_ctx.db.flush()

        emit_security_event(
            "job_failed",
            outcome="denied",
            project_id=str(project.id),
            job_id="job-1",
            reason="stale_job_reaped",
            details={"grace_seconds": 1200},
        )
        emit_security_event(
            "authn_denied",
            outcome="denied",
            user_id=str(owner.id),
            reason="revoked_token",
        )
        # A foreign event neither initiated by the owner nor on an owned project.
        emit_security_event(
            "malware_detected",
            outcome="denied",
            project_id=str(foreign_project.id),
            user_id=str(other.id),
            reason="foreign",
        )

        before = _counter("security_events_persisted_total")
        written = await drain_pending_audit_events(app_ctx.db)
        assert written == 3
        assert (
            _counter("security_events_persisted_total") == before + 3
        )
        await app_ctx.db.commit()

        token = await app_ctx.token_for(owner)
        headers = app_ctx.auth(token)
        async with await app_ctx.client() as client:
            body = (
                await client.get(
                    "/api/v1/operations/security-events", headers=headers
                )
            ).json()
            assert body["count"] == 2
            event_types = {e["event_type"] for e in body["data"]}
            assert event_types == {"job_failed", "authn_denied"}
            assert not any(
                e["event_type"] == "malware_detected" for e in body["data"]
            )

            # event_type filter.
            filtered = (
                await client.get(
                    "/api/v1/operations/security-events?event_type=job_failed",
                    headers=headers,
                )
            ).json()
            assert filtered["count"] == 1
            assert filtered["data"][0]["job_id"] == "job-1"
            assert filtered["data"][0]["details"] == {"grace_seconds": 1200}

            # Owned-project filter.
            owned = (
                await client.get(
                    f"/api/v1/operations/security-events?project_id={project.id}",
                    headers=headers,
                )
            ).json()
            assert owned["count"] == 1
            assert owned["data"][0]["project_id"] == str(project.id)

            # A project the caller does not own is 404, never exposed.
            foreign = await client.get(
                (
                    "/api/v1/operations/security-events"
                    f"?project_id={foreign_project.id}"
                ),
                headers=headers,
            )
            assert foreign.status_code == 404

            # Fellow users never see the owner's project events.
            other_token = await app_ctx.token_for(other)
            other_body = (
                await client.get(
                    "/api/v1/operations/security-events",
                    headers=app_ctx.auth(other_token),
                )
            ).json()
            assert not any(
                e["project_id"] == str(project.id) for e in other_body["data"]
            )

    async def test_memory_sink_still_serves_memory_stream(self, app_ctx):
        # Default SECURITY_AUDIT_SINK is "memory": the endpoint reads the
        # in-process stream, and drain is a no-op.
        user = await app_ctx.make_user("mem@example.test")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Mem")
        app_ctx.db.add(project)
        await app_ctx.db.flush()

        emit_security_event(
            "malware_scan_completed",
            project_id=str(project.id),
            reason="clean",
            details={"scanner": "fake"},
        )
        drained = await drain_pending_audit_events(app_ctx.db)
        assert drained == 0

        token = await app_ctx.token_for(user)
        body = None
        async with await app_ctx.client() as client:
            resp = await client.get(
                "/api/v1/operations/security-events",
                headers=app_ctx.auth(token),
            )
            assert resp.status_code == 200
            body = resp.json()
        matches = [
            e for e in body["data"] if e["event_type"] == "malware_scan_completed"
        ]
        assert matches and matches[0]["details"] == {"scanner": "fake"}


# ===========================================================================
# 13E — Bounded ingestion budgets
# ===========================================================================


def make_pdf(*pages: str) -> bytes:
    document = fitz.open()
    for text in pages:
        page = document.new_page()
        page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def make_docx(*paragraphs: str) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_source(db: Session, tmp_path, *, content: bytes) -> "object":
    """Minimal stored source for worker-path tests (mirrors phase 3D)."""
    from app.db.models.source import Source
    from app.db.models.user import User
    from app.ingestion.storage import LocalStorage

    user = User(
        id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        email="worker@example.test",
        name="Worker",
        role="operator",
    )
    project = Project(
        id=uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        user_id=user.id,
        name="Worker project",
    )
    source = Source(
        id=uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
        project_id=project.id,
        source_type="txt",
        original_filename="source.txt",
        mime_type="text/plain",
        file_size=len(content),
        language="en",
        status="processing",
    )
    db.add_all([user, project, source])
    db.flush()
    key = LocalStorage.source_key(project.id, source.id, source.original_filename)
    LocalStorage(tmp_path).save(key, content)
    source.storage_key = key
    db.commit()
    db.refresh(source)
    return source


class TestMagicByteValidation:
    DOCX_MIME = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    @staticmethod
    def _rules():
        from app.ingestion.validation import (
            SourceValidationError,
            validate_source,
        )

        return SourceValidationError, validate_source

    def test_pdf_uploaded_as_docx_rejected(self):
        error, validate = self._rules()
        with pytest.raises(error, match="DOCX content does not match"):
            validate(
                source_type="docx",
                content=b"%PDF-1.7 fake pdf bytes",
                filename="report.docx",
                mime_type=self.DOCX_MIME,
                max_size_bytes=10**6,
            )

    def test_zip_uploaded_as_pdf_rejected(self):
        error, validate = self._rules()
        with pytest.raises(error, match="PDF content does not match"):
            validate(
                source_type="pdf",
                content=b"PK\x03\x04fake-zip-container",
                filename="report.pdf",
                mime_type="application/pdf",
                max_size_bytes=10**6,
            )

    def test_pdf_masquerading_as_text_rejected(self):
        error, validate = self._rules()
        with pytest.raises(error, match="binary document"):
            validate(
                source_type="txt",
                content=b"%PDF-1.7 sneaky pdf",
                filename="notes.txt",
                mime_type="text/plain",
                max_size_bytes=10**6,
            )

    def test_corrupt_bytes_defer_to_extraction_contract(self):
        # Arbitrary corrupt bytes match no known signature: validation passes
        # and the standard extraction error is preserved (phase 3C contract).
        _, validate = self._rules()
        result = validate(
            source_type="pdf",
            content=b"not a PDF",
            filename="broken.pdf",
            mime_type="application/pdf",
            max_size_bytes=10**6,
        )
        assert result.source_type == "pdf"


class TestDocumentBudgetCaps:
    def test_pdf_page_cap_enforced(self, monkeypatch):
        from app.ingestion.documents import (
            DocumentExtractionError,
            extract_pdf,
        )

        monkeypatch.setattr(settings, "MAX_PDF_PAGES", 2)
        with pytest.raises(DocumentExtractionError, match="page count"):
            extract_pdf(make_pdf("one", "two", "three"))

    def test_pdf_char_cap_enforced(self, monkeypatch):
        from app.ingestion.documents import (
            DocumentExtractionError,
            extract_pdf,
        )

        monkeypatch.setattr(settings, "MAX_EXTRACTED_CHARS", 10)
        with pytest.raises(DocumentExtractionError, match="extraction limit"):
            extract_pdf(make_pdf("x" * 500))

    def test_docx_char_cap_enforced(self, monkeypatch):
        from app.ingestion.documents import (
            DocumentExtractionError,
            extract_docx,
        )

        monkeypatch.setattr(settings, "MAX_EXTRACTED_CHARS", 10)
        with pytest.raises(DocumentExtractionError, match="extraction limit"):
            extract_docx(make_docx("y" * 500))

    def test_normal_documents_below_caps_extract(self, monkeypatch):
        from app.ingestion.documents import extract_docx, extract_pdf

        monkeypatch.setattr(settings, "MAX_PDF_PAGES", 500)
        monkeypatch.setattr(settings, "MAX_EXTRACTED_CHARS", 2_000_000)
        assert "hello" in extract_pdf(make_pdf("hello world"))
        assert "hello" in extract_docx(make_docx("hello world"))


class TestTextInputBudgetCaps:
    async def test_direct_text_cap_enforced(self, async_db_session, monkeypatch):
        from app.services.source_service import ingest_text_source

        monkeypatch.setattr(settings, "INPUT_MAX_TEXT_LENGTH", 100)
        with pytest.raises(ValueError, match="input limit"):
            await ingest_text_source(
                async_db_session,
                project_id=uuid.uuid4(),
                content=("z" * 500).encode("utf-8"),
                source_type="text",
                filename=None,
                mime_type="text/plain",
                language="en",
                metadata=None,
            )

    def test_chunk_cap_enforced(self, sync_db, tmp_path, monkeypatch):
        from app.ingestion.worker_processing import process_source_with_session

        monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
        monkeypatch.setattr(settings, "MAX_SOURCE_CHUNKS", 1)
        source = make_source(
            sync_db, tmp_path, content=b"shared word " * 4000
        )
        with pytest.raises(ValueError, match="chunk count"):
            process_source_with_session(sync_db, source.id)


# ===========================================================================
# 13F — Production settings hardening
# ===========================================================================


def _prod(**overrides) -> Settings:
    # Encodes a fully valid production configuration so hardening assertions stay green.
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


class TestProductionHardening:
    def test_refuses_dev_secret_in_production(self):
        with pytest.raises(ValidationError):
            _prod(AUTH_SECRET_KEY="dev-secret-replace-before-production")

    def test_refuses_console_otp_provider_in_production(self):
        with pytest.raises(ValidationError):
            _prod(OTP_PROVIDER="console")

    def test_refuses_memory_otp_store_in_production(self):
        with pytest.raises(ValidationError):
            _prod(OTP_STORE_BACKEND="memory")

    def test_refuses_wildcard_cors_origin_in_production(self):
        with pytest.raises(ValidationError):
            _prod(ALLOWED_ORIGINS="https://ok.example,*")

    def test_refuses_fake_integrity_provider_in_production(self):
        with pytest.raises(ValidationError):
            _prod(INTEGRITY_PROVIDER="fake")

    def test_refuses_real_integrity_without_ledger_url_in_production(self):
        with pytest.raises(ValidationError):
            _prod(INTEGRITY_PROVIDER="real", INTEGRITY_LEDGER_URL="")

    def test_refuses_local_storage_in_production(self):
        with pytest.raises(ValidationError):
            _prod(STORAGE_BACKEND="local")

    def test_refuses_dev_database_password_in_production(self):
        with pytest.raises(ValidationError):
            _prod(DATABASE_URL="postgresql+asyncpg://transformiq:changeme@localhost:5432/transformiq")

    def test_refuses_fake_fallback_provider_in_production(self):
        with pytest.raises(ValidationError):
            _prod(LLM_FALLBACK_PROVIDER="fake")

    def test_hardened_production_config_is_valid(self):
        hardened = _prod()
        assert hardened.ENVIRONMENT == "production"
        assert hardened.RATE_LIMIT_MEMORY_MAX_TRACKED_KEYS == 100_000
        assert hardened.STORAGE_BACKEND == "s3"
        assert hardened.INTEGRITY_PROVIDER == "none"

    def test_staging_is_equally_hardened(self):
        with pytest.raises(ValidationError):
            _prod(ENVIRONMENT="staging", OTP_PROVIDER="console")

    def test_bounded_knobs_rejected(self):
        with pytest.raises(ValidationError):
            Settings(MAX_PDF_PAGES=0, _env_file=None)
        with pytest.raises(ValidationError):
            Settings(MAX_SOURCE_CHUNKS=0, _env_file=None)
        with pytest.raises(ValidationError):
            Settings(RATE_LIMIT_MEMORY_MAX_TRACKED_KEYS=10, _env_file=None)

    def test_grace_must_exceed_worker_timeout(self):
        with pytest.raises(ValidationError):
            Settings(
                STALE_TRANSFORMATION_JOB_GRACE_SECONDS=settings.WORKER_JOB_TIMEOUT,
                _env_file=None,
            )


# ===========================================================================
# 13G — Stale transformation-job reaper
# ===========================================================================


async def _make_running_job(
    db: AsyncSession, *, started_at: datetime | None
) -> TransformationJob:
    job = TransformationJob(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        configuration_id=uuid.uuid4(),
        requested_outputs={"output_types": ["summary"]},
        status="running",
        started_at=started_at,
    )
    db.add(job)
    await db.flush()
    return job


class TestStaleJobReaper:
    async def test_reaps_orphaned_running_job_only(
        self, async_db_session, monkeypatch
    ):
        from app.transformation.reaper import fail_stale_transformation_jobs

        grace = settings.STALE_TRANSFORMATION_JOB_GRACE_SECONDS
        stale = await _make_running_job(
            async_db_session,
            started_at=datetime.now(timezone.utc)
            - timedelta(seconds=grace + 60),
        )
        fresh = await _make_running_job(
            async_db_session, started_at=datetime.now(timezone.utc)
        )
        await async_db_session.commit()

        before = _counter("stale_transformation_jobs_failed_total")
        failed = await fail_stale_transformation_jobs(async_db_session)
        await async_db_session.commit()
        assert failed == 1
        assert (
            _counter("stale_transformation_jobs_failed_total") == before + 1
        )

        async_db_session.expunge_all()
        failed_book = await async_db_session.get(
            TransformationJob, stale.id
        )
        assert failed_book.status == "failed"
        assert "reaper" in (failed_book.error_message or "")
        assert failed_book.completed_at is not None

        untouched = await async_db_session.get(TransformationJob, fresh.id)
        assert untouched.status == "running"

        reaped_events = [
            e
            for e in security_events()
            if e.get("event_type") == "job_failed"
            and e.get("reason") == "stale_job_reaped"
            and e.get("job_id") == str(stale.id)
        ]
        assert reaped_events
        assert reaped_events[0]["grace_seconds"] == grace

    async def test_no_stale_jobs_reaps_nothing(self, async_db_session):
        from app.transformation.reaper import fail_stale_transformation_jobs

        fresh = await _make_running_job(
            async_db_session, started_at=datetime.now(timezone.utc)
        )
        await async_db_session.commit()
        failed = await fail_stale_transformation_jobs(async_db_session)
        assert failed == 0
        await async_db_session.commit()
        assert (
            await async_db_session.get(TransformationJob, fresh.id)
        ).status == "running"


# ===========================================================================
# 13H — Metric families
# ===========================================================================


class TestPhase13Metrics:
    def test_families_registered(self):
        rendered = render_metrics()
        for family in (
            "security_events_persisted_total",
            "security_events_drop_total",
            "token_revoked_total",
            "stale_transformation_jobs_failed_total",
        ):
            assert family in rendered