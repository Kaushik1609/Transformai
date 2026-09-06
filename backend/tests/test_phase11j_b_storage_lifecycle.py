"""
Phase 11J-B — Storage Lifecycle & Artifact Cleanup

Proves the local storage lifecycle introduced in Phase 11J-B:
    * LocalStorage.delete is containment-safe and idempotent.
    * Source deletion removes the source original file and every output
      artifact (primary + companion PDF/SRT keys) cascaded from it.
    * Project deletion removes every artifact under the project.
    * Files are deleted BEFORE their database record so a transient storage
      failure leaves the record intact for a safe, idempotent retry.
    * Keys still referenced by other live records are protected from deletion.
    * Traversal / absolute / directory targets are rejected.
    * Authorization boundaries (Phase 9A) still gate deletion and downloads.

Uses the existing per-file fixture conventions (no global conftest).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.models.generation_configuration import GenerationConfiguration
from app.db.models.output import Output
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.ingestion.storage import LocalStorage
from app.services.storage_lifecycle import cleanup_storage_keys, output_storage_keys
from app.transformation.artifacts import output_storage_key
from app.transformation.render.pdf import PDF_MIME_TYPE

P11JB_USER = uuid.UUID("ee111111-1111-4e11-8e11-eeeeeeeeeeee")
P11JB_OTHER_USER = uuid.UUID("ff222222-2222-4f22-8f22-ffffffffffff")

SRT_MIME_TYPE = "application/x-subrip"
PNG_MIME_TYPE = "image/png"
PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


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
def local_storage(tmp_path) -> LocalStorage:
    return LocalStorage(str(tmp_path))


def _make_client(
    async_db_session: AsyncSession,
    user_id: uuid.UUID,
    email: str,
) -> TestClient:
    from app.api.deps import CurrentUser, get_current_user
    from app.api.v1 import router as api_v1_router
    from app.api.v1.health import router as health_router
    from app.db.session import get_db

    app = FastAPI()
    app.include_router(health_router)
    app.include_router(api_v1_router, prefix="/api/v1")

    async def override_get_db():
        yield async_db_session

    async def override_get_current_user():
        return CurrentUser(
            id=user_id,
            email=email,
            name="Lifecycle User",
            role="operator",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(scope="function")
def client(
    async_db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    yield _make_client(async_db_session, P11JB_USER, "lifecycle@transformiq.test")


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def seed_chain(
    db: AsyncSession,
    *,
    storage: LocalStorage,
    source_storage_key: str | None,
    outputs: list[dict[str, Any]] | None = None,
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Seed a user -> project -> source -> job -> outputs chain.

    Each output spec may provide ``storage_key``, ``mime_type``, ``metadata``
    (with optional ``pdf_storage_key`` / ``subtitle_storage_key`` companions).
    A missing ``storage_key`` is derived with the approved key scheme whenever
    a ``mime_type`` is given. All referenced keys are written to ``storage``.
    """
    owner_id = owner_id or P11JB_USER
    existing = await db.execute(select(User).where(User.id == owner_id))
    if existing.scalar_one_or_none() is None:
        db.add(
            User(
                id=owner_id,
                email=f"lc-{uuid.uuid4().hex}@transformiq.test",
                name="Lifecycle",
                role="operator",
            )
        )
    project = Project(id=uuid.uuid4(), user_id=owner_id, name="Lifecycle")
    db.add(project)
    source = Source(
        id=uuid.uuid4(),
        project_id=project.id,
        source_type="text",
        status="ready",
        storage_key=source_storage_key,
        extracted_text="Source line one.\nSource line two.",
    )
    config = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
    db.add_all([source, config])
    job = TransformationJob(
        id=uuid.uuid4(),
        project_id=project.id,
        source_id=source.id,
        configuration_id=config.id,
        requested_outputs={"output_types": ["infographic"]},
        status="completed",
    )
    db.add(job)

    written: list[str] = [
        source_storage_key
    ] if source_storage_key else []
    if source_storage_key:
        storage.save(source_storage_key, b"source-bytes")

    output_ids: list[uuid.UUID] = []
    for spec in outputs or ():
        output_id = uuid.uuid4()
        mime = spec.get("mime_type")
        key = spec.get("storage_key")
        if key is None and mime:
            key = output_storage_key(project.id, job.id, output_id, mime)
        db.add(
            Output(
                id=output_id,
                job_id=job.id,
                output_type=spec.get("output_type", "infographic"),
                status=spec.get("status", "completed"),
                storage_key=key,
                mime_type=mime,
                output_metadata=spec.get("metadata"),
            )
        )
        if key:
            storage.save(key, b"artifact-bytes")
            written.append(key)
        for role in ("pdf_storage_key", "subtitle_storage_key"):
            companion = (spec.get("metadata") or {}).get(role)
            if companion:
                storage.save(companion, b"companion-bytes")
                written.append(companion)
        output_ids.append(output_id)

    await db.commit()
    return {
        "project_id": project.id,
        "source_id": source.id,
        "job_id": job.id,
        "config_id": config.id,
        "output_ids": output_ids,
        "written": written,
    }


