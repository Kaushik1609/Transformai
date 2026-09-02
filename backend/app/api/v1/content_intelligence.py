"""Source-scoped Phase 4 content intelligence API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.content_intelligence.schemas import CanonicalContentResponse, ContentIntelligenceResponse
from app.content_intelligence.service import create_pending_analysis_async, get_analysis
from app.db.session import get_db
from app.ingestion.queue import enqueue_content_intelligence, get_content_intelligence_queue
from app.services import source_service

router = APIRouter(prefix="/sources", tags=["content-intelligence"])


def _response(content) -> ContentIntelligenceResponse:
    data = {
        "id": content.id,
        "source_id": content.source_id,
        "project_id": content.project_id,
        "status": content.status,
        "title": content.title,
        "summary": content.summary,
        "metadata": content.content_metadata,
        "topics": content.topics,
        "entities": content.entities,
        "key_points": content.key_points,
        "claims": content.claims,
        "statistics": content.statistics,
        "dates": content.dates,
        "recommendations": content.recommendations,
        "source_references": content.source_references,
        "error_message": content.error_message,
        "created_at": content.created_at,
        "updated_at": content.updated_at,
        "analyzed_at": content.analyzed_at,
    }
    return ContentIntelligenceResponse(data=CanonicalContentResponse.model_validate(data))


async def _owned_source(source_id: uuid.UUID, db: AsyncSession, current_user: CurrentUser):
    source = await source_service.get_source_owned(
        db, source_id=source_id, user_id=current_user.id
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Source {source_id} not found.")
    return source


@router.post(
    "/{source_id}/content-intelligence",
    response_model=ContentIntelligenceResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue content intelligence analysis",
)
async def analyze_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ContentIntelligenceResponse:
    source = await _owned_source(source_id, db, current_user)
    if source.status != "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source must be ready before analysis.")
    content = await create_pending_analysis_async(db, source)
    try:
        enqueue_content_intelligence(source.id, queue=get_content_intelligence_queue())
    except Exception as exc:
        content.status = "failed"
        content.error_message = f"Unable to enqueue analysis: {exc}"
        await db.flush()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Unable to queue analysis.") from exc
    return _response(content)


@router.get(
    "/{source_id}/content-intelligence",
    response_model=ContentIntelligenceResponse,
    summary="Get source content intelligence",
)
async def get_source_analysis(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ContentIntelligenceResponse:
    await _owned_source(source_id, db, current_user)
    content = await get_analysis(db, source_id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content intelligence has not been created.")
    return _response(content)
