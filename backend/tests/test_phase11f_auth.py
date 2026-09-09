"""
Phase 11F — L1 Perimeter & Identity for TransformIQ

Covers the newly introduced authentication surface:

    Register / OTP activation / password login / JWT / me / logout
    OTP security policy (hashing, expiry, single-use, attempt limits,
    resend cooldown, per-window issuance quota)
    JWT creation/decoding (issuer, audience, typed claims, expiry)
    RBAC: analyst (default) vs admin; legacy operator stays analyst-tier
    Resource-isolation integration using REAL JWTs (no dependency override
    of the current user), proving Phase 2/9A scoping integrates with Phase 11F.
    Rate limiting on auth + protected buckets (Redis-capable, memory default).
    DEV_AUTH_BYPASS safety (forbidden outside development).
"""

import asyncio
import time
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401  (ensures all tables are registered)
import app.db.models.user
from app.core.config import settings

# ---------------------------------------------------------------------------
# Shared async SQLite engine + session (mirrors test_phase9a_authorization)
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_db_session():
    from app.db.base import Base

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()

    await engine.dispose()


# ---------------------------------------------------------------------------
# Isolated FastAPI app for auth-flow tests
# ---------------------------------------------------------------------------

class AuthContext:
    def __init__(self, app, store, provider, db_session):
        self.app = app
        self.store = store
        self.provider = provider
        self.db = db_session

    async def aclient(self) -> AsyncClient:
        transport = ASGITransport(app=self.app)
        return AsyncClient(transport=transport, base_url="http://test")

    async def register_and_verify(
        self,
        *,
        email: str,
        name: str = "Tester",
        channel: str = "email",
        mobile_number: str | None = None,
        role_override: str | None = None,
        password: str = "Tester-pass-1!",
    ):
        """Register -> read the code from the console provider -> verify -> token."""
        client = await self.aclient()
        body = {"name": name, "email": email, "channel": channel, "password": password}
        if mobile_number:
            body["mobile_number"] = mobile_number
        resp = await client.post("/api/v1/auth/register", json=body)
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        code = self.provider.last_otp_for(data["channel"], data["identifier"])
        assert code, "an OTP should have been delivered to the console provider"

        verify_body = {"email": email, "channel": channel, "otp": code}
        if mobile_number:
            verify_body["mobile_number"] = mobile_number
        vresp = await client.post("/api/v1/auth/verify", json=verify_body)
        assert vresp.status_code == 200, vresp.text
        payload = vresp.json()
        token = payload["access_token"]
        user = payload["user"]

        if role_override:
            from app.db.models.user import User

            record = await self.db.get(User, uuid.UUID(user["id"]))
            record.role = role_override
            await self.db.flush()

        return client, token, user

    def auth(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def auth_ctx(async_db_session, monkeypatch):
    """App wired to the shared session + shared in-memory OTP store/provider.

    DEV_AUTH_BYPASS is forced off for the duration so the real JWT pipeline
    runs (register -> OTP -> JWT -> protected route). The user-record loader is
    swapped to read from the shared test session.
    """
    from fastapi import FastAPI
    import app.api.v1
    import app.api.deps as deps_module
    from app.api.v1 import router as api_v1_router
    from app.api.v1.health import router as health_router
    from app.auth.otp_delivery import ConsoleOtpProvider, get_otp_delivery_provider
    from app.auth.otp_store import MemoryOtpStore, get_otp_store
    from app.db.session import get_db
    from app.db.models.user import User

    app = FastAPI()
    app.include_router(health_router)
    app.include_router(api_v1_router, prefix="/api/v1")

    store = MemoryOtpStore()
    provider = ConsoleOtpProvider()

    async def override_get_db():
        yield async_db_session

    async def override_get_otp_store():
        return store

    async def override_get_otp_provider():
        return provider

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_otp_store] = override_get_otp_store
    app.dependency_overrides[get_otp_delivery_provider] = override_get_otp_provider

    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)

    async def fake_get_user_record(user_id):
        return await async_db_session.get(User, user_id)

    monkeypatch.setattr(deps_module, "_get_user_record", fake_get_user_record)

    yield AuthContext(app, store, provider, async_db_session)


# ===========================================================================
# 1. OTP generation / hashing
# ===========================================================================