async def seed_project(
    db: AsyncSession,
    *,
    storage: LocalStorage,
    source_specs: list[dict[str, Any]],
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Seed one user/project with multiple (source, outputs) chains."""
    owner_id = owner_id or P11JB_USER
    existing = await db.execute(select(User).where(User.id == owner_id))
    if existing.scalar_one_or_none() is None:
        db.add(
            User(
                id=owner_id,
                email=f"lc-{uuid.uuid4().hex}@transformiq.test",
                name="Lifecycle",
                role="operator",
            )
        )
    project = Project(id=uuid.uuid4(), user_id=owner_id, name="Lifecycle Project")
    db.add(project)
    config = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
    db.add(config)

    written: list[str] = []
    source_ids: list[uuid.UUID] = []
    output_ids: list[uuid.UUID] = []
    for spec in source_specs:
        source = Source(
            id=uuid.uuid4(),
            project_id=project.id,
            source_type="text",
            status="ready",
            storage_key=spec.get("storage_key"),
        )
        db.add(source)
        if spec.get("storage_key"):
            storage.save(spec["storage_key"], b"source-bytes")
            written.append(spec["storage_key"])
        source_ids.append(source.id)
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=project.id,
            source_id=source.id,
            configuration_id=config.id,
            status="completed",
        )
        db.add(job)
        for output_spec in spec.get("outputs", []):
            output_id = uuid.uuid4()
            mime = output_spec.get("mime_type")
            key = output_spec.get("storage_key")
            if key is None and mime:
                key = output_storage_key(project.id, job.id, output_id, mime)
            db.add(
                Output(
                    id=output_id,
                    job_id=job.id,
                    output_type=output_spec.get("output_type", "infographic"),
                    status="completed",
                    storage_key=key,
                    mime_type=mime,
                    output_metadata=output_spec.get("metadata"),
                )
            )
            output_ids.append(output_id)
            if key:
                storage.save(key, b"artifact-bytes")
                written.append(key)
            for role in ("pdf_storage_key", "subtitle_storage_key"):
                companion = (output_spec.get("metadata") or {}).get(role)
                if companion:
                    storage.save(companion, b"companion-bytes")
                    written.append(companion)

    await db.commit()
    return {
        "project_id": project.id,
        "source_ids": source_ids,
        "output_ids": output_ids,
        "written": written,
    }


async def seed_source_via_api(
    client: TestClient,
    db: AsyncSession,
    storage: LocalStorage,
    key: str,
) -> dict[str, Any]:
    """Create a source through the API and back it with a storage file."""
    proj = client.post("/api/v1/projects", json={"name": "Lifecycle"})
    pid = uuid.UUID(proj.json()["data"]["id"])
    src = client.post(
        f"/api/v1/projects/{pid}/sources",
        json={"source_type": "text", "extracted_text": "Line one.\nLine two."},
    )
    sid = uuid.UUID(src.json()["data"]["id"])
    source = await db.get(Source, sid)
    source.storage_key = key
    storage.save(key, b"source-bytes")
    await db.commit()
    return {"project_id": pid, "source_id": sid}


async def seed_project_via_api(
    client: TestClient,
    db: AsyncSession,
    storage: LocalStorage,
    source_specs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a project + sources through the API, then attach outputs directly."""
    proj = client.post("/api/v1/projects", json={"name": "Lifecycle"})
    pid = uuid.UUID(proj.json()["data"]["id"])
    config = GenerationConfiguration(id=uuid.uuid4(), project_id=pid, language="English")
    db.add(config)

    source_ids: list[uuid.UUID] = []
    outputs: list[dict[str, Any]] = []
    job = None
    for spec in source_specs:
        src = client.post(
            f"/api/v1/projects/{pid}/sources",
            json={"source_type": "text", "extracted_text": "Line one.\nLine two."},
        )
        sid = uuid.UUID(src.json()["data"]["id"])
        source = await db.get(Source, sid)
        source.storage_key = spec["storage_key"]
        storage.save(spec["storage_key"], b"source-bytes")
        source_ids.append(sid)

        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=pid,
            source_id=sid,
            configuration_id=config.id,
            status="completed",
        )
        db.add(job)
        for output_spec in spec.get("outputs", []):
            output_id = uuid.uuid4()
            mime = output_spec.get("mime_type")
            key = output_storage_key(pid, job.id, output_id, mime)
            db.add(
                Output(
                    id=output_id,
                    job_id=job.id,
                    output_type=output_spec.get("output_type", "infographic"),
                    status="completed",
                    storage_key=key,
                    mime_type=mime,
                    output_metadata=None,
                )
            )
            storage.save(key, b"artifact-bytes")
            outputs.append({"id": output_id, "key": key, "source_id": sid})
    await db.commit()
    return {"project_id": pid, "source_ids": source_ids, "outputs": outputs}


