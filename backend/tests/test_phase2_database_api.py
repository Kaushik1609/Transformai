"""
Phase 2 Tests — Database + API Foundation

Tests cover:
- Database connection layer (models, engine, session)
- SQLAlchemy model creation and relationships
- Project CRUD API (create, read, update, delete)
- Source metadata API
- Configuration API
- Transformation job API
- Output + VerificationResult persistence
- Validation errors
- Not-found errors
- API response format

Uses an in-memory SQLite database for test isolation.
No live PostgreSQL required for the unit test suite.
"""
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base

# ---------------------------------------------------------------------------
# SQLite in-memory engine for tests
# ---------------------------------------------------------------------------

SQLITE_URL = "sqlite://"


@pytest.fixture(scope="session")
def sqlite_engine():
    """Create a single shared in-memory SQLite engine for the test session."""
    engine = create_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    # Enable FK enforcement in SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create all tables using our ORM models
    # Import models to ensure they are registered with Base.metadata
    import app.db.models  # noqa: F401

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(sqlite_engine) -> Generator[Session, None, None]:
    """
    Provide a transactional test database session.
    Each test gets a fresh transaction that is rolled back after the test.
    """
    TestingSessionLocal = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    session = TestingSessionLocal()
    session.begin_nested()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# FastAPI test client with overridden DB dependency
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

TEST_USER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