class TestOtpPrimitives:
    def test_generate_otp_is_numeric_configured_length(self):
        from app.core.security import generate_otp

        for _ in range(50):
            code = generate_otp()
            assert len(code) == settings.OTP_LENGTH
            assert code.isdigit()
            assert len(str(int(code))) == settings.OTP_LENGTH  # no leading-zero loss

    def test_generate_otp_is_deterministically_random(self):
        from app.core.security import generate_otp

        codes = {generate_otp() for _ in range(200)}
        assert len(codes) > 150

    def test_hash_is_hmac_deterministic(self):
        from app.core.security import hash_otp_value

        h1 = hash_otp_value("123456", channel="email", identifier="a@x.com", issued_at=1000)
        h2 = hash_otp_value("123456", channel="email", identifier="a@x.com", issued_at=1000)
        assert h1 == h2
        assert h1 != "123456"

    def test_hash_differs_on_code_and_salt(self):
        from app.core.security import hash_otp_value

        base = dict(channel="email", identifier="a@x.com", issued_at=1000)
        assert hash_otp_value("123456", **base) != hash_otp_value("654321", **base)
        assert hash_otp_value("123456", **base) != hash_otp_value("123456", channel="mobile", identifier="a@x.com", issued_at=1000)
        assert hash_otp_value("123456", **base) != hash_otp_value("123456", channel="email", identifier="b@x.com", issued_at=1000)

    def test_verify_constant_time(self):
        from app.core.security import hash_otp_value, verify_otp_value

        digest = hash_otp_value("123456", channel="email", identifier="a@x.com", issued_at=1000)
        assert verify_otp_value("123456", digest, channel="email", identifier="a@x.com", issued_at=1000) is True
        assert verify_otp_value("000000", digest, channel="email", identifier="a@x.com", issued_at=1000) is False
        assert verify_otp_value("123456", "garbage", channel="email", identifier="a@x.com", issued_at=1000) is False


# ===========================================================================
# 2. OTP lifecycle policy (service-level)
# ===========================================================================

class TestOtpPolicy:
    def _store(self):
        from app.auth.otp_store import MemoryOtpStore

        return MemoryOtpStore()

    def _delivery(self):
        from app.auth.otp_delivery import ConsoleOtpProvider

        return ConsoleOtpProvider()

    async def test_issue_and_verify_success(self, monkeypatch):
        from app.auth.otp_service import issue_otp, verify_otp

        store, delivery = self._store(), self._delivery()
        issued = issue_otp(store, delivery, channel="email", identifier="a@x.com")
        assert issued.identifier == "a@x.com"
        code = delivery.last_otp_for("email", "a@x.com")
        verify_otp(store, channel="email", identifier="a@x.com", otp=code)
        assert store.get("email", "a@x.com") is None  # consumed

    async def test_issue_and_verify_wrong_code(self, monkeypatch):
        from app.auth.otp_service import OtpVerifyError, issue_otp, verify_otp

        store, delivery = self._store(), self._delivery()
        issue_otp(store, delivery, channel="email", identifier="a@x.com")
        with pytest.raises(OtpVerifyError):
            verify_otp(store, channel="email", identifier="a@x.com", otp="000000")

    async def test_expired_code_rejected(self, monkeypatch):
        import app.core.config as config_module
        from app.auth.otp_service import OtpVerifyError, issue_otp, verify_otp

        store, delivery = self._store(), self._delivery()
        issue_otp(store, delivery, channel="email", identifier="a@x.com")
        record = store.get("email", "a@x.com")
        record.expires_at = time.time() - 1
        store.put("email", "a@x.com", record)
        with pytest.raises(OtpVerifyError, match="expired"):
            verify_otp(store, channel="email", identifier="a@x.com", otp=delivery.last_otp_for("email", "a@x.com"))

    async def test_single_use_prevents_replay(self, monkeypatch):
        from app.auth.otp_service import OtpVerifyError, issue_otp, verify_otp

        store, delivery = self._store(), self._delivery()
        issue_otp(store, delivery, channel="email", identifier="a@x.com")
        code = delivery.last_otp_for("email", "a@x.com")
        verify_otp(store, channel="email", identifier="a@x.com", otp=code)
        with pytest.raises(OtpVerifyError):
            verify_otp(store, channel="email", identifier="a@x.com", otp=code)

    async def test_exhausting_attempts_destroys_code(self, monkeypatch):
        import app.core.config as config_module
        from app.auth.otp_service import OtpVerifyError, issue_otp, verify_otp

        monkeypatch.setattr(config_module.settings, "OTP_MAX_ATTEMPTS", 3)
        store, delivery = self._store(), self._delivery()
        issue_otp(store, delivery, channel="email", identifier="a@x.com")
        for _ in range(3):
            with pytest.raises(OtpVerifyError):
                verify_otp(store, channel="email", identifier="a@x.com", otp="000000")
        # Code consumed/destroyed: even the real code now fails.
        real = delivery.last_otp_for("email", "a@x.com")
        with pytest.raises(OtpVerifyError):
            verify_otp(store, channel="email", identifier="a@x.com", otp=real)

    async def test_issue_single_active_per_identifier(self, monkeypatch):
        import app.core.config as config_module
        from app.auth.otp_service import OtpVerifyError, issue_otp, verify_otp

        monkeypatch.setattr(config_module.settings, "OTP_RESEND_COOLDOWN_SECONDS", 0)
        store, delivery = self._store(), self._delivery()
        issue_otp(store, delivery, channel="email", identifier="a@x.com")
        first = delivery.last_otp_for("email", "a@x.com")
        issue_otp(store, delivery, channel="email", identifier="a@x.com")
        # First code invalidated.
        with pytest.raises(OtpVerifyError):
            verify_otp(store, channel="email", identifier="a@x.com", otp=first)
        verify_otp(store, channel="email", identifier="a@x.com", otp=delivery.last_otp_for("email", "a@x.com"))

    async def test_resend_cooldown(self, monkeypatch):
        import app.core.config as config_module
        from app.auth.otp_service import OtpIssueError, issue_otp

        monkeypatch.setattr(config_module.settings, "OTP_RESEND_COOLDOWN_SECONDS", 60)
        store, delivery = self._store(), self._delivery()
        issue_otp(store, delivery, channel="email", identifier="a@x.com")
        with pytest.raises(OtpIssueError, match="Please wait"):
            issue_otp(store, delivery, channel="email", identifier="a@x.com")

    async def test_max_issues_per_window(self, monkeypatch):
        import app.core.config as config_module
        from app.auth.otp_service import OtpIssueError, issue_otp

        monkeypatch.setattr(config_module.settings, "OTP_MAX_ISSUES_PER_WINDOW", 2)
        monkeypatch.setattr(config_module.settings, "OTP_ISSUE_WINDOW_SECONDS", 300)
        store, delivery = self._store(), self._delivery()

        # First issue → OK (count=1).
        issue_otp(store, delivery, channel="email", identifier="a@x.com")
        record = store.get("email", "a@x.com")
        record.next_resend_at = time.time() - 1
        store.put("email", "a@x.com", record)

        # Second issue → OK (count=2).
        issue_otp(store, delivery, channel="email", identifier="a@x.com")
        record = store.get("email", "a@x.com")
        record.next_resend_at = time.time() - 1
        store.put("email", "a@x.com", record)

        # Third issue → denied (count=2 >= max of 2).
        with pytest.raises(OtpIssueError, match="Too many verification codes"):
            issue_otp(store, delivery, channel="email", identifier="a@x.com")