def _exists(storage: LocalStorage, key: str) -> bool:
    return (storage.root / key).is_file()


# ---------------------------------------------------------------------------
# A. LocalStorage.delete — containment, idempotency, isolation
# ---------------------------------------------------------------------------


class TestLocalStorageDelete:
    def test_delete_removes_artifact_and_parents_stay(self, local_storage: LocalStorage):
        key = "projects/p/sources/s/original.txt"
        local_storage.save(key, b"hello")
        assert _exists(local_storage, key)
        local_storage.delete(key)
        assert not _exists(local_storage, key)
        assert (local_storage.root / "projects").is_dir()
        local_storage.delete(key)
        assert not _exists(local_storage, key)

    def test_delete_missing_artifact_is_idempotent(self, local_storage: LocalStorage):
        local_storage.delete("projects/p/sources/s/original.txt")
        local_storage.delete("projects/p/sources/s/original.txt")

    def test_delete_nested_key(self, local_storage: LocalStorage):
        key = "projects/p/jobs/j/outputs/o/result.pdf"
        local_storage.save(key, b"pdf")
        local_storage.delete(key)
        assert not _exists(local_storage, key)

    @pytest.mark.parametrize(
        "key",
        [
            "../escape.txt",
            "./../escape.txt",
            "a/../../escape.txt",
            "..\\..\\escape.txt",
            "projects\\..\\..\\escape.txt",
        ],
    )
    def test_delete_rejects_traversal_keys(self, local_storage: LocalStorage, key: str):
        outside = local_storage.root.parent / "escape.txt"
        outside.write_bytes(b"keep")
        try:
            with pytest.raises(ValueError):
                local_storage.delete(key)
            assert outside.read_bytes() == b"keep"
        finally:
            outside.unlink(missing_ok=True)

    @pytest.mark.parametrize("key", [r"C:\Windows\system32\evil.txt", r"D:\etc\passwd"])
    def test_delete_rejects_absolute_paths(self, local_storage: LocalStorage, key: str):
        with pytest.raises(ValueError):
            local_storage.delete(key)

    def test_delete_directory_target_raises(self, local_storage: LocalStorage):
        target = "projects/p/sources/s/original.txt"
        local_storage.save(target, b"hello")
        (local_storage.root / "projects").mkdir(parents=True, exist_ok=True)
        with pytest.raises(OSError):
            local_storage.delete("projects")  # a directory, not an artifact
        assert _exists(local_storage, target)

    def test_delete_leaves_unrelated_files_untouched(self, local_storage: LocalStorage):
        target = "projects/p/sources/s/original.txt"
        unrelated = "projects/q/sources/t/original.txt"
        local_storage.save(target, b"a")
        local_storage.save(unrelated, b"b")
        local_storage.delete(target)
        assert not _exists(local_storage, target)
        assert _exists(local_storage, unrelated)
        assert local_storage.read(unrelated) == b"b"


