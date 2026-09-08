"""Phase 12C tests for the content-level PII scan (source ingestion audit gap).

The Phase 11K PII engine (``app.core.pii``) is now surfaced on the content
pipeline: normalized source text is scanned at ingestion and the per-category
counts are recorded in ``source_metadata["pii_scan"]`` plus a ``pii_detected``
security event.  These tests verify the new control end-to-end.
"""

import uuid
from collections.abc import AsyncGenerator, Generator

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import CurrentUser, get_current_user
from app.core.audit import clear_security_events, security_events
from app.core.config import settings
from app.db.base import Base
from app.db.models.project import Project
from app.db.session import get_db
from app.ingestion.pii_scan import EVENT_TYPE, META_KEY, scan_source_pii
from app.main import app

TEST_USER_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccc0c")
TEST_USER = CurrentUser(
    id=TEST_USER_ID,
    email="phase12c@example.test",
    name="Phase 12C Test User",
    role="operator",
)

PLAIN_TEXT = "This is a normal government memo about procurement with no personal data."
PII_TEXT = (
    "Contact john.doe@example.com or 555-123-4567 for the review. "
    "Server at 192.168.1.1 holds the card 4111111111111111."
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
    clear_security_events()

    async def override_get_db():
        yield async_db_session

    async def override_get_current_user():
        return TEST_USER

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    clear_security_events()


def create_project(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Phase 12C"})
    assert response.status_code == 201
    return response.json()["data"]["id"]


def make_pdf(*paragraphs: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "\n".join(paragraphs))
    content = document.tobytes()
    document.close()
    return content


def events_with_type() -> list[dict]:
    return [e for e in security_events() if e.get("event_type") == EVENT_TYPE]


class TestScanSourcePiiUnit:
    def test_plain_text_no_pii(self) -> None:
        result = scan_source_pii(PLAIN_TEXT)
        assert result["detected"] is False
        assert result["counts"] == {}
        assert META_KEY not in result

    def test_none_and_empty(self) -> None:
        assert scan_source_pii(None)["detected"] is False
        assert scan_source_pii("")["detected"] is False

    def test_detects_email(self) -> None:
        result = scan_source_pii("reach john.doe@example.com today")
        assert result["detected"] is True
        assert result["counts"].get("email") == 1

    def test_detects_phone(self) -> None:
        result = scan_source_pii("call 555-123-4567 now")
        assert result["detected"] is True
        assert result["counts"].get("phone", 0) >= 1

    def test_detects_ipv4(self) -> None:
        result = scan_source_pii("host 192.168.1.1 is internal")
        assert result["detected"] is True
        assert result["counts"].get("ipv4") == 1

    def test_detects_credit_card_luhn(self) -> None:
        result = scan_source_pii("card 4111111111111111 on file")
        assert result["detected"] is True
        assert result["counts"].get("credit_card") == 1

    def test_summary_never_contains_raw_values(self) -> None:
        raw = "email a@example.com phone 555-123-4567 ip 192.168.1.1 card 4111111111111111"
        result = scan_source_pii(raw)
        import json

        dump = json.dumps(result)
        for secret in ("a@example.com", "555-123-4567", "192.168.1.1", "4111111111111111"):
            assert secret not in dump


class TestTextSourcePiiScan:
    def test_plain_text_no_scan_and_no_event(self, client: TestClient) -> None:
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/file",
            files={"file": ("memo.txt", PLAIN_TEXT.encode("utf-8"), "text/plain")},
        )
        assert response.status_code == 201
        source_metadata = response.json()["data"].get("source_metadata") or {}
        assert "pii_scan" not in source_metadata
        assert events_with_type() == []

    def test_pii_text_records_scan_and_event(self, client: TestClient) -> None:
        project_id = create_project(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/file",
            files={"file": ("contact.txt", PII_TEXT.encode("utf-8"), "text/plain")},
        )
        assert response.status_code == 201
        body = response.json()["data"]
        source_metadata = body.get("source_metadata") or {}
        pii_scan = source_metadata.get("pii_scan")
        assert pii_scan is not None
        assert pii_scan["detected"] is True
        assert pii_scan["counts"].get("email", 0) >= 1

        events = events_with_type()
        assert any(e["reason"] == "pii_detected_in_source" for e in events)
        assert events[0]["categories"] == list(pii_scan["counts"].keys())

    def test_event_has_no_raw_pii(self, client: TestClient) -> None:
        project_id = create_project(client)
        client.post(
            f"/api/v1/projects/{project_id}/sources/file",
            files={"file": ("contact.txt", PII_TEXT.encode("utf-8"), "text/plain")},
        )
        import json

        dump = json.dumps(events_with_type())
        for secret in ("john.doe@example.com", "555-123-4567", "4111111111111111"):
            assert secret not in dump


class TestDocumentSourcePiiScan:
    def test_pdf_pii_recorded_and_event_emitted(self, client: TestClient) -> None:
        project_id = create_project(client)
        pdf_bytes = make_pdf("Report on john.doe@example.com account")
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/document",
            files={"file": ("pii.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 201
        source_metadata = response.json()["data"].get("source_metadata") or {}
        pii_scan = source_metadata.get("pii_scan")
        assert pii_scan is not None
        assert pii_scan["detected"] is True
        assert pii_scan["counts"].get("email") == 1
        assert events_with_type()

    def test_pdf_plain_records_no_scan(self, client: TestClient) -> None:
        project_id = create_project(client)
        pdf_bytes = make_pdf("Standard quarterly procurement summary with no PII.")
        response = client.post(
            f"/api/v1/projects/{project_id}/sources/document",
            files={"file": ("plain.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 201
        source_metadata = response.json()["data"].get("source_metadata") or {}
        assert "pii_scan" not in source_metadata
        assert events_with_type() == []


class TestOriginalContentPreserved:
    async def test_document_text_and_status_preserved(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services import source_service

        project = Project(
            id=uuid.uuid4(),
            user_id=TEST_USER_ID,
            name="Phase 12C Preserve",
        )
        async_db_session.add(project)
        await async_db_session.flush()

        pdf_bytes = make_pdf("Report on john.doe@example.com account")
        source = await source_service.ingest_document_source(
            async_db_session,
            project_id=project.id,
            content=pdf_bytes,
            source_type="pdf",
            filename="preserve.pdf",
            mime_type="application/pdf",
            language="en",
        )
        assert source.status == "ready"
        assert "john.doe@example.com" in (source.extracted_text or "")
        source_metadata = dict(source.source_metadata or {})
        assert source_metadata["pii_scan"]["detected"] is True
        assert source_metadata["pii_scan"]["counts"].get("email") == 1