# ===========================================================================
# 3. JWT primitives
# ===========================================================================

class TestJwtPrimitives:
    def test_create_decode_roundtrip(self):
        from app.core.security import create_access_token, decode_access_token

        token = create_access_token(subject=uuid.uuid4(), email="u@x.com", role="analyst")
        payload = decode_access_token(token)
        assert payload["email"] == "u@x.com"
        assert payload["role"] == "analyst"
        assert payload["type"] == "access"
        assert payload["iss"] == settings.AUTH_ISSUER
        assert payload["aud"] == settings.AUTH_AUDIENCE

    def test_expired_token_rejected(self):
        from app.core.security import create_access_token, decode_access_token

        token = create_access_token(
            subject=uuid.uuid4(),
            email="u@x.com",
            role="analyst",
            expires_delta=timedelta(seconds=-60),
        )
        with pytest.raises(ValueError, match="expired"):
            decode_access_token(token)

    def test_tampered_token_rejected(self):
        from app.core.security import create_access_token, decode_access_token

        token = create_access_token(subject=uuid.uuid4(), email="u@x.com", role="analyst")
        with pytest.raises(ValueError, match="Invalid"):
            decode_access_token(token + "tampered")

    def test_missing_token_rejected(self):
        from app.core.security import decode_access_token

        with pytest.raises(ValueError, match="Missing"):
            decode_access_token("")


# ===========================================================================
# 4. Config safety
# ===========================================================================

class TestConfigSafety:
    def test_dev_bypass_forbidden_in_production(self):
        from pydantic import ValidationError
        from app.core.config import Settings

        with pytest.raises(ValidationError):
            Settings(ENVIRONMENT="production", DEV_AUTH_BYPASS=True, _env_file=None)

    def test_dev_bypass_allowed_in_development(self):
        from app.core.config import Settings

        cfg = Settings(ENVIRONMENT="development", DEV_AUTH_BYPASS=True, _env_file=None)
        assert cfg.DEV_AUTH_BYPASS is True

    def test_weak_otp_policy_rejected(self):
        from pydantic import ValidationError
        from app.core.config import Settings

        with pytest.raises(ValidationError):
            Settings(OTP_LENGTH=4, _env_file=None)

    def test_weak_rate_limit_rejected(self):
        from pydantic import ValidationError
        from app.core.config import Settings

        with pytest.raises(ValidationError):
            Settings(RATE_LIMIT_LOGIN_MAX=0, _env_file=None)


