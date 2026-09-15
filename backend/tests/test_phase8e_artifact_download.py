"""Phase 8E — Artifact download/access tests.

Covers the authenticated, server-resolved artifact download endpoint:
primary and companion artifacts, ownership enforcement, status gating,
missing resources, role validation, text-only outputs, and storage-path
traversal protection.  Uses the existing per-file fixture conventions (no
global conftest).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
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
from app.ingestion.storage import LocalStorage
from app.main import app as fastapi_app
from app.transformation.artifacts import output_storage_key
from app.transformation.render.pdf import PDF_MIME_TYPE
from app.transformation.render.pptx import PPTX_MIME_TYPE

P8E_USER_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
P8E_USER = CurrentUser(P8E_USER_ID, "phase8e@example.test", "Phase 8E", "operator")
OTHER_USER_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")

PNG_MIME_TYPE = "image/png"
SRT_MIME_TYPE = "application/x-subrip"


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
        return P8E_USER

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
    storage_key: str | None = None,
    mime_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    owner_id: uuid.UUID | None = None,
    derive_key: bool = True,
    classification: str = "PUBLIC",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed a project/source/config/job/output chain and commit it.

    When ``derive_key`` is true (and the caller supplied no explicit key), the
    output's storage key is auto-computed from the approved key scheme.
    """
    owner_id = owner_id or P8E_USER_ID
    from sqlalchemy import select

    existing = await db.execute(select(User).where(User.id == owner_id))
    if existing.scalar_one_or_none() is None:
        db.add(
            User(id=owner_id, email=f"p8e-{uuid.uuid4().hex}@example.test", name="P8E", role="operator")
        )
    project = Project(id=uuid.uuid4(), user_id=owner_id, name="Phase 8E")
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
    if storage_key is None and derive_key and mime_type:
        storage_key = output_storage_key(project.id, job.id, output_id, mime_type)
    db.add(
        Output(
            id=output_id, job_id=job.id, output_type=output_type, status=status,
            storage_key=storage_key, mime_type=mime_type, output_metadata=metadata,
        )
    )
    await db.commit()
    return project.id, job.id, output_id


async def set_output_metadata(db: AsyncSession, output_id: uuid.UUID, metadata: dict[str, Any]) -> None:
    """Point an output's companion metadata at explicit storage keys."""
    await db.execute(
        update(Output).where(Output.id == output_id).values(output_metadata=metadata)
    )
    await db.commit()


def write_artifact(
    root, project_id: uuid.UUID, job_id: uuid.UUID, output_id: uuid.UUID,
    mime_type: str, content: bytes,
) -> None:
    """Persist artifact bytes under the approved output key for these ids."""
    LocalStorage(str(root)).save(output_storage_key(project_id, job_id, output_id, mime_type), content)


def write_bytes(root, key: str, content: bytes) -> None:
    """Persist artifact bytes under an explicit storage key."""
    LocalStorage(str(root)).save(key, content)


def disposition(resp) -> str:
    """Return the quoted filename from an attachment Content-Disposition header."""
    header = resp.headers["content-disposition"]
    assert header.startswith("attachment; filename=\"")
    return header.rpartition('filename="')[2].rstrip('"')


# ---------------------------------------------------------------------------
# Primary artifacts
# ---------------------------------------------------------------------------


async def test_download_presentation_pptx_primary(tmp_path, client, async_db_session):
    content = b"fake-pptx-bytes"
    pid, jid, oid = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE)
    write_artifact(tmp_path, pid, jid, oid, PPTX_MIME_TYPE, content)

    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 200
    assert resp.content == content
    assert resp.headers["content-type"] == PPTX_MIME_TYPE
    assert disposition(resp) == "presentation.pptx"


async def test_download_infographic_png_primary(tmp_path, client, async_db_session):
    content = b"\x89PNG\r\n\x1a\nfake-png-bytes"
    pid, jid, oid = await seed_output(async_db_session, output_type="infographic", mime_type=PNG_MIME_TYPE)
    write_artifact(tmp_path, pid, jid, oid, PNG_MIME_TYPE, content)

    resp = client.get(f"/api/v1/outputs/{oid}/download?artifact=primary")
    assert resp.status_code == 200
    assert resp.content == content
    assert resp.headers["content-type"] == PNG_MIME_TYPE
    assert disposition(resp) == "infographic.png"


