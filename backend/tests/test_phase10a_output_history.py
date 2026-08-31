"""Phase 10A — Project transformation history tests.

Covers GET /api/v1/projects/{project_id}/transformations:
newest-first ordering, the fields needed for history rows, ownership
enforcement, missing projects, and empty history.  Uses the existing
per-file fixture conventions (no global conftest).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.db.models.generation_configuration import GenerationConfiguration
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.main import app as fastapi_app

P10_USER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
P10_USER = CurrentUser(P10_USER_ID, "phase10a@example.test", "Phase 10A", "operator")
OTHER_USER_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
async def async_db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    import app.db.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture(scope="function")
def client(
    async_db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))

    async def override_get_db():
        yield async_db_session

    async def override_get_current_user():
        return P10_USER

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def seed_project(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Create a user + project and commit them."""
    owner_id = owner_id or P10_USER_ID
    existing = await db.execute(select(User).where(User.id == owner_id))
    if existing.scalar_one_or_none() is None:
        db.add(
            User(id=owner_id, email=f"p10-{uuid.uuid4().hex}@example.test", name="P10", role="operator")
        )
    project = Project(id=uuid.uuid4(), user_id=owner_id, name="Phase 10A")
    db.add(project)
    await db.flush()
    source = Source(
        id=uuid.uuid4(), project_id=project.id, source_type="text", status="ready",
        extracted_text="Source line one.\nSource line two.",
    )
    config = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
    db.add_all([source, config])
    await db.flush()
    return project.id


async def seed_job(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    status: str = "completed",
    output_types: list[str] | None = None,
    created_at: datetime | None = None,
    error_message: str | None = None,
    progress: int = 100,
) -> uuid.UUID:
    """Create a transformation job under a project (reuses the first source/config)."""
    source_row = await db.execute(
        select(Source).where(Source.project_id == project_id).limit(1)
    )
    config_row = await db.execute(
        select(GenerationConfiguration).where(GenerationConfiguration.project_id == project_id).limit(1)
    )
    source = source_row.scalar_one()
    config = config_row.scalar_one()
    job = TransformationJob(
        id=uuid.uuid4(),
        project_id=project_id,
        source_id=source.id,
        configuration_id=config.id,
        requested_outputs={"output_types": output_types or ["summary"]},
        status=status,
        progress=progress,
        error_message=error_message,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    return job.id


# ---------------------------------------------------------------------------
# History endpoint
# ---------------------------------------------------------------------------


async def test_list_history_newest_first(client, async_db_session):
    pid = await seed_project(async_db_session)
    older = await seed_job(
        async_db_session,
        project_id=pid,
        status="completed",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    newer = await seed_job(
        async_db_session,
        project_id=pid,
        status="failed",
        error_message="Worker job failed",
        created_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )

    resp = client.get(f"/api/v1/projects/{pid}/transformations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["count"] == 2
    ids = [row["id"] for row in body["data"]]
    assert ids == [str(newer), str(older)]


async def test_history_rows_expose_history_fields(client, async_db_session):
    pid = await seed_project(async_db_session)
    created = datetime(2024, 3, 1, tzinfo=timezone.utc)
    jid = await seed_job(
        async_db_session,
        project_id=pid,
        status="completed",
        output_types=["summary", "advisory"],
        created_at=created,
    )

    resp = client.get(f"/api/v1/projects/{pid}/transformations")
    assert resp.status_code == 200
    row = resp.json()["data"][0]
    assert row["id"] == str(jid)
    assert row["status"] == "completed"
    assert row["requested_outputs"] == {"output_types": ["summary", "advisory"]}
    assert row["progress"] == 100
    assert row["error_message"] is None
    assert row["created_at"] is not None
    assert row["started_at"] is None
    assert row["completed_at"] is None


async def test_history_includes_failure_message(client, async_db_session):
    pid = await seed_project(async_db_session)
    await seed_job(
        async_db_session,
        project_id=pid,
        status="failed",
        error_message="Canonical content is missing; cannot transform.",
    )

    resp = client.get(f"/api/v1/projects/{pid}/transformations")
    row = resp.json()["data"][0]
    assert row["status"] == "failed"
    assert "missing" in (row["error_message"] or "")


async def test_empty_history(client, async_db_session):
    pid = await seed_project(async_db_session)

    resp = client.get(f"/api/v1/projects/{pid}/transformations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["data"] == []


async def test_foreign_project_returns_404(client, async_db_session):
    fpid = await seed_project(async_db_session, owner_id=OTHER_USER_ID)
    await seed_job(async_db_session, project_id=fpid)

    resp = client.get(f"/api/v1/projects/{fpid}/transformations")
    assert resp.status_code == 404


async def test_nonexistent_project_returns_404(client):
    resp = client.get(f"/api/v1/projects/{uuid.uuid4()}/transformations")
    assert resp.status_code == 404


async def test_history_only_includes_own_project(client, async_db_session):
    pid = await seed_project(async_db_session)
    other_pid = await seed_project(async_db_session, owner_id=OTHER_USER_ID)
    await seed_job(async_db_session, project_id=pid)
    await seed_job(async_db_session, project_id=other_pid)

    resp = client.get(f"/api/v1/projects/{pid}/transformations")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1