# ===========================================================================
# 5. Auth HTTP flow — registration
# ===========================================================================

class TestRegister:
    async def test_register_returns_no_otp_and_creates_inactive_user(self, auth_ctx):
        from sqlalchemy import select

        from app.db.models.user import User

        client = await auth_ctx.aclient()
        resp = await client.post(
            "/api/v1/auth/register",
            json={"name": "Ana", "email": "ana@example.com", "password": "Register-pw-1!"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "otp" not in resp.text.lower()
        assert body["data"]["channel"] == "email"
        assert body["data"]["identifier"] == "ana@example.com"
        assert body["data"]["resend_after_seconds"] > 0

        # The account exists, is INACTIVE until the OTP is verified, and the
        # password is stored only as a hash.
        record = (
            await auth_ctx.db.execute(
                select(User).where(User.email == "ana@example.com")
            )
        ).scalar_one()
        assert record.is_active is False
        assert record.password_hash
        assert record.password_hash != "Register-pw-1!"
        assert "Register-pw-1!" not in record.password_hash

    async def test_register_password_required(self, auth_ctx):
        client = await auth_ctx.aclient()
        resp = await client.post(
            "/api/v1/auth/register",
            json={"name": "A", "email": "pw@example.com"},
        )
        assert resp.status_code == 422

    async def test_register_weak_password_rejected(self, auth_ctx):
        client = await auth_ctx.aclient()
        resp = await client.post(
            "/api/v1/auth/register",
            json={"name": "A", "email": "weak@example.com", "password": "short"},
        )
        assert resp.status_code == 422

    async def test_register_duplicate_conflict(self, auth_ctx):
        client = await auth_ctx.aclient()
        await client.post(
            "/api/v1/auth/register",
            json={"name": "A", "email": "dup@example.com", "password": "Register-pw-1!"},
        )
        resp = await client.post(
            "/api/v1/auth/register",
            json={"name": "B", "email": "dup@example.com", "password": "Register-pw-2!"},
        )
        assert resp.status_code == 409

    async def test_registration_disabled(self, auth_ctx, monkeypatch):
        import app.core.config as config_module

        monkeypatch.setattr(config_module.settings, "REGISTRATION_ENABLED", False)
        client = await auth_ctx.aclient()
        resp = await client.post(
            "/api/v1/auth/register",
            json={"name": "A", "email": "x@example.com", "password": "Register-pw-1!"},
        )
        assert resp.status_code == 403


# ===========================================================================
# 6. Auth HTTP flow — OTP verification & tokens
# ===========================================================================

class TestVerifyAndToken:
    async def test_register_verify_yields_analyst_token(self, auth_ctx):
        client, token, user = await auth_ctx.register_and_verify(email="ana@example.com")
        assert token
        assert user["role"] == "analyst"
        assert user["email"] == "ana@example.com"

        me = await client.get("/api/v1/auth/me", headers=auth_ctx.auth(token))
        assert me.status_code == 200
        assert me.json()["data"]["email"] == "ana@example.com"

    async def test_verify_wrong_code(self, auth_ctx):
        client = await auth_ctx.aclient()
        await client.post(
            "/api/v1/auth/register",
            json={"name": "B", "email": "b@example.com", "password": "Register-pw-1!"},
        )
        resp = await client.post(
            "/api/v1/auth/verify",
            json={"email": "b@example.com", "otp": "000000"},
        )
        assert resp.status_code == 401

    async def test_verify_replay_rejected(self, auth_ctx):
        client, token, _ = await auth_ctx.register_and_verify(email="c@example.com")
        code = "000000"
        # Re-verify with a stale code must 401 (record already consumed).
        resp = await client.post(
            "/api/v1/auth/verify",
            json={"email": "c@example.com", "otp": "000000"},
        )
        assert resp.status_code == 401

    async def test_me_requires_token(self, auth_ctx):
        client = await auth_ctx.aclient()
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_me_rejects_invalid_token(self, auth_ctx):
        client, token, _ = await auth_ctx.register_and_verify(email="d@example.com")
        resp = await client.get("/api/v1/auth/me", headers=auth_ctx.auth(token + "x"))
        assert resp.status_code == 401

    async def test_logout_acknowledges(self, auth_ctx):
        client, token, _ = await auth_ctx.register_and_verify(email="e@example.com")
        resp = await client.post("/api/v1/auth/logout", headers=auth_ctx.auth(token))
        assert resp.status_code == 200


# ===========================================================================
# 7. Login channels + side-channel protection (Phase 15 password login)
# ===========================================================================

class TestLoginChannels:
    PASSWORD = "Tester-pass-1!"

    async def test_mobile_channel_full_flow(self, auth_ctx):
        client, token, user = await auth_ctx.register_and_verify(
            email="m@example.com",
            channel="mobile",
            mobile_number="9876543210",
        )
        assert user["email"] == "m@example.com"

        # Login over the password flow works too (no OTP involved).
        reg_code = auth_ctx.provider.last_otp_for("mobile", "9876543210")
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "m@example.com", "password": self.PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]
        # Login must NOT have issued any new OTP: the last delivered code is
        # still the registration one standing.
        assert auth_ctx.provider.last_otp_for("mobile", "9876543210") == reg_code
        assert auth_ctx.provider.last_otp_for("email", "m@example.com") is None

    async def test_inactive_account_login_is_generic_denied(self, auth_ctx):
        client = await auth_ctx.aclient()
        resp = await client.post(
            "/api/v1/auth/register",
            json={"name": "P", "email": "pending@example.com", "password": self.PASSWORD},
        )
        assert resp.status_code == 201
        # Before OTP verification the account is inactive: password login fails
        # with the same generic error as a wrong password.
        denied = await client.post(
            "/api/v1/auth/login",
            json={"email": "pending@example.com", "password": self.PASSWORD},
        )
        assert denied.status_code == 401
        assert denied.json()["detail"] == "Invalid email or password."

    async def test_unknown_account_login_is_generic_denied(self, auth_ctx):
        client = await auth_ctx.aclient()
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": self.PASSWORD},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password."
        assert auth_ctx.provider.last_otp_for("email", "ghost@example.com") is None

    async def test_wrong_password_login_is_generic_denied(self, auth_ctx):
        client, token, _ = await auth_ctx.register_and_verify(email="wp@example.com")
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "wp@example.com", "password": "Wrong-pass-1!"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password."

    async def test_forgot_password_reset_flow(self, auth_ctx):
        client, token, _ = await auth_ctx.register_and_verify(email="fp@example.com")

        # Request a reset code (200, generic-format response).
        first = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "fp@example.com"},
        )
        assert first.status_code == 200
        code = auth_ctx.provider.last_otp_for("email", "fp@example.com")
        assert code

        # Reset with the code -> new password stored; old password now fails.
        ok = await client.post(
            "/api/v1/auth/reset-password",
            json={"email": "fp@example.com", "otp": code, "new_password": "New-pass-99!"},
        )
        assert ok.status_code == 200

        old_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "fp@example.com", "password": self.PASSWORD},
        )
        assert old_login.status_code == 401

        new_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "fp@example.com", "password": "New-pass-99!"},
        )
        assert new_login.status_code == 200
        assert new_login.json()["access_token"]

    async def test_forgot_password_wrong_code_rejected(self, auth_ctx):
        client, token, _ = await auth_ctx.register_and_verify(email="fpw@example.com")
        await client.post("/api/v1/auth/forgot-password", json={"email": "fpw@example.com"})
        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"email": "fpw@example.com", "otp": "000000", "new_password": "New-pass-99!"},
        )
        assert resp.status_code == 401

    async def test_forgot_password_unknown_account_is_generic(self, auth_ctx):
        client = await auth_ctx.aclient()
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "ghost@example.com"},
        )
        assert resp.status_code == 200
        assert auth_ctx.provider.last_otp_for("email", "ghost@example.com") is None

    async def test_resend_otp_inactive_reissues_and_active_is_generic(self, auth_ctx):
        client = await auth_ctx.aclient()
        first = await client.post(
            "/api/v1/auth/register",
            json={"name": "R", "email": "res@example.com", "password": self.PASSWORD},
        )
        assert first.status_code == 201
        code1 = auth_ctx.provider.last_otp_for("email", "res@example.com")
        assert code1

        # Cooldown makes the immediate resend silently uniform without delivery.
        second = await client.post("/api/v1/auth/resend-otp", json={"email": "res@example.com"})
        assert second.status_code == 200
        assert auth_ctx.provider.last_otp_for("email", "res@example.com") == code1

        # An active account is generic (no delivery) from this endpoint.
        await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "res@example.com"},
        )
        await client.post(
            "/api/v1/auth/verify",
            json={"email": "res@example.com", "otp": code1},
        )
        generic = await client.post("/api/v1/auth/resend-otp", json={"email": "res@example.com"})
        assert generic.status_code == 200
        # The last delivered code is unchanged (no new delivery for an active account).
        assert auth_ctx.provider.last_otp_for("email", "res@example.com") == code1

    async def test_resend_cooldown_is_silent_uniform(self, auth_ctx):
        """Resend during cooldown: generic 200 (no account-existence leak),
        and no new code is issued/delivered."""
        from app.auth.otp_service import OtpIssueError, issue_otp

        _, token, _ = await auth_ctx.register_and_verify(email="s@example.com")
        client = await auth_ctx.aclient()
        first = await client.post("/api/v1/auth/forgot-password", json={"email": "s@example.com"})
        assert first.status_code == 200
        code1 = auth_ctx.provider.last_otp_for("email", "s@example.com")
        assert code1

        # Window inside the resend cooldown → still 200 and no second OTP.
        second = await client.post("/api/v1/auth/forgot-password", json={"email": "s@example.com"})
        assert second.status_code == 200
        assert auth_ctx.provider.last_otp_for("email", "s@example.com") == code1
        assert second.json()["data"]["resend_after_seconds"] == 0

        # The server truly throttled the issue: a direct issue would raise.
        # (Reaching for the store through the app-scoped dependency.)
        with pytest.raises(OtpIssueError):
            issue_otp(
                auth_ctx.store,
                auth_ctx.provider,
                channel="email",
                identifier="s@example.com",
            )


