"""
TransformIQ Backend — Security Primitives (Phase 11F)

One-time-passcode (OTP) generation, hashing and verification built on
HMAC-SHA256, plus JWT creation/decoding built on python-jose.

Rules:
- OTP codes are numeric, length OTP_LENGTH, and generated with
  ``secrets`` (cryptographically secure).
- Only the HMAC-SHA256 hash of a code is ever persisted. The raw code is
  delivered to the user over the delivery channel and never stored.
- Comparisons use constant-time comparison (hmac.compare_digest).
- JWTs carry only public claims; no passwords or secrets are embedded.
"""
from __future__ import annotations

import hmac
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# OTP generation
# ---------------------------------------------------------------------------

def generate_otp(length: int | None = None) -> str:
    """Return a cryptographically secure numeric OTP of the configured length."""
    n = length or settings.OTP_LENGTH
    if not isinstance(n, int) or isinstance(n, bool) or n < 6:
        raise ValueError("OTP length must be an integer >= 6.")
    # secrets.randbelow avoids the modulo bias of random.randint and is CSPRNG-backed.
    upper = 10 ** n
    lower = 10 ** (n - 1)
    return str(secrets.randbelow(upper - lower) + lower)


# ---------------------------------------------------------------------------
# OTP hashing (HMAC-SHA256, salted with issued_at second + channel)
# ---------------------------------------------------------------------------

def _otp_salt(channel: str, identifier: str, issued_at: int) -> str:
    # Saling with (channel, identifier, issued_at) guarantees distinct digests
    # even if two users coincidentally receive the same code, while keeping
    # the salt derivable so the record can be validated again on replay.
    return f"{channel}:{identifier.lower()}:{issued_at}"


def hash_otp_value(otp: str, *, channel: str, identifier: str, issued_at: int | None = None) -> str:
    """Return the HMAC-SHA256 hex digest of ``otp`` keyed with AUTH_SECRET_KEY."""
    issued_at = int(time.time()) if issued_at is None else int(issued_at)
    salt = _otp_salt(channel, identifier, issued_at)
    digest = hmac.new(
        settings.AUTH_SECRET_KEY.encode("utf-8"),
        f"{salt}:{otp}".encode("utf-8"),
        "sha256",
    )
    return digest.hexdigest()


def verify_otp_value(otp: str, expected_hash: str, *, channel: str, identifier: str, issued_at: int) -> bool:
    """Constant-time comparison of a candidate OTP against a stored hash."""
    candidate = hash_otp_value(otp, channel=channel, identifier=identifier, issued_at=issued_at)
    try:
        return hmac.compare_digest(candidate, expected_hash)
    except TypeError:
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(
    *,
    subject: str | uuid.UUID,
    email: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Uses python-jose. Only non-sensitive claims are included.  Every token
    carries a unique ``jti`` claim (Phase 13A) enabling server-side revocation
    on logout without relying on shared state in the token itself.
    """
    from jose import jwt

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "jti": secrets.token_urlsafe(24),
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + (
            expires_delta or timedelta(minutes=settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES)
        ),
        "type": "access",
        "iss": settings.AUTH_ISSUER,
        "aud": settings.AUTH_AUDIENCE,
    }
    return jwt.encode(payload, settings.AUTH_SECRET_KEY, algorithm=settings.AUTH_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT access token.

    Raises ValueError with a human-facing message on any failure; callers
    translate it into a 401.
    """
    from jose import JWTError, ExpiredSignatureError, jwt

    if not token:
        raise ValueError("Missing access token.")
    try:
        payload = jwt.decode(
            token,
            settings.AUTH_SECRET_KEY,
            algorithms=[settings.AUTH_ALGORITHM],
            issuer=settings.AUTH_ISSUER,
            audience=settings.AUTH_AUDIENCE,
        )
    except ExpiredSignatureError:
        raise ValueError("Access token has expired.") from None
    except JWTError as exc:
        raise ValueError("Invalid access token.") from exc
    if payload.get("type") != "access":
        raise ValueError("Invalid access token type.")
    return payload