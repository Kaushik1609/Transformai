"""
TransformIQ Backend — Source API Router

Endpoints:
    POST   /api/v1/projects/{project_id}/sources
    GET    /api/v1/projects/{project_id}/sources
    GET    /api/v1/sources/{source_id}
    DELETE /api/v1/sources/{source_id}

Phase 2: metadata records only. File upload / extraction is Phase 3.
"""
import uuid
import json

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from starlette.datastructures import UploadFile as StarletteUploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.api.v1.schemas.source import (
    DeleteResponse,
    SourceCreate,
    DirectTextSourceCreate,
    SourceDetailResponse,
    SourceListResponse,
    SourceResponse,
)
from app.core.ratelimit import rate_limit_bucket
from app.db.session import get_db
from app.ingestion.documents import DocumentExtractionError
from app.ingestion.queue import enqueue_source_ingestion, get_ingestion_queue
from app.ingestion.validation import SourceValidationError
from app.services import project_service, source_service

logger = structlog.get_logger(__name__)

# Two separate routers:
#   - project_sources_router: nested under /projects/{project_id}/sources
#   - sources_router: standalone /sources/{source_id}
project_sources_router = APIRouter(tags=["sources"])
sources_router = APIRouter(tags=["sources"])


def _ingestion_error(exc: ValueError) -> HTTPException:
    """Convert deterministic ingestion validation errors to a client error."""
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------------------------------------------------------------------
# Nested under projects
# ---------------------------------------------------------------------------

@project_sources_router.post(
    "/{project_id}/sources",
    response_model=SourceDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a source to a project",
)
async def create_source(
    project_id: uuid.UUID,
    body: SourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(rate_limit_bucket("source_upload")),
) -> SourceDetailResponse:
    # Verify project ownership
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    source = await source_service.create_source(
        db,
        project_id=project_id,
        source_type=body.source_type,
        original_filename=body.original_filename,
        extracted_text=body.extracted_text,
        mime_type=body.mime_type,
        language=body.language,
        metadata=body.metadata,
    )
    return SourceDetailResponse(data=SourceResponse.model_validate(source))


@project_sources_router.post(
    "/{project_id}/sources/text",
    response_model=SourceDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest direct text into a project",
)
async def ingest_direct_text(
    project_id: uuid.UUID,
    body: DirectTextSourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(rate_limit_bucket("source_upload")),
) -> SourceDetailResponse:
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    try:
        source = await source_service.ingest_text_source(
            db,
            project_id=project_id,
            content=body.text.encode("utf-8"),
            source_type="text",
            filename=None,
            mime_type="text/plain",
            language=body.language,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise _ingestion_error(exc) from exc
    return SourceDetailResponse(data=SourceResponse.model_validate(source))


@project_sources_router.post(
    "/{project_id}/sources/file",
    response_model=SourceDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a TXT source file into a project",
)
async def ingest_txt_file(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    language: str = Form(default="en"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(rate_limit_bucket("source_upload")),
) -> SourceDetailResponse:
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    content = await file.read()
    try:
        source = await source_service.ingest_text_source(
            db,
            project_id=project_id,
            content=content,
            source_type="txt",
            filename=file.filename,
            mime_type=file.content_type or "",
            language=language,
            metadata=None,
        )
    except ValueError as exc:
        raise _ingestion_error(exc) from exc
    return SourceDetailResponse(data=SourceResponse.model_validate(source))


@project_sources_router.post(
    "/{project_id}/sources/document",
    response_model=SourceDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a PDF or DOCX source file into a project",
)
async def ingest_document_file(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    language: str = Form(default="en"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(rate_limit_bucket("source_upload")),
) -> SourceDetailResponse:
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )

    filename = file.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    source_type = extension
    if source_type not in {"pdf", "docx"}:
        raise _ingestion_error(ValueError("Only PDF and DOCX files are supported."))

    content = await file.read()
    try:
        source = await source_service.ingest_document_source(
            db,
            project_id=project_id,
            content=content,
            source_type=source_type,
            filename=file.filename,
            mime_type=file.content_type or "",
            language=language,
        )
    except (DocumentExtractionError, ValueError) as exc:
        raise _ingestion_error(exc) from exc
    return SourceDetailResponse(data=SourceResponse.model_validate(source))


@project_sources_router.post(
    "/{project_id}/sources/async",
    response_model=SourceDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue source ingestion",
)
async def queue_source_ingestion(
    project_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(rate_limit_bucket("source_upload")),
) -> SourceDetailResponse:
    """Store a source and enqueue extraction without processing in HTTP."""
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        payload = await request.json()
        text = payload.get("text")
        if not isinstance(text, str):
            raise _ingestion_error(ValueError("JSON body must contain text."))
        content = text.encode("utf-8")
        source_type = "text"
        filename = "original.txt"
        mime_type = "text/plain"
        language = payload.get("language", "en")
        metadata = payload.get("metadata")
    elif content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, StarletteUploadFile):
            raise _ingestion_error(ValueError("Multipart body must contain a file."))
        filename = upload.filename or ""
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if extension not in {"txt", "pdf", "docx"}:
            raise _ingestion_error(ValueError("Only TXT, PDF, and DOCX files are supported."))
        content = await upload.read()
        source_type = extension
        mime_type = upload.content_type or ""
        language = str(form.get("language", "en"))
        metadata = None
    else:
        raise _ingestion_error(ValueError("Use JSON or multipart form data."))

    try:
        source = await source_service.create_pending_source(
            db,
            project_id=project_id,
            content=content,
            source_type=source_type,
            filename=filename,
            mime_type=mime_type,
            language=language,
            metadata=metadata,
        )
        enqueue_source_ingestion(source.id, queue=get_ingestion_queue())
    except (SourceValidationError, ValueError) as exc:
        raise _ingestion_error(exc) from exc
    return SourceDetailResponse(data=SourceResponse.model_validate(source))


@project_sources_router.get(
    "/{project_id}/sources",
    response_model=SourceListResponse,
    summary="List sources for a project",
)
async def list_sources(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> SourceListResponse:
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    sources = await source_service.list_sources(db, project_id=project_id)
    return SourceListResponse(
        data=[SourceResponse.model_validate(s) for s in sources],
        count=len(sources),
    )


# ---------------------------------------------------------------------------
# Standalone source endpoints
# ---------------------------------------------------------------------------

@sources_router.get(
    "/{source_id}",
    response_model=SourceDetailResponse,
    summary="Get a source by ID",
)
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> SourceDetailResponse:
    # Authorization resolved at the database level (Source → Project → user).
    source = await source_service.get_source_owned(
        db, source_id=source_id, user_id=current_user.id
    )
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id} not found.",
        )
    return SourceDetailResponse(data=SourceResponse.model_validate(source))


@sources_router.delete(
    "/{source_id}",
    response_model=DeleteResponse,
    summary="Delete a source",
)
async def delete_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> DeleteResponse:
    # Authorization resolved at the database level (Source → Project → user).
    source = await source_service.get_source_owned(
        db, source_id=source_id, user_id=current_user.id
    )
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id} not found.",
        )
    await source_service.delete_source(db, source=source)
    return DeleteResponse(message=f"Source {source_id} deleted successfully.")
