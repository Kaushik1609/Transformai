"""
TransformIQ Backend — Database Engine

Creates async and sync SQLAlchemy engines from application settings.
Async engine is used by FastAPI route handlers via dependency injection.
Sync engine is used by Alembic migrations and synchronous utilities.

Both engines are created lazily on first use so that:
1. The module can be safely imported without live database connections.
2. asyncpg is not required at import time (no Windows/Python 3.13 binary).
3. Tests can patch get_db before the engine is ever created.

Rules:
- Never hard-code connection strings here.
- Never expose credentials.
- Connections are pooled and recycled automatically.
"""
from __future__ import annotations

_sync_engine = None
_async_engine = None
_AsyncSessionLocal = None


# ---------------------------------------------------------------------------
# Sync engine — psycopg2-based (used by Alembic)
# ---------------------------------------------------------------------------

def get_sync_engine():
    """Return the sync SQLAlchemy engine, creating it on first call."""
    global _sync_engine
    if _sync_engine is None:
        from sqlalchemy import create_engine
        from app.core.config import settings

        url = settings.DATABASE_SYNC_URL
        if url.startswith("postgresql+asyncpg://"):
            url = "postgresql://" + url[len("postgresql+asyncpg://") :]
        elif url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]

        _sync_engine = create_engine(
            url,
            echo=settings.ENVIRONMENT == "development",
            pool_pre_ping=True,
        )
    return _sync_engine


# ---------------------------------------------------------------------------
# Async engine + session factory — asyncpg-based (used by FastAPI)
# ---------------------------------------------------------------------------

def get_async_engine():
    """Return the async SQLAlchemy engine, creating it on first call."""
    global _async_engine
    if _async_engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine
        from app.core.config import settings

        url = settings.DATABASE_URL
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://") :]
        elif url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://") :]

        _async_engine = create_async_engine(
            url,
            echo=settings.ENVIRONMENT == "development",
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _async_engine


def get_async_session_factory():
    """Return the async sessionmaker, creating it on first call."""
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker
        _AsyncSessionLocal = sessionmaker(
            bind=get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _AsyncSessionLocal


# ---------------------------------------------------------------------------
# Lazy proxy objects — importable as module-level names
# ---------------------------------------------------------------------------

class _LazyProxy:
    """Generic lazy proxy that delegates attribute access to a factory result."""

    def __init__(self, factory):
        object.__setattr__(self, "_factory", factory)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_factory")(), name)

    def __call__(self, *args, **kwargs):
        return object.__getattribute__(self, "_factory")()(*args, **kwargs)


# These names are importable as before; construction is deferred until
# the first attribute access or call.
sync_engine = _LazyProxy(get_sync_engine)
async_engine = _LazyProxy(get_async_engine)
AsyncSessionLocal = _LazyProxy(get_async_session_factory)
