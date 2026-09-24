"""Phase 10B — Output DOCX/PDF export tests.

Covers POST /api/v1/outputs/{output_id}/export:
DOCX/PDF bytes for summary/advisory outputs, filenames, content types,
ownership enforcement, status gating, unsupported output types, invalid
formats, and missing structured content.  Uses the existing per-file
fixture conventions (no global conftest).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Generator
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
from app.db.models.output import Output
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.main import app as fastapi_app
from app.transformation.output_schemas import Advisory, ExecutiveSummary
from app.transformation.render.docx import DOCX_MIME_TYPE
from app.transformation.render.pdf import PDF_MIME_TYPE

P10B_USER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
P10B_USER = CurrentUser(P10B_USER_ID, "phase10b@example.test", "Phase 10B", "operator")
OTHER_USER_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")

SUMMARY_CONTENT = {
    "type": "summary",
    "title": "Quarterly Cyber Threat Report",
    "summary": "Ransomware activity rose 37% in Q1.",
    "key_findings": ["37% rise in ransomware"],
    "text": "# Executive Summary: Quarterly\n\nRansomware rose 37%.",
}

ADVISORY_CONTENT = {
    "type": "advisory",
    "title": "Advisory: Elevated Ransomware Risk",
    "situation": "Organizations face elevated ransomware risk.",
    "key_findings": ["37% rise in ransomware"],
    "text": "# Advisory\n\n## Situation\nElevated risk.",
}


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
        return P10B_USER

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def seed_output(
    db: AsyncSession,
    *,
    output_type: str,
    status: str = "completed",
    structured_content: dict[str, Any] | None = None,
    owner_id: uuid.UUID | None = None,
    classification: str = "PUBLIC",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed a project/source/config/job/output chain and commit it."""
    owner_id = owner_id or P10B_USER_ID
    existing = await db.execute(select(User).where(User.id == owner_id))
    if existing.scalar_one_or_none() is None:
        db.add(
            User(id=owner_id, email=f"p10b-{uuid.uuid4().hex}@example.test", name="P10B", role="operator")
        )
    project = Project(id=uuid.uuid4(), user_id=owner_id, name="Phase 10B")
    db.add(project)
    source = Source(
        id=uuid.uuid4(), project_id=project.id, source_type="text", status="ready",
        extracted_text="Source line one.\nSource line two.",
        source_metadata={"classification": classification},
    )
    config = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
    db.add_all([source, config])
    job = TransformationJob(
        id=uuid.uuid4(), project_id=project.id, source_id=source.id,
        configuration_id=config.id,
        requested_outputs={"output_types": [output_type]}, status="completed",
    )
    db.add(job)
    output_id = uuid.uuid4()
    db.add(
        Output(
            id=output_id, job_id=job.id, output_type=output_type, status=status,
            structured_content=structured_content,
            text_content=(
                (structured_content or {}).get("text")
                if structured_content else None
            ),
            mime_type="text/plain",
        )
    )
    await db.commit()
    return project.id, job.id, output_id


def disposition(resp) -> str:
    """Return the quoted filename from an attachment Content-Disposition header."""
    header = resp.headers["content-disposition"]
    assert header.startswith("attachment; filename=\"")
    return header.rpartition('filename="')[2].rstrip('"')


# ---------------------------------------------------------------------------
# Docx export
# ---------------------------------------------------------------------------


async def test_export_summary_docx(client, async_db_session):
    _, _, oid = await seed_output(
        async_db_session, output_type="summary", structured_content=SUMMARY_CONTENT
    )

    resp = client.post(f"/api/v1/outputs/{oid}/export?format=docx")
    assert resp.status_code == 200
    assert resp.content.startswith(b"PK")  # DOCX is a zip archive
    assert resp.headers["content-type"] == DOCX_MIME_TYPE
    assert disposition(resp) == "summary.docx"


async def test_export_advisory_docx(client, async_db_session):
    _, _, oid = await seed_output(
        async_db_session, output_type="advisory", structured_content=ADVISORY_CONTENT
    )

    resp = client.post(f"/api/v1/outputs/{oid}/export?format=docx")
    assert resp.status_code == 200
    assert resp.content.startswith(b"PK")
    assert resp.headers["content-type"] == DOCX_MIME_TYPE
    assert disposition(resp) == "advisory.docx"


