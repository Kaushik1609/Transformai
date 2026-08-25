"""
TransformIQ Backend — Development Auth Dependency

Phase 2 maintains the development-only authorization boundary established
in Phase 1. When DEV_AUTH_BYPASS=true (the default for local development),
a fixed development user identity is injected so that the API is usable
without a real JWT.

The database ownership model is still respected:
  - Every project is associated with a user_id.
  - The dev user has a stable UUID that persists in the database.
  - When real authentication is added (Phase 2 extension or Phase 3),
    this module is replaced with a real JWT dependency.

DO NOT trust client-supplied user IDs anywhere in the API.
DO NOT use this bypass in staging or production (enforced in settings).
"""
import uuid

from fastapi import Depends, HTTPException, status

from app.core.config import settings

# Stable development user identity.
# This UUID is deterministic so the dev user always has the same ID across
# test runs and Docker restarts.
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_EMAIL = "dev@transformiq.local"
DEV_USER_NAME = "Development User"
DEV_USER_ROLE = "operator"


class CurrentUser:
    """
    Minimal representation of the authenticated user for Phase 2.
    Expanded when real auth is added.
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


async def get_current_user() -> CurrentUser:
    """
    FastAPI dependency — returns the current authenticated user.

    Phase 2: When DEV_AUTH_BYPASS=true, returns a stable dev identity.
    When false, raises 401 (real auth not implemented yet).
    """
    if settings.DEV_AUTH_BYPASS:
        return CurrentUser(
            id=DEV_USER_ID,
            email=DEV_USER_EMAIL,
            name=DEV_USER_NAME,
            role=DEV_USER_ROLE,
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is required. Set DEV_AUTH_BYPASS=true for development.",
    )
