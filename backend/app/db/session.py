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

    Uses the lazy async session factory so that asyncpg is not required
    at module import time.
    """
    from app.db.engine import get_async_session_factory
    AsyncSessionLocal = get_async_session_factory()
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