# ---------------------------------------------------------------------------
# B. cleanup_storage_keys — batch helper behaviour
# ---------------------------------------------------------------------------


class TestCleanupStorageKeys:
    def test_empty_keys_noop(self, local_storage: LocalStorage):
        key = "projects/p/sources/s/original.txt"
        local_storage.save(key, b"hi")
        cleanup_storage_keys(local_storage, keys=[])
        assert _exists(local_storage, key)

    def test_deletes_keys_and_protects_referenced(self, local_storage: LocalStorage):
        a = "projects/p/sources/s/a.txt"
        b = "projects/p/sources/s/b.txt"
        local_storage.save(a, b"a")
        local_storage.save(b, b"b")
        cleanup_storage_keys(local_storage, keys=[a, b], referenced_keys={b})
        assert not _exists(local_storage, a)
        assert _exists(local_storage, b)

    def test_traversal_key_raises_before_any_deletion(self, local_storage: LocalStorage):
        good = "projects/p/sources/s/original.txt"
        local_storage.save(good, b"keep")
        with pytest.raises(ValueError):
            cleanup_storage_keys(local_storage, keys=["../escape.txt", good])
        assert _exists(local_storage, good)
        assert not (local_storage.root.parent / "escape.txt").exists()


# ---------------------------------------------------------------------------
# C. Service-level lifetime — source / output / project cleanup
# ---------------------------------------------------------------------------