async def test_download_video_pdf_primary(tmp_path, client, async_db_session):
    content = b"%PDF-fake-video-package-bytes"
    pid, jid, oid = await seed_output(async_db_session, output_type="video", mime_type=PDF_MIME_TYPE)
    write_artifact(tmp_path, pid, jid, oid, PDF_MIME_TYPE, content)

    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 200
    assert resp.content == content
    assert resp.headers["content-type"] == PDF_MIME_TYPE
    assert disposition(resp) == "video.pdf"


async def test_default_artifact_role_is_primary(tmp_path, client, async_db_session):
    content = b"default-primary-bytes"
    pid, jid, oid = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE)
    write_artifact(tmp_path, pid, jid, oid, PPTX_MIME_TYPE, content)

    resp = client.get(f"/api/v1/outputs/{oid}/download?artifact=primary")
    assert resp.status_code == 200
    assert resp.content == content


# ---------------------------------------------------------------------------
# Companion artifacts
# ---------------------------------------------------------------------------


async def test_download_infographic_pdf_companion(tmp_path, client, async_db_session):
    png = b"\x89PNG\r\n\x1a\nfake-png"
    pdf = b"%PDF-fake-infographic-printable"
    pid, jid, oid = await seed_output(async_db_session, output_type="infographic", mime_type=PNG_MIME_TYPE)
    write_artifact(tmp_path, pid, jid, oid, PNG_MIME_TYPE, png)
    pdf_key = output_storage_key(pid, jid, oid, PDF_MIME_TYPE)
    write_bytes(tmp_path, pdf_key, pdf)
    await set_output_metadata(async_db_session, oid, {"pdf_storage_key": pdf_key})

    resp = client.get(f"/api/v1/outputs/{oid}/download?artifact=pdf")
    assert resp.status_code == 200
    assert resp.content == pdf
    assert resp.headers["content-type"] == PDF_MIME_TYPE
    assert disposition(resp) == "infographic.pdf"


async def test_download_video_srt_companion(tmp_path, client, async_db_session):
    video = b"%PDF-fake-video-package"
    srt = b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"
    pid, jid, oid = await seed_output(async_db_session, output_type="video", mime_type=PDF_MIME_TYPE)
    write_artifact(tmp_path, pid, jid, oid, PDF_MIME_TYPE, video)
    srt_key = output_storage_key(pid, jid, oid, SRT_MIME_TYPE)
    write_bytes(tmp_path, srt_key, srt)
    await set_output_metadata(async_db_session, oid, {"subtitle_storage_key": srt_key})

    resp = client.get(f"/api/v1/outputs/{oid}/download?artifact=srt")
    assert resp.status_code == 200
    assert resp.content == srt
    assert resp.headers["content-type"] == SRT_MIME_TYPE
    assert disposition(resp) == "video_subtitles.srt"


# ---------------------------------------------------------------------------
# Security / ownership
# ---------------------------------------------------------------------------


async def test_foreign_user_output_returns_404(tmp_path, client, async_db_session):
    content = b"foreign-artifact"
    pid, jid, oid = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE, owner_id=OTHER_USER_ID)
    write_artifact(tmp_path, pid, jid, oid, PPTX_MIME_TYPE, content)

    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 404
    assert b"foreign-artifact" not in resp.content


async def test_cross_project_output_denied(tmp_path, client, async_db_session):
    owned = b"owned-artifact"
    opp, ojid, ooid = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE)
    write_artifact(tmp_path, opp, ojid, ooid, PPTX_MIME_TYPE, owned)
    fpid, fjid, foid = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE, owner_id=OTHER_USER_ID)
    write_artifact(tmp_path, fpid, fjid, foid, PPTX_MIME_TYPE, b"foreign")

    assert client.get(f"/api/v1/outputs/{ooid}/download").status_code == 200
    resp = client.get(f"/api/v1/outputs/{foid}/download")
    assert resp.status_code == 404
    assert b"foreign" not in resp.content


async def test_same_user_other_project_can_download(tmp_path, client, async_db_session):
    a = b"project-a"
    b = b"project-b"
    pa, ja, oa = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE)
    write_artifact(tmp_path, pa, ja, oa, PPTX_MIME_TYPE, a)
    pb, jb, ob = await seed_output(async_db_session, output_type="video", mime_type=PDF_MIME_TYPE)
    write_artifact(tmp_path, pb, jb, ob, PDF_MIME_TYPE, b)

    assert client.get(f"/api/v1/outputs/{oa}/download").content == a
    assert client.get(f"/api/v1/outputs/{ob}/download").content == b