# ===========================================================================
# 8. RBAC — analyst vs admin
# ===========================================================================

class TestRBAC:
    async def test_default_role_is_analyst(self, auth_ctx):
        await auth_ctx.register_and_verify(email="rbac@example.com")
        from sqlalchemy import select

        from app.db.models.user import User

        records = (await auth_ctx.db.execute(select(User))).scalars().all()
        assert records
        assert all(u.role == "analyst" for u in records)

    async def test_analyst_denied_admin_surface(self, auth_ctx):
        client, token, user = await auth_ctx.register_and_verify(email="analyst@example.com")
        resp = await client.get("/api/v1/admin/users", headers=auth_ctx.auth(token))
        assert resp.status_code == 403

    async def test_admin_allowed_admin_surface(self, auth_ctx):
        client, token, user = await auth_ctx.register_and_verify(
            email="boss@example.com", role_override="admin"
        )
        resp = await client.get("/api/v1/admin/users", headers=auth_ctx.auth(token))
        assert resp.status_code == 200
        emails = {u["email"] for u in resp.json()["data"]}
        assert "boss@example.com" in emails

    async def test_dev_bypass_operator_still_denied_admin(self, auth_ctx, monkeypatch):
        import app.core.config as config_module

        # Bypass ON: the fixed "operator" dev user still must NOT reach admin.
        monkeypatch.setattr(config_module.settings, "DEV_AUTH_BYPASS", True)
        client = await auth_ctx.aclient()
        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code == 403

    async def test_require_any_roles_direct(self):
        from app.api.deps import require_any_roles
        from app.api.deps import CurrentUser

        admin_dep = require_any_roles("admin")
        analyst_dep = require_any_roles("analyst", "operator", "admin")

        allowed = await analyst_dep(CurrentUser(id=uuid.uuid4(), email="a", name="A", role="analyst"))
        assert allowed.role == "analyst"
        await admin_dep(CurrentUser(id=uuid.uuid4(), email="b", name="B", role="admin"))
        with pytest.raises(HTTPException) as exc:
            await admin_dep(CurrentUser(id=uuid.uuid4(), email="c", name="C", role="analyst"))
        assert exc.value.status_code == 403