class TestSourceCleanup:
    async def test_delete_source_removes_file_and_record(self, async_db_session, local_storage):
        info = await seed_chain(
            async_db_session,
            storage=local_storage,
            source_storage_key="projects/p/sources/s/original.txt",
        )
        unrelated = "projects/other/sources/o/original.txt"
        local_storage.save(unrelated, b"unrelated")
        source = await async_db_session.get(Source, info["source_id"])
        from app.services.source_service import delete_source

        await delete_source(async_db_session, source=source, storage=local_storage)
        await async_db_session.commit()

        assert not _exists(local_storage, "projects/p/sources/s/original.txt")
        assert _exists(local_storage, unrelated)
        assert await async_db_session.get(Source, info["source_id"]) is None

    async def test_delete_source_cleans_output_primary_and_companions(self, async_db_session, local_storage):
        info = await seed_chain(
            async_db_session,
            storage=local_storage,
            source_storage_key="projects/p/sources/s/original.txt",
            outputs=[
                {
                    "output_type": "infographic",
                    "mime_type": PNG_MIME_TYPE,
                    "metadata": {
                        "pdf_storage_key": "projects/p/jobs/j/outputs/o/result.pdf",
                        "subtitle_storage_key": "projects/p/jobs/j/outputs/o/subtitle.srt",
                    },
                }
            ],
        )
        source = await async_db_session.get(Source, info["source_id"])
        from app.services.source_service import delete_source

        await delete_source(async_db_session, source=source, storage=local_storage)
        await async_db_session.commit()

        for key in info["written"]:
            assert not _exists(local_storage, key), key
        assert (
            await async_db_session.execute(
                select(Output.id).where(Output.id.in_(info["output_ids"]))
            )
        ).scalars().all() == []

    async def test_output_keys_and_metadata_correct(self, async_db_session, local_storage):
        info = await seed_chain(
            async_db_session,
            storage=local_storage,
            source_storage_key=None,
            outputs=[
                {
                    "output_type": "infographic",
                    "mime_type": PDF_MIME_TYPE,
                    "metadata": {
                        "pdf_storage_key": "projects/p/jobs/j/outputs/o/result.pdf",
                        "subtitle_storage_key": "projects/p/jobs/j/outputs/o/subtitle.srt",
                    },
                }
            ],
        )
        output = await async_db_session.get(Output, info["output_ids"][0])
        expected_primary = output_storage_key(
            info["project_id"], info["job_id"], output.id, PDF_MIME_TYPE
        )
        assert output.storage_key == expected_primary
        keys = output_storage_keys(output)
        assert expected_primary in keys
        assert "projects/p/jobs/j/outputs/o/result.pdf" in keys
        assert "projects/p/jobs/j/outputs/o/subtitle.srt" in keys
        assert local_storage.read(expected_primary) == b"artifact-bytes"
        assert local_storage.read("projects/p/jobs/j/outputs/o/subtitle.srt") == b"companion-bytes"

    async def test_shared_companion_key_protected_until_last_reference(self, async_db_session, local_storage):
        shared = "projects/shared/artifacts/companion.pdf"
        a = await seed_chain(
            async_db_session,
            storage=local_storage,
            source_storage_key="projects/a/sources/a/original.txt",
            outputs=[{"output_type": "infographic", "mime_type": PNG_MIME_TYPE, "metadata": {"pdf_storage_key": shared}}],
        )
        b = await seed_chain(
            async_db_session,
            storage=local_storage,
            source_storage_key="projects/b/sources/b/original.txt",
            outputs=[{"output_type": "infographic", "mime_type": PNG_MIME_TYPE, "metadata": {"pdf_storage_key": shared}}],
        )
        from app.services.source_service import delete_source

        source_a = await async_db_session.get(Source, a["source_id"])
        await delete_source(async_db_session, source=source_a, storage=local_storage)
        await async_db_session.commit()

        assert not _exists(local_storage, "projects/a/sources/a/original.txt")
        assert not _exists(local_storage, a["written"][1])  # A's primary artifact
        assert _exists(local_storage, shared)  # still referenced by source B
        assert _exists(local_storage, "projects/b/sources/b/original.txt")

        source_b = await async_db_session.get(Source, b["source_id"])
        await delete_source(async_db_session, source=source_b, storage=local_storage)
        await async_db_session.commit()

        assert not _exists(local_storage, shared)  # last reference removed
        assert not _exists(local_storage, b["written"][1])

    async def test_shared_source_key_protected_by_other_source(self, async_db_session, local_storage):
        shared = "projects/shared/p/sources/shared/original.txt"
        a = await seed_chain(async_db_session, storage=local_storage, source_storage_key=shared)
        b = await seed_chain(async_db_session, storage=local_storage, source_storage_key=shared)
        from app.services.source_service import delete_source

        source_a = await async_db_session.get(Source, a["source_id"])
        await delete_source(async_db_session, source=source_a, storage=local_storage)
        assert _exists(local_storage, shared)  # still referenced by source B

        source_b = await async_db_session.get(Source, b["source_id"])
        await delete_source(async_db_session, source=source_b, storage=local_storage)
        assert not _exists(local_storage, shared)

    async def test_cleanup_failure_keeps_record_and_file_for_retry(self, async_db_session, tmp_path):
        key = "projects/p/sources/s/original.txt"
        root = str(tmp_path)
        info = await seed_chain(
            async_db_session,
            storage=LocalStorage(root),
            source_storage_key=key,
        )

        class FailingStorage(LocalStorage):
            def delete(self, k: str) -> None:
                raise OSError("simulated transient storage failure")

        from app.services.source_service import delete_source

        source = await async_db_session.get(Source, info["source_id"])
        with pytest.raises(OSError):
            await delete_source(async_db_session, source=source, storage=FailingStorage(root))

        assert await async_db_session.get(Source, info["source_id"]) is not None
        assert _exists(LocalStorage(root), key)

        source = await async_db_session.get(Source, info["source_id"])
        await delete_source(async_db_session, source=source, storage=LocalStorage(root))
        await async_db_session.commit()

        assert await async_db_session.get(Source, info["source_id"]) is None
        assert not _exists(LocalStorage(root), key)

    async def test_delete_source_with_missing_artifact_still_succeeds(self, async_db_session, tmp_path):
        root = str(tmp_path)
        storage = LocalStorage(root)
        key = "projects/p/jobs/j/outputs/o/result.txt"
        info = await seed_chain(
            async_db_session,
            storage=storage,
            source_storage_key=None,
            outputs=[{"output_type": "summary", "storage_key": key, "mime_type": "text/plain"}],
        )
        (storage.root / key).unlink()  # simulate artifact lost out-of-band
        source = await async_db_session.get(Source, info["source_id"])
        from app.services.source_service import delete_source

        await delete_source(async_db_session, source=source, storage=storage)
        await async_db_session.commit()
        assert await async_db_session.get(Source, info["source_id"]) is None

    async def test_delete_source_without_storage_key_is_noop_on_storage(self, async_db_session, local_storage):
        info = await seed_chain(async_db_session, storage=local_storage, source_storage_key=None)
        unrelated = "projects/other/sources/u/original.txt"
        local_storage.save(unrelated, b"keep")
        source = await async_db_session.get(Source, info["source_id"])
        from app.services.source_service import delete_source

        await delete_source(async_db_session, source=source, storage=local_storage)
        await async_db_session.commit()
        assert await async_db_session.get(Source, info["source_id"]) is None
        assert _exists(local_storage, unrelated)


