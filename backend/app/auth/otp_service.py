"""
TransformIQ Backend — OTP Service (Phase 11F)

Encapsulates the OTP lifecycle (issue + verify) with the security policy:

- Single active code per (channel, identifier); issuing a new code
  invalidates the previous one.
- Resend cooldown (OTP_RESEND_COOLDOWN_SECONDS).
- Maximum issues per window (OTP_MAX_ISSUES_PER_WINDOW / OTP_ISSUE_WINDOW_SECONDS).
- Maximum verification attempts (OTP_MAX_ATTEMPTS) — the record is destroyed
  once the budget is exhausted.
- Expiry (OTP_EXPIRY_SECONDS), single-use consumption.
- Only the HMAC digest is persisted; verification is constant-time.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from app.auth.otp_delivery import Channel, OtpDeliveryProvider, OtpDeliveryError
from app.auth.otp_store import OtpRecord, OtpStore
from app.core.config import settings
from app.core.security import generate_otp, hash_otp_value, verify_otp_value


class OtpIssueError(ValueError):
    """Raised when an OTP cannot be issued (cooldown, quota)."""


class OtpVerifyError(ValueError):
    """Raised when an OTP fails verification (expired, invalid, exhausted)."""


@dataclass(frozen=True)
class OtpIssueResult:
    channel: str
    identifier: str
    resend_after_seconds: int


def _normalize_identifier(channel: Channel, identifier: str) -> str:
    value = (identifier or "").strip().lower()
    if not value:
        raise OtpIssueError("A valid identifier is required for OTP delivery.")
    return value


def issue_otp(
    store: OtpStore,
    delivery: OtpDeliveryProvider,
    *,
    channel: Channel,
    identifier: str,
    should_deliver: bool = True,
    reason: str = "authentication",
) -> OtpIssueResult:
    """Issue a new OTP for ``identifier``, enforcing the issuance policy.

    When ``should_deliver`` is False the code is created and stored but NOT
    sent — used to keep account-existence hidden during login.
    """
    identifier = _normalize_identifier(channel, identifier)
    now = time.time()

    record = store.get(channel, identifier)
    if record is not None:
        if now < record.next_resend_at:
            raise OtpIssueError(
                f"Please wait {int(record.next_resend_at - now) + 1} seconds before requesting another code."
            )
        in_window = (now - record.created_at) < settings.OTP_ISSUE_WINDOW_SECONDS
        if in_window and record.issue_count >= settings.OTP_MAX_ISSUES_PER_WINDOW:
            raise OtpIssueError(
                "Too many verification codes requested. Please try again later."
            )
        issue_count = record.issue_count + 1 if in_window else 1
    else:
        issue_count = 1

    otp = generate_otp()
    issued_at = int(now)
    otp_hash = hash_otp_value(otp, channel=channel, identifier=identifier, issued_at=issued_at)

    new_record = OtpRecord(
        otp_hash=otp_hash,
        issued_at=issued_at,
        expires_at=now + settings.OTP_EXPIRY_SECONDS,
        attempts_remaining=settings.OTP_MAX_ATTEMPTS,
        next_resend_at=now + settings.OTP_RESEND_COOLDOWN_SECONDS,
        issue_count=issue_count,
        created_at=record.created_at if record else now,
    )
    store.put(channel, identifier, new_record)

    if should_deliver:
        try:
            delivery.send_otp(
                channel=channel,
                identifier=identifier,
                otp=otp,
                reason=reason,
            )
        except OtpDeliveryError:
            # Delivery failure must not leave a dangling active code behind.
            store.delete(channel, identifier)
            raise

    return OtpIssueResult(
        channel=channel,
        identifier=identifier,
        resend_after_seconds=settings.OTP_RESEND_COOLDOWN_SECONDS,
    )


def verify_otp(
    store: OtpStore,
    *,
    channel: Channel,
    identifier: str,
    otp: str,
) -> None:
    """Verify an OTP, consuming it on success. Raises OtpVerifyError otherwise."""
    identifier = _normalize_identifier(channel, identifier)
    now = time.time()

    record = store.get(channel, identifier)
    if record is None or record.used or now > record.expires_at:
        raise OtpVerifyError("The verification code has expired or is invalid.")
    if record.attempts_remaining <= 0:
        store.delete(channel, identifier)
        raise OtpVerifyError("Too many invalid attempts. Request a new code.")

    if verify_otp_value(
        otp,
        record.otp_hash,
        channel=channel,
        identifier=identifier,
        issued_at=record.issued_at,
    ):
        store.delete(channel, identifier)  # single-use
        return

    record.attempts_remaining -= 1
    if record.attempts_remaining <= 0:
        store.delete(channel, identifier)
        raise OtpVerifyError("Too many invalid attempts. Request a new code.")
    store.put(channel, identifier, record)
    raise OtpVerifyError("Incorrect verification code. Please try again.")