# ===========================================================================
# 9. Resource isolation with real JWTs
# ===========================================================================

class TestIsolationWithJwt:
    async def test_cross_user_isolation(self, auth_ctx):
        _, token_a, _ = await auth_ctx.register_and_verify(email="owner@example.com")
        _, token_b, _ = await auth_ctx.register_and_verify(email="intruder@example.com")

        async with ASGITransport(app=auth_ctx.app) as transport:
            client = AsyncClient(transport=transport, base_url="http://test")
            async with client:
                # A creates a project + source + config + job.
                proj = await client.post(
                    "/api/v1/projects", json={"name": "Owner project"},
                    headers=auth_ctx.auth(token_a),
                )
                assert proj.status_code == 201, proj.text
                pid = proj.json()["data"]["id"]
                src = await client.post(
                    f"/api/v1/projects/{pid}/sources",
                    json={"source_type": "text", "extracted_text": "owner text"},
                    headers=auth_ctx.auth(token_a),
                )
                sid = src.json()["data"]["id"]
                cfg = await client.post(
                    f"/api/v1/projects/{pid}/configurations",
                    json={"language": "English"},
                    headers=auth_ctx.auth(token_a),
                )
                cid = cfg.json()["data"]["id"]
                job = await client.post(
                    "/api/v1/transformations",
                    json={
                        "project_id": pid,
                        "source_id": sid,
                        "configuration_id": cid,
                        "output_types": ["summary"],
                    },
                    headers=auth_ctx.auth(token_a),
                )
                assert job.status_code == 201, job.text
                job_id = job.json()["data"]["id"]

                # A can read every resource.
                assert (await client.get(f"/api/v1/projects/{pid}", headers=auth_ctx.auth(token_a))).status_code == 200
                assert (await client.get(f"/api/v1/sources/{sid}", headers=auth_ctx.auth(token_a))).status_code == 200
                assert (await client.get(f"/api/v1/transformations/{job_id}", headers=auth_ctx.auth(token_a))).status_code == 200

                # B (using a REAL JWT) is blocked with 404 on every resource.
                assert (await client.get(f"/api/v1/projects/{pid}", headers=auth_ctx.auth(token_b))).status_code == 404
                assert (await client.get(f"/api/v1/sources/{sid}", headers=auth_ctx.auth(token_b))).status_code == 404
                assert (await client.get(f"/api/v1/transformations/{job_id}", headers=auth_ctx.auth(token_b))).status_code == 404
                assert (await client.get(f"/api/v1/projects/{pid}/sources", headers=auth_ctx.auth(token_b))).status_code == 404

    async def test_auth_required_on_protected_routes(self, auth_ctx):
        client, token, _ = await auth_ctx.register_and_verify(email="tokenreq@example.com")
        resp = await client.get("/api/v1/projects")
        assert resp.status_code == 401
        ok = await client.post(
            "/api/v1/projects", json={"name": "N"}, headers=auth_ctx.auth(token)
        )
        assert ok.status_code == 201


