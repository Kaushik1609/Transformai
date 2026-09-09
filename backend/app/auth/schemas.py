"""
TransformIQ Backend — Auth API Schemas (Phase 11F, extended Phase 15)

Request/response models for registration, password login, registration-OTP
activation, and password reset. Follows the project's `{success, data}` style.
"""
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email_format(v):
    """Lightweight syntax-only email check (avoids the email-validator dep)."""
    value = (v or "").strip().lower()
    if not _EMAIL_RE.match(value) or len(value) > 254:
        raise ValueError("email must be a valid email address.")
    return value


def _validate_mobile_format(v: str | None) -> str | None:
    """Normalize a phone number to bare digits, rejecting non-numeric input."""
    if v is None:
        return None
    clean = v.replace(" ", "").replace("-", "")
    if len(clean) < 5 or len(clean) > 15 or not clean.isdigit():
        raise ValueError("mobile_number must be a valid numeric phone number.")
    return clean


def _validate_password(v: str) -> str:
    """Password policy: 8..128 characters, no leading/trailing whitespace."""
    value = v or ""
    if value != value.strip():
        raise ValueError("password must not have leading or trailing whitespace.")
    if len(value) < 8 or len(value) > 128:
        raise ValueError("password must be between 8 and 128 characters.")
    return value


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    """Body for POST /api/v1/auth/register."""

    name: str = Field(..., min_length=1, max_length=255, description="Display name")
    email: str = Field(..., description="Primary identity (login) email")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Account password (PBKDF2-hashed server-side; never stored in the clear)",
    )
    mobile_number: str | None = Field(
        default=None,
        min_length=5,
        max_length=20,
        description="Optional mobile contact used as the SMS OTP channel",
    )
    channel: Literal["email", "mobile"] = Field(
        default="email",
        description="Preferred OTP verification channel",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v):
        return _validate_email_format(v)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        return _validate_password(v)

    @field_validator("mobile_number")
    @classmethod
    def validate_mobile(cls, v: str | None) -> str | None:
        return _validate_mobile_format(v)


class LoginRequest(BaseModel):
    """Body for POST /api/v1/auth/login (email + password)."""

    email: str = Field(..., description="Registered account email")
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Account password",
    )

    @field_validator("email")
    @classmethod
    def normalize_login_email(cls, v):
        return _validate_email_format(v)


class VerifyOtpRequest(BaseModel):
    """Body for POST /api/v1/auth/verify (exchanges an OTP for a token)."""

    email: str = Field(...)
    channel: Literal["email", "mobile"] = Field(
        default="email",
        description="Channel the OTP was delivered over",
    )
    mobile_number: str | None = Field(
        default=None,
        min_length=5,
        max_length=20,
        description="The mobile number the OTP was sent to (required when channel=mobile)",
    )
    otp: str = Field(..., min_length=6, max_length=12, description="One-time passcode")

    @field_validator("email")
    @classmethod
    def normalize_verify_email(cls, v):
        return _validate_email_format(v)

    @field_validator("mobile_number")
    @classmethod
    def validate_verify_mobile(cls, v: str | None) -> str | None:
        return _validate_mobile_format(v)


class ResetPasswordRequest(BaseModel):
    """Body for POST /api/v1/auth/reset-password (confirm reset)."""

    email: str = Field(...)
    otp: str = Field(..., min_length=6, max_length=12, description="One-time passcode")
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="New account password",
    )
    channel: Literal["email", "mobile"] = Field(
        default="email",
        description="Channel the reset OTP was delivered over",
    )
    mobile_number: str | None = Field(
        default=None,
        min_length=5,
        max_length=20,
        description="Required when channel=mobile",
    )

    @field_validator("email")
    @classmethod
    def normalize_reset_email(cls, v):
        return _validate_email_format(v)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v):
        return _validate_password(v)

    @field_validator("mobile_number")
    @classmethod
    def validate_reset_mobile(cls, v: str | None) -> str | None:
        return _validate_mobile_format(v)


class ForgotPasswordRequest(BaseModel):
    """Body for POST /api/v1/auth/forgot-password."""

    email: str = Field(...)
    channel: Literal["email", "mobile"] = Field(
        default="email",
        description="Channel the reset OTP should be delivered over",
    )
    mobile_number: str | None = Field(
        default=None,
        min_length=5,
        max_length=20,
        description="Required when channel=mobile",
    )

    @field_validator("email")
    @classmethod
    def normalize_forgot_email(cls, v):
        return _validate_email_format(v)

    @field_validator("mobile_number")
    @classmethod
    def validate_forgot_mobile(cls, v: str | None) -> str | None:
        return _validate_mobile_format(v)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class UserSummary(BaseModel):
    """Public user identity returned to the client."""

    id: uuid.UUID
    email: str
    name: str
    role: str

    model_config = {"from_attributes": True}


class OtpDeliveryDetails(BaseModel):
    """Non-sensitive metadata about an issued OTP."""

    channel: str
    identifier: str
    resend_after_seconds: int = 0


class RegisterResponse(BaseModel):
    """Response for a successful registration."""

    success: bool = True
    data: OtpDeliveryDetails
    message: str = "Verification code sent."


class LoginResponse(BaseModel):
    """Generic, side-channel-free response for a password-reset request."""

    success: bool = True
    data: OtpDeliveryDetails
    message: str = "If an account exists for that email, a reset code was sent."


class PasswordResetResponse(BaseModel):
    """Response for a successful password reset / registration OTP resend."""

    success: bool = True
    message: str = "Password updated."


class AuthTokenResponse(BaseModel):
    """Successful OTP verification returns a short-lived access token."""

    success: bool = True
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserSummary


class MeResponse(BaseModel):
    """GET /api/v1/auth/me response."""

    success: bool = True
    data: UserSummary


class LogoutResponse(BaseModel):
    """Acknowledgement for logout (client side clears its token)."""

    success: bool = True
    message: str = "Logged out."


class AdminUserSummary(BaseModel):
    """Admin listing entry for a user record."""

    id: uuid.UUID
    email: str
    name: str
    role: str
    mobile_number: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUserListResponse(BaseModel):
    success: bool = True
    data: list[AdminUserSummary]
    count: int