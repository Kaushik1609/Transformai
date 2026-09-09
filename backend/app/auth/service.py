"""
TransformIQ Backend — Auth Service (Phase 11F, extended Phase 15)

High-level authentication flows:

- ``register_user``: creates an analyst account (password-hashed, inactive)
  and issues a registration-activation OTP.
- ``login_with_password``: validates email + password for an ACTIVE account
  and mints a short-lived JWT.  All failure modes raise a single generic
  ``InvalidCredentialsError`` so responses never disclose whether an email is
  registered, whether an account is inactive, or why a password was rejected.
- ``verify_login``: consumes the registration OTP, activates the account,
  and mints a JWT.
- ``request_password_reset_otp`` / ``reset_password``: OTP-gated password
  reset reused from the same OTP service infrastructure.  Unknown or inactive
  accounts receive a generic response without a delivery so account existence
  is never leaked.
- ``resend_registration_otp``: lets a pending (registered, inactive) account
  request a fresh activation code without exposing account existence.

Errors surface as ``ValueError`` subclasses; route handlers translate them to
4xx responses.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.otp_delivery import Channel, OtpDeliveryProvider, OtpDeliveryError
from app.auth.otp_service import OtpIssueError, OtpIssueResult, OtpVerifyError, issue_otp, verify_otp
from app.auth.otp_store import OtpStore
from app.core.config import settings
from app.core.password import hash_password, verify_password
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


class InvalidCredentialsError(ValueError):
    """Single generic credential failure (unknown email / inactive / bad password).

    Every path raises the same public message ``"Invalid email or password."``;
    the internal ``reason`` is used only by the security-audit hook, never the
    HTTP response body.
    """

    def __init__(self, reason: str) -> None:
        super().__init__("Invalid email or password.")
        self.reason = reason


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


def _generic_otp_result(channel: Channel, email: str, mobile_number: str | None) -> OtpIssueResult:
    """Uniform, side-channel-free result for unknown/ineligible accounts."""
    identifier = (
        _login_identifier(channel, email, mobile_number) if channel == "email" else (mobile_number or "")
    )
    return OtpIssueResult(
        channel=channel,
        identifier=identifier,
        resend_after_seconds=settings.OTP_RESEND_COOLDOWN_SECONDS,
    )


async def register_user(
    db: AsyncSession,
    *,
    name: str,
    email: str,
    password: str,
    mobile_number: str | None,
    channel: Channel,
    store: OtpStore,
    delivery: OtpDeliveryProvider,
) -> tuple[User, OtpIssueResult]:
    """Create a new (inactive) analyst account and issue the activation OTP.

    The password is PBKDF2-hashed before persistence and the account is
    created ``is_active=False``; it only becomes active after the
    registration OTP is verified (``verify_login``).
    """
    if not settings.REGISTRATION_ENABLED:
        raise RegistrationDisabledError("Registration is currently disabled.")
    email = email.strip().lower()
    existing = await _fetch_user_by_email(db, email)
    if existing is not None:
        raise DuplicateAccountError("An account with that email already exists.")

    password_hash = await asyncio.to_thread(hash_password, password)
    user = User(
        email=email,
        name=name.strip(),
        role=ROLE_ANALYST,
        mobile_number=mobile_number,
        password_hash=password_hash,
        is_active=False,
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


async def login_with_password(
    db: AsyncSession,
    *,
    email: str,
    password: str,
) -> tuple[User, str, int]:
    """Validate email + password and mint a JWT for an active account.

    Failure modes are deliberately indistinguishable to callers:
    unknown email, inactive account, missing hash, or wrong password all raise
    ``InvalidCredentialsError("Invalid email or password.")``.
    """
    email = email.strip().lower()
    user = await _fetch_user_by_email(db, email)
    if user is None:
        raise InvalidCredentialsError("account_not_found")
    if not user.is_active:
        raise InvalidCredentialsError("account_inactive")
    if not user.password_hash:
        raise InvalidCredentialsError("account_no_password")
    verified = await asyncio.to_thread(verify_password, password, user.password_hash)
    if not verified:
        raise InvalidCredentialsError("password_mismatch")

    token = create_access_token(
        subject=user.id,
        email=user.email,
        role=user.role,
    )
    expires_in = settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return user, token, expires_in


async def verify_login(
    db: AsyncSession,
    *,
    email: str,
    channel: Channel,
    otp: str,
    mobile_number: str | None,
    store: OtpStore,
) -> tuple[User, str, int]:
    """Verify the submitted OTP and, on success, return (user, token, expires_in).

    Verifying the registration OTP activates the previously inactive account.
    """
    email = email.strip().lower()
    user = await _fetch_user_by_email(db, email)
    if user is None:
        raise AccountNotFoundError("No account is associated with that email.")

    identifier = _login_identifier(channel, email, mobile_number)
    if channel == "mobile" and user.mobile_number and identifier != user.mobile_number:
        raise AccountNotFoundError("No account is associated with that mobile number.")

    verify_otp(store, channel=channel, identifier=identifier, otp=otp)

    if not user.is_active:
        user.is_active = True
        await db.flush()

    token = create_access_token(
        subject=user.id,
        email=user.email,
        role=user.role,
    )
    expires_in = settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return user, token, expires_in


async def request_password_reset_otp(
    db: AsyncSession,
    *,
    email: str,
    channel: Channel,
    mobile_number: str | None,
    store: OtpStore,
    delivery: OtpDeliveryProvider,
) -> OtpIssueResult:
    """
    Request a password-reset OTP for an active account.

    Unknown and inactive accounts get a generic result WITHOUT a delivery so
    the response is indistinguishable from a successful request.
    """
    email = email.strip().lower()
    user = await _fetch_user_by_email(db, email)
    if user is None or not user.is_active:
        return _generic_otp_result(channel, email, mobile_number)

    identifier = _login_identifier(channel, email, mobile_number)
    if channel == "mobile" and user.mobile_number and identifier != user.mobile_number:
        return _generic_otp_result(channel, email, mobile_number)

    return issue_otp(
        store,
        delivery,
        channel=channel,
        identifier=identifier,
        should_deliver=True,
        reason="password_reset",
    )


async def reset_password(
    db: AsyncSession,
    *,
    email: str,
    otp: str,
    new_password: str,
    channel: Channel,
    mobile_number: str | None,
    store: OtpStore,
) -> None:
    """Consume the reset OTP and set a new password hash for the account.

    Unknown accounts fail with ``AccountNotFoundError`` carrying a generic
    message that does not reveal whether the account exists.
    """
    email = email.strip().lower()
    user = await _fetch_user_by_email(db, email)
    if user is None:
        raise AccountNotFoundError("Invalid or expired reset code.")

    identifier = _login_identifier(channel, email, mobile_number)
    if channel == "mobile" and user.mobile_number and identifier != user.mobile_number:
        raise AccountNotFoundError("Invalid or expired reset code.")

    verify_otp(store, channel=channel, identifier=identifier, otp=otp)

    new_hash = await asyncio.to_thread(hash_password, new_password)
    user.password_hash = new_hash
    await db.flush()


async def resend_registration_otp(
    db: AsyncSession,
    *,
    email: str,
    channel: Channel,
    mobile_number: str | None,
    store: OtpStore,
    delivery: OtpDeliveryProvider,
) -> OtpIssueResult:
    """
    Re-issue a registration-activation OTP for a pending (inactive) account.

    Unknown and already-active accounts get a generic result WITHOUT a
    delivery, so this endpoint never leaks whether an email is registered.
    """
    email = email.strip().lower()
    user = await _fetch_user_by_email(db, email)
    if user is None or user.is_active:
        return _generic_otp_result(channel, email, mobile_number)

    identifier = _login_identifier(channel, email, mobile_number)
    if channel == "mobile" and user.mobile_number and identifier != user.mobile_number:
        return _generic_otp_result(channel, email, mobile_number)

    return issue_otp(
        store,
        delivery,
        channel=channel,
        identifier=identifier,
        should_deliver=True,
        reason="registration",
    )


async def get_user_by_id(db: AsyncSession, user_id: Any) -> User | None:
    return await _fetch_user_by_id(db, user_id)