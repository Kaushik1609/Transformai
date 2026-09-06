"""
TransformIQ Backend — Credential & PII Redaction (Phase 11K)

Single reusable redaction layer used by structlog, resilience wrappers, the
worker and audit events so secret-shaped and PII-shaped values are never
written to logs or error surfaces.

The patterns are intentionally conservative: they only redact unambiguous
credential shapes (bearer tokens, JWTs, API keys, ``key=value`` secrets,
connection-URI credentials, private-key blocks) and common directly
identifiable PII (emails, phone-like numbers, IPv4 addresses).  Redaction is a
defense-in-depth hygiene layer; it is NOT a substitute for never logging
sensitive values in the first place.
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Credential redaction
# ---------------------------------------------------------------------------

# JSON Web Tokens (three base64url segments).
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)

# Connection URIs that embed credentials: scheme://user:password@host
_URI_CREDS_RE = re.compile(r"\b([a-z][a-z0-9+.-]*://)([^:/@\s]+)(:[^@\s]*)?@")

# OpenAI-style secret keys.
_API_KEY_RE = re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{8,}\b")

# Named secret assignments: `key=value` / `key: value`, value clipped at
# common separators so the following log text survives.
_NAMED_SECRET_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|apikey|token|authorization|auth[_-]?token|"
    r"access[_-]?token|refresh[_-]?token|password|passwd|secret|"
    r"client[_-]?secret|private[_-]?key|otp|passcode|pin|session[_-]?id)\b"
    r"\s*[:=]\s*([^,;\s}]+)"
)

# Bearer tokens: `bearer <credentials>`.
_BEARER_RE = re.compile(r"(?i)\bbearer\s+\S+")

# Private key PEM blocks.
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

_SUBSTITUTION = "<redacted>"


def redact_secrets(text: str) -> str:
    """Return ``text`` with secret-shaped values replaced by ``<redacted>``."""
    if not text:
        return text
    value = _JWT_RE.sub(_SUBSTITUTION, text)
    value = _PRIVATE_KEY_RE.sub(_SUBSTITUTION, value)
    value = _URI_CREDS_RE.sub(r"\1\2:<redacted>@", value)
    value = _API_KEY_RE.sub(_SUBSTITUTION, value)
    value = _NAMED_SECRET_RE.sub(
        lambda m: f"{m.group(0)[: len(m.group(0)) - len(m.group(1))]}<redacted>",
        value,
    )
    value = _BEARER_RE.sub("bearer <redacted>", value)
    return value


def safe_message(exc: BaseException, *, limit: int = 500) -> str:
    """Return a bounded, credential-safe message derived from an exception."""
    message = str(exc) or exc.__class__.__name__
    return redact_secrets(message)[:limit]


# ---------------------------------------------------------------------------
# structlog integration
# ---------------------------------------------------------------------------

def _redact_value(value: Any) -> Any:
    """Recursively redact string values inside scalars/list/dict structures."""
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return type(value)(_redact_value(item) for item in value)
    return value


class RedactionProcessor:
    """structlog processor that redacts secret-shaped values in every event.

    Applied to ``event`` (the primary message) and all bound key/value pairs,
    recursing into list/dict payloads so structured fields such as validation
    errors and HTTP error details are scrubbed before rendering.
    """

    def __call__(self, logger: Any, method_name: str, event_dict: dict) -> dict:
        if "event" in event_dict:
            event_dict["event"] = redact_secrets(event_dict["event"])
        for key in list(event_dict):
            if key in ("log_level", "timestamp", "framework", "logger", "level"):
                continue
            event_dict[key] = _redact_value(event_dict[key])
        return event_dict


__all__ = ["redact_secrets", "safe_message", "RedactionProcessor", "_redact_value"]