"""
TransformIQ Backend — Database Session Dependency

Provides a reusable FastAPI dependency that yields an async SQLAlchemy
session and ensures it is closed (and rolled back on error) when the
request is complete.

Usage in route handlers:

    from app.db.session import get_db
    from sqlalchemy.ext.asyncio import AsyncSession
    from fastapi import Depends

    @router.get("/things")
    async def list_things(db: AsyncSession = Depends(get_db)):
        ...
"""
from collections.abc import AsyncGenerator


async def get_db() -> AsyncGenerator:
    """
    Async generator that yields a database session per request.

    The session is automatically closed after the request finishes.
    Any unhandled exception causes a rollback before closing.

    When the audit sink is the database (Phase 13D), pending security events
    emitted during the request are drained into the same transaction just
    before commit, so audit records are durable even if the endpoint returned
    before the worker would have flushed (best-effort; failures never break the
    request).

    Uses the lazy async session factory so that asyncpg is not required
    at module import time.
    """
    from app.db.engine import get_async_session_factory
    AsyncSessionLocal = get_async_session_factory()
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await _persist_pending_audit(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def _persist_pending_audit(session) -> None:
    """Drain queued database-sink audit records (never raises)."""
    try:
        from app.core.audit import drain_pending_audit_events

        await drain_pending_audit_events(session)
    except Exception:  # pragma: no cover - defensive, audit must not 500 requests
        pass
