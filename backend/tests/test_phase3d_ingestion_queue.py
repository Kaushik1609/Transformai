"""Phase 3D tests for asynchronous source enqueueing."""

import uuid
from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.ingestion.queue import enqueue_source_ingestion
from app.main import app

TEST_USER_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
TEST_USER = CurrentUser(TEST_USER_ID, "phase3d@example.test", "Phase 3D", "operator")


@pytest.fixture(scope="function")
async def async_db_session() -> AsyncGenerator[AsyncSession, None]:
    import app.db.models  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture(scope="function")
def client(async_db_session, tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))

    async def override_get_db():
        yield async_db_session

    async def override_get_current_user():
        return TEST_USER

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_project(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Phase 3D"})
    assert response.status_code == 201
    return response.json()["data"]["id"]


class FakeJob:
    id = "rq-job-123"


class FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeJob()


def test_enqueue_payload_contains_only_source_id():
    queue = FakeQueue()
    source_id = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")

    job_id = enqueue_source_ingestion(source_id, queue=queue)

    assert job_id == "rq-job-123"
    args, kwargs = queue.calls[0]
    assert args == ("worker.process_source",)
    assert kwargs["source_id"] == str(source_id)
    assert set(kwargs) == {"source_id", "job_timeout", "result_ttl"}


def test_async_direct_text_returns_processing_and_stores_original(client, monkeypatch):
    queue = FakeQueue()
    monkeypatch.setattr("app.api.v1.sources.get_ingestion_queue", lambda: queue)
    project_id = create_project(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/sources/async",
        json={"text": "queued source", "language": "en"},
    )

    assert response.status_code == 202
    source = response.json()["data"]
    assert source["status"] == "processing"
    assert source["source_type"] == "text"
    assert queue.calls[0][1]["source_id"] == source["id"]


def test_async_file_returns_processing(client, monkeypatch):
    queue = FakeQueue()
    monkeypatch.setattr("app.api.v1.sources.get_ingestion_queue", lambda: queue)
    project_id = create_project(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/sources/async",
        files={"file": ("queued.txt", b"queued text", "text/plain")},
    )

    assert response.status_code == 202
    assert response.json()["data"]["status"] == "processing"


def test_async_endpoint_rejects_missing_project(client, monkeypatch):
    monkeypatch.setattr("app.api.v1.sources.get_ingestion_queue", lambda: FakeQueue())
    response = client.post(
        f"/api/v1/projects/{uuid.uuid4()}/sources/async",
        json={"text": "queued source"},
    )
    assert response.status_code == 404