class TestProjectCleanup:
    async def test_delete_project_cleans_all_source_and_output_artifacts(self, async_db_session, local_storage):
        first = "projects/p/sources/first/original.txt"
        second = "projects/p/sources/second/original.txt"
        info = await seed_project(
            async_db_session,
            storage=local_storage,
            source_specs=[
                {"storage_key": first},
                {
                    "storage_key": second,
                    "outputs": [
                        {
                            "output_type": "infographic",
                            "mime_type": PDF_MIME_TYPE,
                            "metadata": {
                                "pdf_storage_key": "projects/p/jobs/j/outputs/f/output.pdf",
                                "subtitle_storage_key": "projects/p/jobs/j/outputs/f/subtitle.srt",
                            },
                        }
                    ],
                },
            ],
        )
        project = await async_db_session.get(Project, info["project_id"])
        from app.services.project_service import delete_project

        await delete_project(async_db_session, project=project, storage=local_storage)
        await async_db_session.commit()

        assert not _exists(local_storage, first)
        assert not _exists(local_storage, second)
        assert not _exists(local_storage, "projects/p/jobs/j/outputs/f/output.pdf")
        assert not _exists(local_storage, "projects/p/jobs/j/outputs/f/subtitle.srt")
        sources = (
            await async_db_session.execute(
                select(Source.id).where(Source.project_id == info["project_id"])
            )
        ).scalars().all()
        outputs = (
            await async_db_session.execute(
                select(Output.id).where(Output.id.in_(info["output_ids"]))
            )
        ).scalars().all()
        assert sources == []
        assert outputs == []

    async def test_delete_project_keeps_artifacts_still_referenced_by_other_project(self, async_db_session, local_storage):
        shared = "projects/shared/artifacts/companion.pdf"
        proj = await seed_project(
            async_db_session,
            storage=local_storage,
            source_specs=[
                {
                    "storage_key": "projects/p/sources/s/original.txt",
                    "outputs": [{"output_type": "infographic", "mime_type": PNG_MIME_TYPE, "metadata": {"pdf_storage_key": shared}}],
                }
            ],
        )
        other = await seed_project(
            async_db_session,
            storage=local_storage,
            source_specs=[
                {
                    "storage_key": "projects/q/sources/q/original.txt",
                    "outputs": [{"output_type": "infographic", "mime_type": PNG_MIME_TYPE, "metadata": {"pdf_storage_key": shared}}],
                }
            ],
        )
        from app.services.project_service import delete_project

        project = await async_db_session.get(Project, proj["project_id"])
        await delete_project(async_db_session, project=project, storage=local_storage)
        await async_db_session.commit()

        assert not _exists(local_storage, "projects/p/sources/s/original.txt")
        assert _exists(local_storage, shared)
        assert _exists(local_storage, "projects/q/sources/q/original.txt")

        other_project = await async_db_session.get(Project, other["project_id"])
        await delete_project(async_db_session, project=other_project, storage=local_storage)
        await async_db_session.commit()
        assert not _exists(local_storage, shared)


