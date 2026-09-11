"""
TransformIQ Backend — Authentication Dependencies (Phase 11F)

Phase 11F replaces the development-only identity with a real JWT-aware
``get_current_user`` while preserving backward compatibility:

- When ``DEV_AUTH_BYPASS=true`` (development only, enforced by settings) the
   stable development identity is injected, keeping the API usable without a
   token during local development.
- Otherwise a valid ``Authorization: Bearer <jwt>`` is required. The JWT is
   decoded via python-jose and the owning user record is loaded from the
   database (so a deleted user's stale token is rejected).  Tokens whose
   ``jti`` was revoked at logout are rejected too (Phase 13A).

All authentication failures surface a GENERIC 401 detail: the response never
reveals whether a token was missing, invalid, expired, or revoked (Phase 13A).
The precise reason is recorded only in the internal security-event stream.

Role-based access control:
    ``require_any_roles(*roles)`` / ``require_analyst`` / ``require_admin``

Role tiers:
    admin      — full access.
    analyst    — default role for newly registered users (Phase 11F).
    operator   — legacy development/operator tier, treated as analyst-level.

DO NOT trust client-supplied user IDs anywhere in the API.
DO NOT use the bypass in staging or production (enforced in settings).
"""
import uuid

from fastapi import Depends, HTTPException, Request, status

from app.core.audit import emit_security_event
from app.core.config import settings
from app.core.metrics import metrics
from app.core.security import decode_access_token
from app.core.token_revocation import get_revocation_store

# Stable development user identity.
# This UUID is deterministic so the dev user always has the same ID across
# test runs and Docker restarts.
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_EMAIL = "dev@transformiq.local"
DEV_USER_NAME = "Development User"
DEV_USER_ROLE = "operator"

# RBAC role constants (Phase 11F).
ROLE_ANALYST = "analyst"
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"

# Analyst-tier roles (include the legacy operator tier for backward compatibility).
ANALYST_TIERS: frozenset[str] = frozenset({ROLE_ANALYST, ROLE_OPERATOR})

_ROLE_RANK = {
    ROLE_ADMIN: 2,
    ROLE_ANALYST: 1,
    ROLE_OPERATOR: 1,
}


class CurrentUser:
    """
    Minimal representation of the authenticated user.

    Attributes:
        id: user UUID (subject of the JWT).
        email: canonical user email.
        name: display name.
        role: RBAC role (analyst | operator | admin).
    """

    def __init__(
        self,
        id: uuid.UUID,
        email: str,
        name: str,
        role: str,
    ) -> None:
        self.id = id
        self.email = email
        self.name = name
        self.role = role

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def has_at_least(self, role: str) -> bool:
        """True when this user's role rank is >= the given role's rank."""
        return _ROLE_RANK.get(self.role, 0) >= _ROLE_RANK.get(role, 0)


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "") if request else ""
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() not in {"bearer", "token"} or not credentials.strip():
        return None
    return credentials.strip()


def _unauthorized() -> HTTPException:
    """Generic 401 — never reveals whether the token was missing, invalid,
    expired, or revoked (Phase 13A)."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "Authentication required. Provide a valid Bearer access token."
        ),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _get_user_record(user_id: uuid.UUID) -> object | None:
    """Open a short-lived session and fetch the user record (read-only)."""
    from app.db.engine import get_async_session_factory
    from app.db.models.user import User

    session_factory = get_async_session_factory()
    async with session_factory() as session:
        return await session.get(User, user_id)


async def get_current_user(request: Request = None) -> CurrentUser:
    """
    FastAPI dependency — returns the current authenticated user.

    Zero-argument callable for backward compatibility:
    ``await get_current_user()`` returns the dev identity when the bypass is
    active, otherwise raises 401 (no request context to extract a token from).
    """
    if settings.DEV_AUTH_BYPASS:
        return CurrentUser(
            id=DEV_USER_ID,
            email=DEV_USER_EMAIL,
            name=DEV_USER_NAME,
            role=DEV_USER_ROLE,
        )

    if request is None:
        emit_security_event("authn_denied", outcome="denied", reason="missing_token")
        metrics.inc("authn_denials_total", {"reason": "missing_token"})
        raise _unauthorized()
    token = _extract_bearer_token(request)

    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        emit_security_event(
            "authn_denied", outcome="denied", reason="invalid_token",
            details={"error": str(exc)},
        )
        metrics.inc("authn_denials_total", {"reason": "invalid_token"})
        raise _unauthorized() from exc

    jti = payload.get("jti")
    if jti is not None:
        revoked = get_revocation_store(request).is_revoked(str(jti))
        if revoked:
            emit_security_event(
                "authn_denied", outcome="denied", reason="revoked_token",
            )
            metrics.inc("authn_denials_total", {"reason": "revoked_token"})
            raise _unauthorized()

    subject = payload.get("sub")
    if not subject:
        emit_security_event("authn_denied", outcome="denied", reason="missing_subject")
        metrics.inc("authn_denials_total", {"reason": "missing_subject"})
        raise _unauthorized()

    try:
        user_id = uuid.UUID(str(subject))
    except (ValueError, TypeError):
        emit_security_event("authn_denied", outcome="denied", reason="malformed_subject")
        metrics.inc("authn_denials_total", {"reason": "malformed_subject"})
        raise _unauthorized() from None

    user = await _get_user_record(user_id)
    if user is None:
        emit_security_event(
            "authn_denied", outcome="denied", reason="unknown_user",
            user_id=str(user_id),
        )
        metrics.inc("authn_denials_total", {"reason": "unknown_user"})
        raise _unauthorized()

    return CurrentUser(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
    )


# ---------------------------------------------------------------------------
# RBAC dependencies
# ---------------------------------------------------------------------------

def require_any_roles(*allowed_roles: str):
    """Create a dependency that only permits the given roles."""

    async def _dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed_roles:
            metrics.inc("authz_denials_total")
            emit_security_event(
                "authz_denied",
                outcome="denied",
                user_id=str(current_user.id),
                reason=(
                    f"role '{current_user.role}' not in allowed roles "
                    f"{sorted(allowed_roles)}"
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Insufficient permissions. Your role requires elevated "
                    "access to perform this operation."
                ),
            )
        return current_user

    return _dependency


require_analyst = require_any_roles(ROLE_ADMIN, ROLE_ANALYST, ROLE_OPERATOR)
require_admin = require_any_roles(ROLE_ADMIN)