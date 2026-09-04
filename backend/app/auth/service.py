"""
TransformIQ Backend — Auth Service (Phase 11F)

High-level authentication flows built on the OTP service:

- ``register_user``: creates an analyst account and issues a verification OTP.
- ``request_login_otp``: issues an OTP for an existing account. Deliberately
  returns a generic result for unknown emails so login does not leak whether
  an account exists.
- ``verify_login``: consumes the OTP and mints a short-lived JWT.

Errors surface as ``ValueError`` subclasses; route handlers translate them to
4xx responses.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.otp_delivery import Channel, OtpDeliveryProvider, OtpDeliveryError
from app.auth.otp_service import OtpIssueError, OtpIssueResult, OtpVerifyError, issue_otp, verify_otp
from app.auth.otp_store import OtpStore
from app.core.config import settings
from app.core.security import create_access_token
from app.db.models.user import User

# Roles (Phase 11F RBAC).
ROLE_ANALYST = "analyst"
ROLE_ADMIN = "admin"
# Legacy development/operator tier — kept for backward compatibility and
# treated as an analyst-level role.
ROLE_OPERATOR = "operator"

ALL_ANALYST_TIERS = {ROLE_ANALYST, ROLE_OPERATOR}


class RegistrationDisabledError(ValueError):
    pass


class DuplicateAccountError(ValueError):
    pass


class AccountNotFoundError(ValueError):
    pass


async def _fetch_user_by_email(db: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email.strip().lower())
    return (await db.execute(stmt)).scalar_one_or_none()


async def _fetch_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    stmt = select(User).where(User.id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


def _mask_identifier(identifier: str) -> str:
    at = identifier.rfind("@")
    if at > 0:
        local = identifier[:at]
        return f"{local[:1]}{'*' * max(1, min(4, len(local) - 1))}{identifier[at:]}"
    digits = "".join(c for c in identifier if c.isdigit())
    if digits:
        return f"******{digits[-4:]}"
    return "***"


def _login_identifier(channel: Channel, email: str, mobile_number: str | None) -> str:
    """Resolve the delivery identifier for a requested channel."""
    if channel == "email":
        return email
    if channel == "mobile":
        if not mobile_number:
            raise OtpIssueError("mobile_number is required when channel=mobile.")
        return mobile_number
    raise OtpIssueError(f"Unsupported verification channel: {channel!r}.")


async def register_user(
    db: AsyncSession,
    *,
    name: str,
    email: str,
    mobile_number: str | None,
    channel: Channel,
    store: OtpStore,
    delivery: OtpDeliveryProvider,
) -> tuple[User, OtpIssueResult]:
    """Create a new analyst account and issue the verification OTP."""
    if not settings.REGISTRATION_ENABLED:
        raise RegistrationDisabledError("Registration is currently disabled.")
    email = email.strip().lower()
    existing = await _fetch_user_by_email(db, email)
    if existing is not None:
        raise DuplicateAccountError("An account with that email already exists.")

    user = User(
        email=email,
        name=name.strip(),
        role=ROLE_ANALYST,
        mobile_number=mobile_number,
    )
    db.add(user)
    await db.flush()

    identifier = _login_identifier(channel, email, mobile_number)
    issued = issue_otp(
        store,
        delivery,
        channel=channel,
        identifier=identifier,
        should_deliver=True,
        reason="registration",
    )
    return user, issued


async def request_login_otp(
    db: AsyncSession,
    *,
    email: str,
    channel: Channel,
    mobile_number: str | None,
    store: OtpStore,
    delivery: OtpDeliveryProvider,
) -> OtpIssueResult:
    """
    Request an OTP for an existing account.

    Unknown accounts get a generic result WITHOUT a delivery so the response
    is indistinguishable from a successful request.
    """
    email = email.strip().lower()
    user = await _fetch_user_by_email(db, email)
    if user is None:
        return OtpIssueResult(
            channel=channel,
            identifier=_login_identifier(channel, email, mobile_number) if channel == "email" else (mobile_number or ""),
            resend_after_seconds=settings.OTP_RESEND_COOLDOWN_SECONDS,
        )

    identifier = _login_identifier(channel, email, mobile_number)
    if channel == "mobile" and user.mobile_number and identifier != user.mobile_number:
        # The supplied number does not match the registered number; behave
        # as if the account does not exist.
        return OtpIssueResult(
            channel=channel,
            identifier=identifier,
            resend_after_seconds=settings.OTP_RESEND_COOLDOWN_SECONDS,
        )

    return issue_otp(
        store,
        delivery,
        channel=channel,
        identifier=identifier,
        should_deliver=True,
        reason="login",
    )


async def verify_login(
    db: AsyncSession,
    *,
    email: str,
    channel: Channel,
    otp: str,
    mobile_number: str | None,
    store: OtpStore,
) -> tuple[User, str, int]:
    """Verify the submitted OTP and, on success, return (user, token, expires_in)."""
    email = email.strip().lower()
    user = await _fetch_user_by_email(db, email)
    if user is None:
        raise AccountNotFoundError("No account is associated with that email.")

    identifier = _login_identifier(channel, email, mobile_number)
    if channel == "mobile" and user.mobile_number and identifier != user.mobile_number:
        raise AccountNotFoundError("No account is associated with that mobile number.")

    verify_otp(store, channel=channel, identifier=identifier, otp=otp)

    token = create_access_token(
        subject=user.id,
        email=user.email,
        role=user.role,
    )
    expires_in = settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return user, token, expires_in


async def get_user_by_id(db: AsyncSession, user_id: Any) -> User | None:
    return await _fetch_user_by_id(db, user_id)