@pytest.fixture(scope="function")
async def async_db_session():
    """
    Provide an async SQLite session for API tests.

    The API and services use SQLAlchemy's async contract, so the FastAPI
    dependency override must provide AsyncSession rather than the synchronous
    session used by the direct ORM tests above.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()

    await engine.dispose()


@pytest.fixture(scope="function")
def client(async_db_session: AsyncSession):
    """
    FastAPI test client with the async DB dependency replaced by an async
    SQLite session so no real PostgreSQL is needed.
    """
    from app.main import app
    from app.db.session import get_db
    from app.api.deps import get_current_user, CurrentUser, DEV_USER_ID, DEV_USER_EMAIL, DEV_USER_NAME, DEV_USER_ROLE

    async def override_get_db():
        yield async_db_session

    async def override_get_current_user():
        return CurrentUser(
            id=TEST_USER_ID,
            email=DEV_USER_EMAIL,
            name=DEV_USER_NAME,
            role=DEV_USER_ROLE,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()


# ===========================================================================
# 1. Database layer — model creation tests
# ===========================================================================

class TestModelCreation:
    """Verify that ORM models can be instantiated and persisted."""

    def test_user_creation(self, db_session: Session):
        from app.db.models.user import User

        user = User(
            id=uuid.uuid4(),
            email="test@example.com",
            name="Test User",
            role="operator",
        )
        db_session.add(user)
        db_session.flush()

        result = db_session.get(User, user.id)
        assert result is not None
        assert result.email == "test@example.com"
        assert result.role == "operator"

    def test_project_creation(self, db_session: Session):
        from app.db.models.user import User
        from app.db.models.project import Project

        user = User(id=uuid.uuid4(), email="p@example.com", name="U", role="operator")
        db_session.add(user)
        db_session.flush()

        project = Project(
            id=uuid.uuid4(),
            user_id=user.id,
            name="Test Project",
            description="A test",
        )
        db_session.add(project)
        db_session.flush()

        result = db_session.get(Project, project.id)
        assert result is not None
        assert result.name == "Test Project"
        assert result.user_id == user.id

    def test_source_creation(self, db_session: Session):
        from app.db.models.user import User
        from app.db.models.project import Project
        from app.db.models.source import Source

        user = User(id=uuid.uuid4(), email="s@example.com", name="U", role="operator")
        db_session.add(user)
        db_session.flush()

        project = Project(id=uuid.uuid4(), user_id=user.id, name="P", description=None)
        db_session.add(project)
        db_session.flush()

        source = Source(
            id=uuid.uuid4(),
            project_id=project.id,
            source_type="text",
            language="en",
            status="uploaded",
        )
        db_session.add(source)
        db_session.flush()

        result = db_session.get(Source, source.id)
        assert result is not None
        assert result.source_type == "text"
        assert result.status == "uploaded"

    def test_source_chunk_creation(self, db_session: Session):
        from app.db.models.user import User
        from app.db.models.project import Project
        from app.db.models.source import Source
        from app.db.models.source_chunk import SourceChunk

        user = User(id=uuid.uuid4(), email="sc@example.com", name="U", role="operator")
        db_session.add(user)
        db_session.flush()
        project = Project(id=uuid.uuid4(), user_id=user.id, name="P", description=None)
        db_session.add(project)
        db_session.flush()
        source = Source(id=uuid.uuid4(), project_id=project.id, source_type="text", language="en", status="uploaded")
        db_session.add(source)
        db_session.flush()

        chunk = SourceChunk(
            id=uuid.uuid4(),
            source_id=source.id,
            chunk_index=0,
            content="First chunk of text.",
        )
        db_session.add(chunk)
        db_session.flush()

        result = db_session.get(SourceChunk, chunk.id)
        assert result is not None
        assert result.content == "First chunk of text."
        assert result.chunk_index == 0

    def test_generation_configuration_creation(self, db_session: Session):
        from app.db.models.user import User
        from app.db.models.project import Project
        from app.db.models.generation_configuration import GenerationConfiguration

        user = User(id=uuid.uuid4(), email="gc@example.com", name="U", role="operator")
        db_session.add(user)
        db_session.flush()
        project = Project(id=uuid.uuid4(), user_id=user.id, name="P", description=None)
        db_session.add(project)
        db_session.flush()

        config = GenerationConfiguration(
            id=uuid.uuid4(),
            project_id=project.id,
            target_audience="executives",
            tone="professional",
            language="English",
            detail_level="standard",
        )
        db_session.add(config)
        db_session.flush()

        result = db_session.get(GenerationConfiguration, config.id)
        assert result is not None
        assert result.target_audience == "executives"
        assert result.language == "English"

    def test_transformation_job_creation(self, db_session: Session):
        from app.db.models.user import User
        from app.db.models.project import Project
        from app.db.models.source import Source
        from app.db.models.generation_configuration import GenerationConfiguration
        from app.db.models.transformation_job import TransformationJob

        user = User(id=uuid.uuid4(), email="tj@example.com", name="U", role="operator")
        db_session.add(user)
        db_session.flush()
        project = Project(id=uuid.uuid4(), user_id=user.id, name="P", description=None)
        db_session.add(project)
        db_session.flush()
        source = Source(id=uuid.uuid4(), project_id=project.id, source_type="text", language="en", status="uploaded")
        db_session.add(source)
        db_session.flush()
        config = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
        db_session.add(config)
        db_session.flush()

        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=project.id,
            source_id=source.id,
            configuration_id=config.id,
            requested_outputs={"output_types": ["summary"]},
            status="queued",
            progress=0,
        )
        db_session.add(job)
        db_session.flush()

        result = db_session.get(TransformationJob, job.id)
        assert result is not None
        assert result.status == "queued"
        assert result.progress == 0

    def test_output_creation(self, db_session: Session):
        from app.db.models.user import User
        from app.db.models.project import Project
        from app.db.models.source import Source
        from app.db.models.generation_configuration import GenerationConfiguration
        from app.db.models.transformation_job import TransformationJob
        from app.db.models.output import Output

        user = User(id=uuid.uuid4(), email="o@example.com", name="U", role="operator")
        db_session.add(user)
        db_session.flush()
        project = Project(id=uuid.uuid4(), user_id=user.id, name="P", description=None)
        db_session.add(project)
        db_session.flush()
        source = Source(id=uuid.uuid4(), project_id=project.id, source_type="text", language="en", status="uploaded")
        db_session.add(source)
        db_session.flush()
        config = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
        db_session.add(config)
        db_session.flush()
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=project.id,
            source_id=source.id,
            configuration_id=config.id,
            status="queued",
            progress=0,
        )
        db_session.add(job)
        db_session.flush()

        output = Output(
            id=uuid.uuid4(),
            job_id=job.id,
            output_type="summary",
            status="generating",
        )
        db_session.add(output)
        db_session.flush()

        result = db_session.get(Output, output.id)
        assert result is not None
        assert result.output_type == "summary"
        assert result.status == "generating"

    def test_verification_result_creation(self, db_session: Session):
        from app.db.models.user import User
        from app.db.models.project import Project
        from app.db.models.source import Source
        from app.db.models.generation_configuration import GenerationConfiguration
        from app.db.models.transformation_job import TransformationJob
        from app.db.models.output import Output
        from app.db.models.verification_result import VerificationResult

        user = User(id=uuid.uuid4(), email="vr@example.com", name="U", role="operator")
        db_session.add(user)
        db_session.flush()
        project = Project(id=uuid.uuid4(), user_id=user.id, name="P", description=None)
        db_session.add(project)
        db_session.flush()
        source = Source(id=uuid.uuid4(), project_id=project.id, source_type="text", language="en", status="uploaded")
        db_session.add(source)
        db_session.flush()
        config = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
        db_session.add(config)
        db_session.flush()
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=project.id,
            source_id=source.id,
            configuration_id=config.id,
            status="queued",
            progress=0,
        )
        db_session.add(job)
        db_session.flush()
        output = Output(id=uuid.uuid4(), job_id=job.id, output_type="summary", status="completed")
        db_session.add(output)
        db_session.flush()

        vr = VerificationResult(
            id=uuid.uuid4(),
            output_id=output.id,
            overall_status="passed",
            claims_checked=5,
            claims_supported=5,
        )
        db_session.add(vr)
        db_session.flush()

        result = db_session.get(VerificationResult, vr.id)
        assert result is not None
        assert result.overall_status == "passed"
        assert result.claims_checked == 5


# ===========================================================================
# 2. Project API tests
# ===========================================================================

class TestProjectAPI:
    """Full CRUD test suite for /api/v1/projects."""

    def test_create_project_returns_201(self, client: TestClient):
        response = client.post("/api/v1/projects", json={"name": "My Project"})
        assert response.status_code == 201

    def test_create_project_returns_success_envelope(self, client: TestClient):
        response = client.post("/api/v1/projects", json={"name": "Envelope Test"})
        data = response.json()
        assert data["success"] is True
        assert "data" in data

    def test_create_project_returns_id(self, client: TestClient):
        response = client.post("/api/v1/projects", json={"name": "Has ID"})
        data = response.json()
        assert "id" in data["data"]
        assert uuid.UUID(data["data"]["id"])  # Valid UUID

    def test_create_project_with_description(self, client: TestClient):
        response = client.post(
            "/api/v1/projects",
            json={"name": "With Desc", "description": "Some description"},
        )
        data = response.json()
        assert data["data"]["description"] == "Some description"

    def test_create_project_validates_empty_name(self, client: TestClient):
        response = client.post("/api/v1/projects", json={"name": ""})
        assert response.status_code == 422

    def test_create_project_validates_missing_name(self, client: TestClient):
        response = client.post("/api/v1/projects", json={})
        assert response.status_code == 422

    def test_list_projects_returns_200(self, client: TestClient):
        response = client.get("/api/v1/projects")
        assert response.status_code == 200

    def test_list_projects_has_data_and_count(self, client: TestClient):
        client.post("/api/v1/projects", json={"name": "List Test"})
        data = client.get("/api/v1/projects").json()
        assert "data" in data
        assert "count" in data
        assert isinstance(data["count"], int)

    def test_get_project_by_id(self, client: TestClient):
        create_resp = client.post("/api/v1/projects", json={"name": "GetByID"})
        project_id = create_resp.json()["data"]["id"]
        get_resp = client.get(f"/api/v1/projects/{project_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["id"] == project_id

    def test_get_project_not_found(self, client: TestClient):
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/projects/{fake_id}")
        assert response.status_code == 404
        assert "detail" in response.json()

    def test_get_project_invalid_uuid(self, client: TestClient):
        response = client.get("/api/v1/projects/not-a-uuid")
        assert response.status_code == 422

    def test_update_project_name(self, client: TestClient):
        create_resp = client.post("/api/v1/projects", json={"name": "Original"})
        project_id = create_resp.json()["data"]["id"]
        patch_resp = client.patch(
            f"/api/v1/projects/{project_id}",
            json={"name": "Updated"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["data"]["name"] == "Updated"

    def test_update_project_description(self, client: TestClient):
        create_resp = client.post("/api/v1/projects", json={"name": "Patch Desc"})
        project_id = create_resp.json()["data"]["id"]
        patch_resp = client.patch(
            f"/api/v1/projects/{project_id}",
            json={"description": "New description"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["data"]["description"] == "New description"

    def test_update_project_not_found(self, client: TestClient):
        fake_id = str(uuid.uuid4())
        response = client.patch(f"/api/v1/projects/{fake_id}", json={"name": "X"})
        assert response.status_code == 404

    def test_delete_project(self, client: TestClient):
        create_resp = client.post("/api/v1/projects", json={"name": "To Delete"})
        project_id = create_resp.json()["data"]["id"]
        del_resp = client.delete(f"/api/v1/projects/{project_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

    def test_delete_project_not_found(self, client: TestClient):
        fake_id = str(uuid.uuid4())
        response = client.delete(f"/api/v1/projects/{fake_id}")
        assert response.status_code == 404

    def test_deleted_project_returns_404(self, client: TestClient):
        create_resp = client.post("/api/v1/projects", json={"name": "Gone"})
        project_id = create_resp.json()["data"]["id"]
        client.delete(f"/api/v1/projects/{project_id}")
        get_resp = client.get(f"/api/v1/projects/{project_id}")
        assert get_resp.status_code == 404

    def test_project_response_has_timestamps(self, client: TestClient):
        resp = client.post("/api/v1/projects", json={"name": "Timestamps"})
        data = resp.json()["data"]
        assert "created_at" in data
        assert "updated_at" in data


# ===========================================================================
# 3. Source API tests
# ===========================================================================

class TestSourceAPI:
    """Source metadata CRUD tests."""

    def _create_project(self, client: TestClient) -> str:
        resp = client.post("/api/v1/projects", json={"name": "Source Project"})
        return resp.json()["data"]["id"]

    def test_create_source_returns_201(self, client: TestClient):
        pid = self._create_project(client)
        resp = client.post(
            f"/api/v1/projects/{pid}/sources",
            json={"source_type": "text", "extracted_text": "Hello world"},
        )
        assert resp.status_code == 201

    def test_create_source_returns_success_envelope(self, client: TestClient):
        pid = self._create_project(client)
        resp = client.post(
            f"/api/v1/projects/{pid}/sources",
            json={"source_type": "text"},
        )
        data = resp.json()
        assert data["success"] is True
        assert "data" in data

    def test_create_source_with_metadata(self, client: TestClient):
        pid = self._create_project(client)
        resp = client.post(
            f"/api/v1/projects/{pid}/sources",
            json={"source_type": "pdf", "metadata": {"pages": 10}},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["source_metadata"]["pages"] == 10

    def test_create_source_in_nonexistent_project(self, client: TestClient):
        fake_pid = str(uuid.uuid4())
        resp = client.post(
            f"/api/v1/projects/{fake_pid}/sources",
            json={"source_type": "text"},
        )
        assert resp.status_code == 404

    def test_list_sources_returns_200(self, client: TestClient):
        pid = self._create_project(client)
        resp = client.get(f"/api/v1/projects/{pid}/sources")
        assert resp.status_code == 200

    def test_list_sources_has_count(self, client: TestClient):
        pid = self._create_project(client)
        client.post(f"/api/v1/projects/{pid}/sources", json={"source_type": "text"})
        data = client.get(f"/api/v1/projects/{pid}/sources").json()
        assert data["count"] >= 1

    def test_get_source_by_id(self, client: TestClient):
        pid = self._create_project(client)
        create_resp = client.post(
            f"/api/v1/projects/{pid}/sources",
            json={"source_type": "text"},
        )
        source_id = create_resp.json()["data"]["id"]
        get_resp = client.get(f"/api/v1/sources/{source_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["id"] == source_id

    def test_get_source_not_found(self, client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/sources/{fake_id}")
        assert resp.status_code == 404

    def test_delete_source(self, client: TestClient):
        pid = self._create_project(client)
        create_resp = client.post(
            f"/api/v1/projects/{pid}/sources",
            json={"source_type": "text"},
        )
        source_id = create_resp.json()["data"]["id"]
        del_resp = client.delete(f"/api/v1/sources/{source_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

    def test_source_status_defaults_to_uploaded(self, client: TestClient):
        pid = self._create_project(client)
        resp = client.post(
            f"/api/v1/projects/{pid}/sources",
            json={"source_type": "text"},
        )
        assert resp.json()["data"]["status"] == "uploaded"


# ===========================================================================
# 4. Configuration API tests
# ===========================================================================

class TestConfigurationAPI:
    """Generation configuration persistence tests."""

    def _create_project(self, client: TestClient) -> str:
        resp = client.post("/api/v1/projects", json={"name": "Config Project"})
        return resp.json()["data"]["id"]

    def test_create_configuration_returns_201(self, client: TestClient):
        pid = self._create_project(client)
        resp = client.post(
            f"/api/v1/projects/{pid}/configurations",
            json={"language": "English"},
        )
        assert resp.status_code == 201

    def test_create_configuration_persists_fields(self, client: TestClient):
        pid = self._create_project(client)
        resp = client.post(
            f"/api/v1/projects/{pid}/configurations",
            json={
                "target_audience": "executives",
                "tone": "professional",
                "language": "English",
                "detail_level": "standard",
                "communication_objective": "inform",
                "content_style": "bullet-points",
                "custom_instructions": "Keep it short.",
            },
        )
        data = resp.json()["data"]
        assert data["target_audience"] == "executives"
        assert data["tone"] == "professional"
        assert data["detail_level"] == "standard"
        assert data["custom_instructions"] == "Keep it short."

    def test_list_configurations(self, client: TestClient):
        pid = self._create_project(client)
        client.post(f"/api/v1/projects/{pid}/configurations", json={"language": "English"})
        resp = client.get(f"/api/v1/projects/{pid}/configurations")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_get_configuration_by_id(self, client: TestClient):
        pid = self._create_project(client)
        create_resp = client.post(
            f"/api/v1/projects/{pid}/configurations",
            json={"language": "French"},
        )
        config_id = create_resp.json()["data"]["id"]
        get_resp = client.get(f"/api/v1/configurations/{config_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["id"] == config_id
        assert get_resp.json()["data"]["language"] == "French"

    def test_update_configuration(self, client: TestClient):
        pid = self._create_project(client)
        create_resp = client.post(
            f"/api/v1/projects/{pid}/configurations",
            json={"language": "English"},
        )
        config_id = create_resp.json()["data"]["id"]
        patch_resp = client.patch(
            f"/api/v1/configurations/{config_id}",
            json={"tone": "formal"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["data"]["tone"] == "formal"

    def test_delete_configuration(self, client: TestClient):
        pid = self._create_project(client)
        create_resp = client.post(
            f"/api/v1/projects/{pid}/configurations",
            json={"language": "English"},
        )
        config_id = create_resp.json()["data"]["id"]
        del_resp = client.delete(f"/api/v1/configurations/{config_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

    def test_configuration_not_found(self, client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/configurations/{fake_id}")
        assert resp.status_code == 404


# ===========================================================================
# 5. Transformation Job API tests
# ===========================================================================

class TestTransformationAPI:
    """Transformation job persistence tests."""

    def _setup_project_source_config(self, client: TestClient) -> tuple[str, str, str]:
        """Create project + source + configuration, return their IDs."""
        proj = client.post("/api/v1/projects", json={"name": "TJ Project"})
        pid = proj.json()["data"]["id"]

        src = client.post(
            f"/api/v1/projects/{pid}/sources",
            json={"source_type": "text"},
        )
        sid = src.json()["data"]["id"]

        cfg = client.post(
            f"/api/v1/projects/{pid}/configurations",
            json={"language": "English"},
        )
        cid = cfg.json()["data"]["id"]

        return pid, sid, cid

    def test_create_transformation_job_returns_201(self, client: TestClient):
        pid, sid, cid = self._setup_project_source_config(client)
        resp = client.post(
            "/api/v1/transformations",
            json={
                "project_id": pid,
                "source_id": sid,
                "configuration_id": cid,
                "output_types": ["summary"],
            },
        )
        assert resp.status_code == 201

    def test_create_transformation_job_status_queued(self, client: TestClient):
        pid, sid, cid = self._setup_project_source_config(client)
        resp = client.post(
            "/api/v1/transformations",
            json={
                "project_id": pid,
                "source_id": sid,
                "configuration_id": cid,
                "output_types": ["summary", "linkedin"],
            },
        )
        assert resp.json()["data"]["status"] == "queued"

    def test_create_transformation_job_persists_requested_outputs(self, client: TestClient):
        pid, sid, cid = self._setup_project_source_config(client)
        resp = client.post(
            "/api/v1/transformations",
            json={
                "project_id": pid,
                "source_id": sid,
                "configuration_id": cid,
                "output_types": ["summary", "linkedin"],
            },
        )
        data = resp.json()["data"]
        assert data["requested_outputs"]["output_types"] == ["summary", "linkedin"]

    def test_get_transformation_job(self, client: TestClient):
        pid, sid, cid = self._setup_project_source_config(client)
        create_resp = client.post(
            "/api/v1/transformations",
            json={
                "project_id": pid,
                "source_id": sid,
                "configuration_id": cid,
                "output_types": ["summary"],
            },
        )
        job_id = create_resp.json()["data"]["id"]
        get_resp = client.get(f"/api/v1/transformations/{job_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["id"] == job_id

    def test_get_transformation_job_not_found(self, client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/transformations/{fake_id}")
        assert resp.status_code == 404

    def test_list_job_outputs_empty(self, client: TestClient):
        pid, sid, cid = self._setup_project_source_config(client)
        create_resp = client.post(
            "/api/v1/transformations",
            json={
                "project_id": pid,
                "source_id": sid,
                "configuration_id": cid,
                "output_types": ["summary"],
            },
        )
        job_id = create_resp.json()["data"]["id"]
        list_resp = client.get(f"/api/v1/transformations/{job_id}/outputs")
        assert list_resp.status_code == 200
        assert list_resp.json()["count"] == 0

    def test_create_job_with_nonexistent_project(self, client: TestClient):
        fake_pid = str(uuid.uuid4())
        fake_sid = str(uuid.uuid4())
        fake_cid = str(uuid.uuid4())
        resp = client.post(
            "/api/v1/transformations",
            json={
                "project_id": fake_pid,
                "source_id": fake_sid,
                "configuration_id": fake_cid,
                "output_types": ["summary"],
            },
        )
        assert resp.status_code == 404

    def test_create_job_requires_output_types(self, client: TestClient):
        pid, sid, cid = self._setup_project_source_config(client)
        resp = client.post(
            "/api/v1/transformations",
            json={
                "project_id": pid,
                "source_id": sid,
                "configuration_id": cid,
                "output_types": [],
            },
        )
        assert resp.status_code == 422

    def test_cancel_transformation_job(self, client: TestClient):
        pid, sid, cid = self._setup_project_source_config(client)
        create_resp = client.post(
            "/api/v1/transformations",
            json={
                "project_id": pid,
                "source_id": sid,
                "configuration_id": cid,
                "output_types": ["summary"],
            },
        )
        job_id = create_resp.json()["data"]["id"]
        cancel_resp = client.post(f"/api/v1/transformations/{job_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["data"]["status"] == "cancelled"


# ===========================================================================
# 6. Output + Verification persistence tests
# ===========================================================================

class TestOutputAndVerification:
    """Output and VerificationResult model persistence tests."""

    def _make_job(self, db_session) -> "uuid.UUID":
        """Create a complete chain up to TransformationJob and return the job ID."""
        from app.db.models.user import User
        from app.db.models.project import Project
        from app.db.models.source import Source
        from app.db.models.generation_configuration import GenerationConfiguration
        from app.db.models.transformation_job import TransformationJob

        uid = uuid.uuid4()
        user = User(id=uid, email=f"{uid}@t.com", name="U", role="operator")
        db_session.add(user)
        db_session.flush()

        project = Project(id=uuid.uuid4(), user_id=uid, name="P", description=None)
        db_session.add(project)
        db_session.flush()

        source = Source(id=uuid.uuid4(), project_id=project.id, source_type="text", language="en", status="uploaded")
        db_session.add(source)
        db_session.flush()

        config = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
        db_session.add(config)
        db_session.flush()

        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=project.id,
            source_id=source.id,
            configuration_id=config.id,
            requested_outputs={"output_types": ["summary"]},
            status="queued",
            progress=0,
        )
        db_session.add(job)
        db_session.flush()
        return job.id

    def test_output_persists(self, db_session):
        from app.db.models.output import Output

        job_id = self._make_job(db_session)
        output = Output(
            id=uuid.uuid4(),
            job_id=job_id,
            output_type="summary",
            status="completed",
            text_content="Executive summary content here.",
        )
        db_session.add(output)
        db_session.flush()

        result = db_session.get(Output, output.id)
        assert result is not None
        assert result.text_content == "Executive summary content here."
        assert result.output_type == "summary"

    def test_verification_result_persists(self, db_session):
        from app.db.models.output import Output
        from app.db.models.verification_result import VerificationResult

        job_id = self._make_job(db_session)
        output = Output(id=uuid.uuid4(), job_id=job_id, output_type="summary", status="completed")
        db_session.add(output)
        db_session.flush()

        vr = VerificationResult(
            id=uuid.uuid4(),
            output_id=output.id,
            overall_status="passed",
            grounding_score=0.92,
            consistency_score=0.88,
            claims_checked=10,
            claims_supported=9,
            warnings={},
            details={"method": "cosine"},
        )
        db_session.add(vr)
        db_session.flush()

        result = db_session.get(VerificationResult, vr.id)
        assert result is not None
        assert result.overall_status == "passed"
        assert result.claims_checked == 10
        assert result.claims_supported == 9


# ===========================================================================
# 7. API response format tests
# ===========================================================================

class TestAPIResponseFormat:
    """Verify that all endpoints return the correct standard response envelope."""

    def test_success_envelope_has_required_fields(self, client: TestClient):
        resp = client.post("/api/v1/projects", json={"name": "Format"})
        data = resp.json()
        assert "success" in data
        assert "data" in data
        assert data["success"] is True

    def test_error_response_has_detail_field(self, client: TestClient):
        resp = client.get(f"/api/v1/projects/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert "detail" in resp.json()

    def test_list_response_has_count(self, client: TestClient):
        resp = client.get("/api/v1/projects")
        data = resp.json()
        assert "count" in data
        assert isinstance(data["count"], int)

    def test_project_data_fields_present(self, client: TestClient):
        resp = client.post("/api/v1/projects", json={"name": "Fields"})
        data = resp.json()["data"]
        expected = {"id", "user_id", "name", "description", "created_at", "updated_at"}
        assert expected.issubset(set(data.keys()))

    def test_source_data_fields_present(self, client: TestClient):
        proj = client.post("/api/v1/projects", json={"name": "SrcFields"})
        pid = proj.json()["data"]["id"]
        resp = client.post(
            f"/api/v1/projects/{pid}/sources",
            json={"source_type": "text"},
        )
        data = resp.json()["data"]
        expected = {"id", "project_id", "source_type", "status", "language", "created_at"}
        assert expected.issubset(set(data.keys()))

    def test_configuration_data_fields_present(self, client: TestClient):
        proj = client.post("/api/v1/projects", json={"name": "CfgFields"})
        pid = proj.json()["data"]["id"]
        resp = client.post(
            f"/api/v1/projects/{pid}/configurations",
            json={"language": "English"},
        )
        data = resp.json()["data"]
        expected = {"id", "project_id", "language", "created_at"}
        assert expected.issubset(set(data.keys()))

    def test_transformation_data_fields_present(self, client: TestClient):
        proj = client.post("/api/v1/projects", json={"name": "TJFields"})
        pid = proj.json()["data"]["id"]
        src = client.post(f"/api/v1/projects/{pid}/sources", json={"source_type": "text"})
        sid = src.json()["data"]["id"]
        cfg = client.post(f"/api/v1/projects/{pid}/configurations", json={"language": "English"})
        cid = cfg.json()["data"]["id"]
        resp = client.post(
            "/api/v1/transformations",
            json={"project_id": pid, "source_id": sid, "configuration_id": cid, "output_types": ["summary"]},
        )
        data = resp.json()["data"]
        expected = {"id", "project_id", "source_id", "configuration_id", "status", "progress", "created_at"}
        assert expected.issubset(set(data.keys()))


# ===========================================================================
# 8. Schema import tests
# ===========================================================================

class TestSchemaImports:
    """Verify all Pydantic schemas can be imported without error."""

    def test_project_schemas_importable(self):
        from app.api.v1.schemas.project import (
            ProjectCreate,
            ProjectUpdate,
            ProjectResponse,
        )
        assert ProjectCreate
        assert ProjectUpdate
        assert ProjectResponse

    def test_source_schemas_importable(self):
        from app.api.v1.schemas.source import SourceCreate, SourceResponse
        assert SourceCreate
        assert SourceResponse

    def test_configuration_schemas_importable(self):
        from app.api.v1.schemas.configuration import ConfigurationCreate, ConfigurationResponse
        assert ConfigurationCreate
        assert ConfigurationResponse

    def test_transformation_schemas_importable(self):
        from app.api.v1.schemas.transformation import (
            TransformationJobCreate,
            OutputResponse,
            VerificationResultResponse,
        )
        assert TransformationJobCreate
        assert OutputResponse
        assert VerificationResultResponse

    def test_service_modules_importable(self):
        from app.services import project_service, source_service
        from app.services import configuration_service, transformation_service
        assert project_service
        assert source_service
        assert configuration_service
        assert transformation_service

    def test_db_engine_importable(self):
        from app.db.engine import get_sync_engine, get_async_engine, sync_engine, async_engine
        assert get_sync_engine is not None
        assert get_async_engine is not None
        # Lazy proxies are truthy objects
        assert sync_engine is not None
        assert async_engine is not None

    def test_db_base_importable(self):
        from app.db.base import Base
        assert Base

    def test_all_models_importable(self):
        from app.db.models import (
            User, Project, Source, SourceChunk,
            GenerationConfiguration, TransformationJob,
            Output, VerificationResult,
        )
        assert User
        assert Project
        assert Source
        assert SourceChunk
        assert GenerationConfiguration
        assert TransformationJob
        assert Output
        assert VerificationResult
