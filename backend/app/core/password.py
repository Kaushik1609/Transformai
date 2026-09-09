"""
TransformIQ Backend — Password hashing (Phase 15)

Standard-library-only PBKDF2-HMAC-SHA256 password hashing.  No third-party
dependency (the project deliberately avoids passlib/bcrypt).  Design:

- Per-user random salt via ``secrets``.
- ``pbkdf2_hmac`` with a high iteration count for meaningful work.
- Constant-time comparison via ``hmac.compare_digest``.
- Self-describing storage format:
      ``pbkdf2_sha256$<iterations>$<salt_b64>$<digest_b64>``
  so iteration counts can be raised in the future while old hashes stay
  verifiable.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PBKDF2_ITERATIONS = 310_000
_ALGORITHM = "pbkdf2_sha256"
_SALT_BYTES = 16
_HASH_BYTES = 32


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def hash_password(password: str) -> str:
    """Hash a plaintext password into the self-describing storage format."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=_HASH_BYTES,
    )
    return "$".join(
        (_ALGORITHM, str(PBKDF2_ITERATIONS), _b64encode(salt), _b64encode(digest))
    )


def verify_password(password: str, stored: str) -> bool:
    """Verify ``password`` against a stored hash (constant-time comparison).

    Malformed/unknown-format hashes fail closed.
    """
    if not stored or not password:
        return False
    try:
        algorithm, iterations_str, salt_b64, digest_b64 = stored.split("$", 3)
        if algorithm != _ALGORITHM:
            return False
        iterations = int(iterations_str)
        if iterations <= 0:
            return False
        salt = _b64decode(salt_b64)
        expected = _b64decode(digest_b64)
    except (
        ValueError,
        base64.binascii.Error,
        TypeError,
        OverflowError,
    ):
        return False

    if not salt or not expected:
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)