# ---------------------------------------------------------------------------
# D. API-level — authorization boundaries and download behaviour
# ---------------------------------------------------------------------------


class TestApiLifecycle:
    async def test_own_source_delete_via_api_cleans_artifact(self, client, async_db_session, tmp_path):
        storage = LocalStorage(str(tmp_path))
        key = "projects/p/sources/s/original.txt"
        info = await seed_source_via_api(client, async_db_session, storage, key)

        resp = client.delete(f"/api/v1/sources/{info['source_id']}")
        assert resp.status_code == 200
        assert not (storage.root / key).exists()

    async def test_other_user_cannot_delete_source_and_artifact_untouched(
        self, async_db_session, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
        storage = LocalStorage(str(tmp_path))
        key = "projects/p/sources/s/original.txt"
        owner = _make_client(async_db_session, P11JB_OTHER_USER, "other@transformiq.test")
        info = await seed_source_via_api(owner, async_db_session, storage, key)

        attacker = _make_client(async_db_session, P11JB_USER, "kill@transformiq.test")
        resp = attacker.delete(f"/api/v1/sources/{info['source_id']}")
        assert resp.status_code == 404
        assert (storage.root / key).exists()

        resp = owner.delete(f"/api/v1/sources/{info['source_id']}")
        assert resp.status_code == 200
        assert not (storage.root / key).exists()

    async def test_output_download_regression_after_sibling_delete(self, client, async_db_session, tmp_path):
        storage = LocalStorage(str(tmp_path))
        info = await seed_project_via_api(
            client,
            async_db_session,
            storage,
            [
                {
                    "storage_key": "projects/p/sources/a/original.txt",
                    "outputs": [{"output_type": "infographic", "mime_type": PDF_MIME_TYPE}],
                },
                {
                    "storage_key": "projects/p/sources/b/original.txt",
                    "outputs": [{"output_type": "presentation", "mime_type": PPTX_MIME_TYPE}],
                },
            ],
        )
        out_a = info["outputs"][0]
        out_b = info["outputs"][1]
        source_a = info["source_ids"][0]

        resp = client.get(f"/api/v1/outputs/{out_b['id']}/download")
        assert resp.status_code == 200
        assert resp.content == b"artifact-bytes"

        assert client.delete(f"/api/v1/sources/{source_a}").status_code == 200
        assert not (storage.root / out_a["key"]).exists()

        assert client.get(f"/api/v1/outputs/{out_a['id']}/download").status_code == 404
        resp = client.get(f"/api/v1/outputs/{out_b['id']}/download")
        assert resp.status_code == 200
        assert resp.content == b"artifact-bytes"
        assert (storage.root / out_b["key"]).exists()