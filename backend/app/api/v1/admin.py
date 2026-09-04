"""
TransformIQ Backend — Admin API Router (Phase 11F)

Admin-only operations. Every route is guarded by ``require_admin`` which
rejects analyst/operator users with 403.

Small on purpose: L1 only needs an admin-only surface to exercise RBAC.
"""
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_admin
from app.auth.schemas import AdminUserListResponse, AdminUserSummary
from app.db.models.user import User
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    summary="List all registered users (admin only)",
)
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
) -> AdminUserListResponse:
    """Return every registered account, newest first."""
    stmt = select(User).order_by(User.created_at.desc())
    users = (await db.execute(stmt)).scalars().all()
    return AdminUserListResponse(
        data=[AdminUserSummary.model_validate(u) for u in users],
        count=len(users),
    )