async def test_client_supplied_storage_key_is_ignored(tmp_path, client, async_db_session):
    real = b"REAL-ARTIFACT"
    pid, jid, oid = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE)
    write_artifact(tmp_path, pid, jid, oid, PPTX_MIME_TYPE, real)
    write_bytes(tmp_path, "projects/decoy/result.txt", b"DECOY-ARTIFACT")

    resp = client.get(f"/api/v1/outputs/{oid}/download?artifact=primary&storage_key=projects%2Fdecoy%2Fresult.txt")
    assert resp.status_code == 200
    assert resp.content == real


async def test_invalid_artifact_role_returns_422(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE)
    write_artifact(tmp_path, pid, jid, oid, PPTX_MIME_TYPE, b"x")

    resp = client.get(f"/api/v1/outputs/{oid}/download?artifact=docx")
    assert resp.status_code == 422
    resp = client.get(f"/api/v1/outputs/{oid}/download?artifact=png")
    assert resp.status_code == 422


async def test_path_traversal_role_returns_422(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE)
    write_artifact(tmp_path, pid, jid, oid, PPTX_MIME_TYPE, b"x")

    resp = client.get(f"/api/v1/outputs/{oid}/download", params={"artifact": "../../etc/passwd"})
    assert resp.status_code == 422


async def test_escaped_storage_key_returns_404(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(
        async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE,
        storage_key="../escape-e2e", derive_key=False,
    )
    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 404
    assert not (tmp_path.parent / "escape-e2e").exists()


def test_storage_root_traversal_protected(tmp_path):
    storage = LocalStorage(str(tmp_path))
    with pytest.raises(ValueError):
        storage.save("../escape", b"x")
    with pytest.raises(ValueError):
        storage.read("../escape")


# ---------------------------------------------------------------------------
# Status gating
# ---------------------------------------------------------------------------


async def test_generating_output_returns_409(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE, status="generating")
    write_artifact(tmp_path, pid, jid, oid, PPTX_MIME_TYPE, b"partial")

    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 409


async def test_failed_output_returns_404(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE, status="failed")
    write_artifact(tmp_path, pid, jid, oid, PPTX_MIME_TYPE, b"partial")

    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 404


async def test_cancelled_output_returns_404(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE, status="cancelled")
    write_artifact(tmp_path, pid, jid, oid, PPTX_MIME_TYPE, b"partial")

    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 404


async def test_generating_output_of_foreign_user_returns_404(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(
        async_db_session, output_type="presentation", mime_type=PPTX_MIME_TYPE,
        status="generating", owner_id=OTHER_USER_ID,
    )

    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Missing resources
# ---------------------------------------------------------------------------


def test_nonexistent_output_returns_404(client):
    resp = client.get(f"/api/v1/outputs/{uuid.uuid4()}/download")
    assert resp.status_code == 404


async def test_missing_primary_storage_key_returns_404(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(async_db_session, output_type="infographic", mime_type=PNG_MIME_TYPE, derive_key=False)

    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 404


async def test_missing_file_on_disk_returns_404(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(async_db_session, output_type="video", mime_type=PDF_MIME_TYPE)

    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 404


async def test_missing_companion_metadata_returns_404(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(async_db_session, output_type="infographic", mime_type=PNG_MIME_TYPE)
    write_artifact(tmp_path, pid, jid, oid, PNG_MIME_TYPE, b"\x89PNG\r\n\x1a\n")

    resp = client.get(f"/api/v1/outputs/{oid}/download?artifact=pdf")
    assert resp.status_code == 404


async def test_missing_companion_file_returns_404(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(async_db_session, output_type="video", mime_type=PDF_MIME_TYPE)
    write_artifact(tmp_path, pid, jid, oid, PDF_MIME_TYPE, b"%PDF-video-package")
    srt_key = output_storage_key(pid, jid, oid, SRT_MIME_TYPE)
    await set_output_metadata(async_db_session, oid, {"subtitle_storage_key": srt_key})

    resp = client.get(f"/api/v1/outputs/{oid}/download?artifact=srt")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Text-only outputs
# ---------------------------------------------------------------------------


async def test_text_only_output_returns_404(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(async_db_session, output_type="summary")

    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 404


async def test_advisory_text_only_returns_404(tmp_path, client, async_db_session):
    pid, jid, oid = await seed_output(async_db_session, output_type="advisory")

    resp = client.get(f"/api/v1/outputs/{oid}/download")
    assert resp.status_code == 404