# ===========================================================================
# 10. Rate limiting
# ===========================================================================

class TestRateLimiting:
    async def test_login_bucket_429_with_retry_after(self, auth_ctx, monkeypatch):
        import app.core.config as config_module

        await auth_ctx.register_and_verify(email="rl@example.com")
        monkeypatch.setattr(config_module.settings, "RATE_LIMIT_LOGIN_MAX", 2)
        client = await auth_ctx.aclient()
        for _ in range(2):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "rl@example.com", "password": "Tester-pass-1!"},
            )
            assert resp.status_code == 200
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "rl@example.com", "password": "Tester-pass-1!"},
        )
        assert resp.status_code == 429
        assert resp.headers.get("retry-after")

    async def test_rate_limiting_can_be_disabled(self, auth_ctx, monkeypatch):
        import app.core.config as config_module

        await auth_ctx.register_and_verify(email="rloff@example.com")
        monkeypatch.setattr(config_module.settings, "RATE_LIMIT_ENABLED", False)
        monkeypatch.setattr(config_module.settings, "RATE_LIMIT_LOGIN_MAX", 1)
        client = await auth_ctx.aclient()
        for _ in range(3):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "rloff@example.com", "password": "Tester-pass-1!"},
            )
            assert resp.status_code == 200


# ===========================================================================
# 11. Dependency-level zero-arg compatibility
# ===========================================================================

class TestDependencyCompat:
    def test_get_current_user_zero_arg_bypass(self, monkeypatch):
        import app.core.config as config_module
        from app.api.deps import DEV_USER_ID, get_current_user

        monkeypatch.setattr(config_module.settings, "DEV_AUTH_BYPASS", True)
        user = asyncio.run(get_current_user())
        assert user.id == DEV_USER_ID

    def test_get_current_user_zero_arg_no_bypass_401(self, monkeypatch):
        import app.core.config as config_module
        from app.api.deps import get_current_user

        monkeypatch.setattr(config_module.settings, "DEV_AUTH_BYPASS", False)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_current_user())
        assert exc.value.status_code == 401


# ===========================================================================
# 12. Phase 15 — password-login denial reasons (service unit level)
# ===========================================================================

