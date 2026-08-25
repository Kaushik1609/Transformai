"""Phase 3B tests for direct-text and TXT source ingestion."""

import uuid
from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import CurrentUser, get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.core.config import settings

TEST_USER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
TEST_USER = CurrentUser(
    id=TEST_USER_ID,
    email="phase3b@example.test",
    name="Phase 3B Test User",
    role="operator",
)


@pytest.fixture(scope="session")
def model_metadata():
    import app.db.models  # noqa: F401

    return Base.metadata


@pytest.fixture(scope="function")
async def async_db_session(model_metadata) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(model_metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
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
        return TEST_USER

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_project(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Phase 3B"})
    assert response.status_code == 201
    return response.json()["data"]["id"]


class TestDirectTextIngestion:
    def test_ingests_normalized_text_and_creates_chunk(self, client: TestClient):
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/text",
            json={
                "text": "  First line\r\n\r\n\r\nSecond line  ",
                "language": "en",
                "metadata": {"origin": "test"},
            },
        )

        assert response.status_code == 201
        source = response.json()["data"]
        assert source["source_type"] == "text"
        assert source["status"] == "ready"
        assert source["storage_key"].endswith("/original.txt")
        assert source["file_size"] > 0

        stored = client.get(f"/api/v1/sources/{source['id']}")
        assert stored.status_code == 200
        assert stored.json()["data"]["status"] == "ready"

    def test_rejects_empty_direct_text(self, client: TestClient):
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/text",
            json={"text": "   \n\t"},
        )
        assert response.status_code == 400

    def test_rejects_missing_project(self, client: TestClient):
        response = client.post(
            f"/api/v1/projects/{uuid.uuid4()}/sources/text",
            json={"text": "content"},
        )
        assert response.status_code == 404


class TestTxtIngestion:
    def test_ingests_txt_file_and_stores_original(self, client: TestClient, tmp_path):
        project_id = create_project(client)
        content = b"TXT first line\r\n\r\nTXT second line"
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/file",
            files={"file": ("notes.txt", content, "text/plain")},
            data={"language": "en"},
        )

        assert response.status_code == 201
        source = response.json()["data"]
        assert source["source_type"] == "txt"
        assert source["original_filename"] == "notes.txt"
        assert source["mime_type"] == "text/plain"
        assert source["file_size"] == len(content)
        assert source["status"] == "ready"

        stored_file = tmp_path / source["storage_key"]
        assert stored_file.read_bytes() == content

    @pytest.mark.parametrize(
        ("filename", "mime_type", "content"),
        [
            ("notes.pdf", "application/pdf", b"not a pdf"),
            ("notes.txt", "application/pdf", b"plain text"),
            ("notes.txt", "text/plain", b""),
        ],
    )
    def test_rejects_invalid_txt_upload(
        self, client: TestClient, filename, mime_type, content
    ):
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/file",
            files={"file": (filename, content, mime_type)},
        )
        assert response.status_code == 400

    def test_rejects_oversized_txt_upload(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0)
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/file",
            files={"file": ("notes.txt", b"content", "text/plain")},
        )
        assert response.status_code == 400


class TestPhase2SourceCompatibility:
    def test_existing_metadata_endpoint_remains_available(self, client: TestClient):
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources",
            json={"source_type": "text", "extracted_text": "existing"},
        )
        assert response.status_code == 201
        assert response.json()["data"]["status"] == "uploaded"
