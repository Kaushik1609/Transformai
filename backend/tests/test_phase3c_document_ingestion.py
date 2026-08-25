"""Phase 3C tests for synchronous PDF and DOCX ingestion."""

import uuid
from collections.abc import AsyncGenerator, Generator

import fitz
import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.db.base import Base
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.db.session import get_db
from app.main import app

TEST_USER_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
TEST_USER = CurrentUser(
    id=TEST_USER_ID,
    email="phase3c@example.test",
    name="Phase 3C Test User",
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
    response = client.post("/api/v1/projects", json={"name": "Phase 3C"})
    assert response.status_code == 201
    return response.json()["data"]["id"]


def make_pdf(*paragraphs: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "\n".join(paragraphs))
    content = document.tobytes()
    document.close()
    return content


def make_docx(*paragraphs: str) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    output = __import__("io").BytesIO()
    document.save(output)
    return output.getvalue()


async def persisted_source(session: AsyncSession, source_id: str) -> Source:
    result = await session.execute(select(Source).where(Source.id == uuid.UUID(source_id)))
    source = result.scalar_one()
    return source


class TestPdfIngestion:
    async def test_ingests_pdf_extracts_text_stores_original_and_orders_chunks(
        self, client: TestClient, async_db_session: AsyncSession, tmp_path
    ):
        project_id = create_project(client)
        content = make_pdf("PDF first paragraph", "PDF second paragraph")
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/document",
            files={"file": ("report.pdf", content, "application/pdf")},
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["source_type"] == "pdf"
        assert data["status"] == "ready"
        assert data["original_filename"] == "report.pdf"
        assert (tmp_path / data["storage_key"]).read_bytes() == content

        source = await persisted_source(async_db_session, data["id"])
        assert "PDF first paragraph" in source.extracted_text
        assert "PDF second paragraph" in source.extracted_text
        chunks_result = await async_db_session.execute(
            select(SourceChunk)
            .where(SourceChunk.source_id == source.id)
            .order_by(SourceChunk.chunk_index.asc())
        )
        chunks = list(chunks_result.scalars().all())
        assert [chunk.chunk_index for chunk in chunks] == [0]
        assert all(chunk.embedding is None for chunk in chunks)

    def test_rejects_empty_pdf(self, client: TestClient):
        document = fitz.open()
        document.new_page()
        content = document.tobytes()
        document.close()
        project_id = create_project(client)

        response = client.post(
            f"/api/v1/projects/{project_id}/sources/document",
            files={"file": ("empty.pdf", content, "application/pdf")},
        )
        assert response.status_code == 400
        assert "usable text" in response.json()["detail"]

    def test_rejects_corrupt_pdf(self, client: TestClient):
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/document",
            files={"file": ("broken.pdf", b"not a PDF", "application/pdf")},
        )
        assert response.status_code == 400
        assert "read the PDF" in response.json()["detail"]


class TestDocxIngestion:
    async def test_ingests_docx_and_persists_extracted_text(self, client, async_db_session, tmp_path):
        project_id = create_project(client)
        content = make_docx("DOCX first paragraph", "DOCX second paragraph")
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/document",
            files={"file": ("report.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["source_type"] == "docx"
        assert data["status"] == "ready"
        assert (tmp_path / data["storage_key"]).read_bytes() == content

        source = await persisted_source(async_db_session, data["id"])
        assert source.extracted_text == "DOCX first paragraph\nDOCX second paragraph"

    def test_rejects_empty_docx(self, client: TestClient):
        content = make_docx()
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/document",
            files={"file": ("empty.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert response.status_code == 400
        assert "usable text" in response.json()["detail"]

    def test_rejects_corrupt_docx(self, client: TestClient):
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/document",
            files={"file": ("broken.docx", b"not a DOCX", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert response.status_code == 400
        assert "read the DOCX" in response.json()["detail"]


class TestDocumentValidation:
    def test_rejects_unsupported_file(self, client: TestClient):
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/document",
            files={"file": ("notes.txt", b"text", "text/plain")},
        )
        assert response.status_code == 400

    def test_rejects_oversized_file(self, client, monkeypatch):
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0)
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/document",
            files={"file": ("report.pdf", make_pdf("content"), "application/pdf")},
        )
        assert response.status_code == 400

    def test_rejects_missing_project(self, client: TestClient):
        response = client.post(
            f"/api/v1/projects/{uuid.uuid4()}/sources/document",
            files={"file": ("report.pdf", make_pdf("content"), "application/pdf")},
        )
        assert response.status_code == 404