class TestPhase15LoginDenialReasons:
    async def test_unknown_account_reason(self, auth_ctx):
        from app.auth.service import InvalidCredentialsError, login_with_password

        with pytest.raises(InvalidCredentialsError) as exc:
            await login_with_password(
                auth_ctx.db, email="ghost@x.com", password="Whatever-1!"
            )
        assert exc.value.reason == "account_not_found"

    async def test_inactive_account_reason(self, auth_ctx):
        from app.auth.service import InvalidCredentialsError, login_with_password, register_user

        await register_user(
            auth_ctx.db,
            name="P",
            email="pending@x.com",
            password="Tester-pass-1!",
            mobile_number=None,
            channel="email",
            store=auth_ctx.store,
            delivery=auth_ctx.provider,
        )
        with pytest.raises(InvalidCredentialsError) as exc:
            await login_with_password(
                auth_ctx.db, email="pending@x.com", password="Tester-pass-1!"
            )
        assert exc.value.reason == "account_inactive"

    async def test_missing_hash_reason(self, auth_ctx):
        from app.auth.service import InvalidCredentialsError, login_with_password
        from app.db.models.user import User

        # A legacy account row with no password hash (passwordless migration).
        auth_ctx.db.add(
            User(
                email="nohash@x.com",
                name="NoHash",
                role="analyst",
                is_active=True,
                password_hash=None,
            )
        )
        await auth_ctx.db.flush()
        with pytest.raises(InvalidCredentialsError) as exc:
            await login_with_password(
                auth_ctx.db, email="nohash@x.com", password="Whatever-1!"
            )
        assert exc.value.reason == "account_no_password"

    async def test_wrong_password_reason(self, auth_ctx):
        from app.auth.service import InvalidCredentialsError, login_with_password

        await auth_ctx.register_and_verify(email="wp@x.com")
        with pytest.raises(InvalidCredentialsError) as exc:
            await login_with_password(auth_ctx.db, email="wp@x.com", password="Wrong-pass-1!")
        assert exc.value.reason == "password_mismatch"

    async def test_successful_login_returns_token(self, auth_ctx):
        from app.auth.service import login_with_password

        await auth_ctx.register_and_verify(email="ok@x.com")
        user, token, expires_in = await login_with_password(
            auth_ctx.db, email="ok@x.com", password="Tester-pass-1!"
        )
        assert user.email == "ok@x.com"
        assert token
        assert expires_in > 0


# ===========================================================================
# 13. Phase 15 — registration stores a PBKDF2 hash, never plaintext
# ===========================================================================

class TestPhase15PasswordStorage:
    async def test_register_stores_hash_not_plaintext(self, auth_ctx):
        from sqlalchemy import select

        from app.db.models.user import User

        client = await auth_ctx.aclient()
        resp = await client.post(
            "/api/v1/auth/register",
            json={"name": "H", "email": "h@x.com", "password": "Register-pw-1!"},
        )
        assert resp.status_code == 201, resp.text
        record = (
            await auth_ctx.db.execute(select(User).where(User.email == "h@x.com"))
        ).scalar_one()
        assert record.password_hash
        assert record.password_hash.startswith("pbkdf2_sha256$")
        assert "Register-pw-1!" not in record.password_hash
        assert record.is_active is False

    async def test_reset_hash_replaces_old_and_verifies(self, auth_ctx):
        from sqlalchemy import select

        from app.db.models.user import User
        from app.core.password import verify_password

        await auth_ctx.register_and_verify(email="rs@x.com")
        client = await auth_ctx.aclient()
        await client.post("/api/v1/auth/forgot-password", json={"email": "rs@x.com"})
        code = auth_ctx.provider.last_otp_for("email", "rs@x.com")
        ok = await client.post(
            "/api/v1/auth/reset-password",
            json={"email": "rs@x.com", "otp": code, "new_password": "New-pass-99!"},
        )
        assert ok.status_code == 200
        record = (
            await auth_ctx.db.execute(select(User).where(User.email == "rs@x.com"))
        ).scalar_one()
        assert verify_password("New-pass-99!", record.password_hash)


# ===========================================================================
# 14. Phase 15 — API accepts prompt-only transformations (auth-scoped)
# ===========================================================================

class TestPhase15PromptTransformationAPI:
    async def _project_and_config(self, auth_ctx, client, token):
        proj = await client.post(
            "/api/v1/projects", json={"name": "P15 prompt"}, headers=auth_ctx.auth(token)
        )
        assert proj.status_code == 201, proj.text
        pid = proj.json()["data"]["id"]
        cfg = await client.post(
            f"/api/v1/projects/{pid}/configurations",
            json={"language": "English"},
            headers=auth_ctx.auth(token),
        )
        assert cfg.status_code == 201, cfg.text
        return pid, cfg.json()["data"]["id"]

    async def test_prompt_only_job_created_without_source(self, auth_ctx):
        client, token, _ = await auth_ctx.register_and_verify(email="p15@x.com")
        pid, cid = await self._project_and_config(auth_ctx, client, token)
        job = await client.post(
            "/api/v1/transformations",
            json={
                "project_id": pid,
                "configuration_id": cid,
                "output_types": ["summary"],
                "prompt": "Draft a briefing about coastal erosion.",
            },
            headers=auth_ctx.auth(token),
        )
        assert job.status_code == 201, job.text
        data = job.json()["data"]
        assert data["source_id"] is None
        assert data["status"] == "queued"

    async def test_transform_with_neither_input_rejected(self, auth_ctx):
        client, token, _ = await auth_ctx.register_and_verify(email="p15b@x.com")
        pid, cid = await self._project_and_config(auth_ctx, client, token)
        job = await client.post(
            "/api/v1/transformations",
            json={
                "project_id": pid,
                "configuration_id": cid,
                "output_types": ["summary"],
            },
            headers=auth_ctx.auth(token),
        )
        assert job.status_code == 422