async def test_export_docx_defaults_to_empty_format_ok(client, async_db_session):
    """The endpoint requires an explicit format; calling without one uses pdf."""
    _, _, oid = await seed_output(
        async_db_session, output_type="summary", structured_content=SUMMARY_CONTENT
    )

    resp = client.post(f"/api/v1/outputs/{oid}/export")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Pdf export
# ---------------------------------------------------------------------------


async def test_export_summary_pdf(client, async_db_session):
    _, _, oid = await seed_output(
        async_db_session, output_type="summary", structured_content=SUMMARY_CONTENT
    )

    resp = client.post(f"/api/v1/outputs/{oid}/export?format=pdf")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
    assert resp.headers["content-type"] == PDF_MIME_TYPE
    assert disposition(resp) == "summary.pdf"


async def test_export_advisory_pdf(client, async_db_session):
    _, _, oid = await seed_output(
        async_db_session, output_type="advisory", structured_content=ADVISORY_CONTENT
    )

    resp = client.post(f"/api/v1/outputs/{oid}/export?format=pdf")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
    assert resp.headers["content-type"] == PDF_MIME_TYPE
    assert disposition(resp) == "advisory.pdf"


# ---------------------------------------------------------------------------
# Security / ownership
# ---------------------------------------------------------------------------


async def test_foreign_user_export_returns_404(client, async_db_session):
    _, _, oid = await seed_output(
        async_db_session, owner_id=OTHER_USER_ID,
        output_type="summary", structured_content=SUMMARY_CONTENT,
    )

    resp = client.post(f"/api/v1/outputs/{oid}/export?format=pdf")
    assert resp.status_code == 404


async def test_nonexistent_output_returns_404(client):
    resp = client.post(f"/api/v1/outputs/{uuid.uuid4()}/export?format=pdf")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Status gating
# ---------------------------------------------------------------------------


async def test_generating_output_returns_409(client, async_db_session):
    _, _, oid = await seed_output(
        async_db_session, output_type="summary", status="generating",
        structured_content=SUMMARY_CONTENT,
    )

    resp = client.post(f"/api/v1/outputs/{oid}/export?format=pdf")
    assert resp.status_code == 409


async def test_failed_output_returns_404(client, async_db_session):
    _, _, oid = await seed_output(
        async_db_session, output_type="summary", status="failed",
        structured_content=SUMMARY_CONTENT,
    )

    resp = client.post(f"/api/v1/outputs/{oid}/export?format=pdf")
    assert resp.status_code == 404


async def test_missing_structured_content_returns_404(client, async_db_session):
    _, _, oid = await seed_output(async_db_session, output_type="summary")

    resp = client.post(f"/api/v1/outputs/{oid}/export?format=pdf")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Unsupported output types / formats
# ---------------------------------------------------------------------------


async def test_export_presentation_returns_422(client, async_db_session):
    _, _, oid = await seed_output(async_db_session, output_type="presentation")

    resp = client.post(f"/api/v1/outputs/{oid}/export?format=pdf")
    assert resp.status_code == 422


async def test_export_invalid_format_returns_422(client, async_db_session):
    _, _, oid = await seed_output(
        async_db_session, output_type="summary", structured_content=SUMMARY_CONTENT
    )

    resp = client.post(f"/api/v1/outputs/{oid}/export?format=srt")
    assert resp.status_code == 422


async def test_export_invalid_structured_content_returns_422(client, async_db_session):
    _, _, oid = await seed_output(
        async_db_session, output_type="summary",
        structured_content={"unexpected": "shape"},
    )

    resp = client.post(f"/api/v1/outputs/{oid}/export?format=pdf")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Schema sanity: the render inputs are the persisted structured content
# ---------------------------------------------------------------------------


def test_seed_content_validates_against_schemas():
    ExecutiveSummary.model_validate(SUMMARY_CONTENT)
    Advisory.model_validate(ADVISORY_CONTENT)