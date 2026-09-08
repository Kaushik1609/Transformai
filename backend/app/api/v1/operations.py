"""Phase 12D-G — read-only Security Activity / Operations API.

Exposes bounded, already-redacted security events from the in-process audit
sink (``app.core.audit``) to the authenticated owner only.  These endpoints
are READ-ONLY observability: they never create or mutate state, and they
never return source content, credentials, secrets, raw PII, or events that
belong to other users.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.api.v1.schemas.operations import (
    SecurityEventListResponse,
    SecurityEventResponse,
)
from app.core.audit import security_events
from app.db.models.project import Project
from app.db.session import get_db

router = APIRouter()

MAX_EVENTS_PER_REQUEST = 200
DEFAULT_EVENTS_PER_REQUEST = 50

_BASE_FIELDS = frozenset(
    {
        "event_type",
        "outcome",
        "timestamp",
        "user_id",
        "project_id",
        "source_id",
        "job_id",
        "reason",
    }
)


def _to_response(event: dict) -> SecurityEventResponse:
    """Map an audit record to the response model.

    ``emit_security_event`` stores redacted ``details`` merged FLAT into the
    record top level (e.g. ``scanner``); every non-base key is a detail value
    that was already redacted at emit time.
    """
    base = {k: v for k, v in event.items() if k in _BASE_FIELDS}
    details = {k: v for k, v in event.items() if k not in _BASE_FIELDS}
    return SecurityEventResponse(**base, details=details)


async def _owned_project_ids(
    db: AsyncSession, user_id: uuid.UUID
) -> set[str]:
    """Project IDs owned by ``user_id`` (single-owner project model)."""
    rows = await db.scalars(
        select(Project.id).where(Project.user_id == user_id)
    )
    return {str(value) for value in rows.all()}


@router.get(
    "/operations/security-events",
    response_model=SecurityEventListResponse,
    summary="List bounded security events for the authenticated owner",
)
async def list_security_events(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    project_id: Annotated[
        uuid.UUID | None,
        Query(description="Restrict to a specific project you own."),
    ] = None,
    event_type: Annotated[
        str | None,
        Query(description="Exact event_type filter (bounded)."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_EVENTS_PER_REQUEST, description="Max events returned."),
    ] = DEFAULT_EVENTS_PER_REQUEST,
) -> SecurityEventListResponse:
    """Return only events visible to the authenticated owner.

    A user may see events they initiated (``user_id``) or events that belong
    to projects they own (``project_id``).  Platform-global events with no
    owning user/project are never exposed here.  Responses carry only bounded
    fields that were already redacted at emit time.
    """
    owned_projects = await _owned_project_ids(db, current_user.id)
    if project_id is not None and str(project_id) not in owned_projects:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    me = str(current_user.id)
    events = security_events()
    filtered: list[dict] = []
    for event in sorted(
        events, key=lambda e: e.get("timestamp", ""), reverse=True
    ):
        project = event.get("project_id")
        owned = project is not None and project in owned_projects
        initiated = event.get("user_id") == me
        if not (owned or initiated):
            continue
        if project_id is not None and project != str(project_id):
            continue
        if event_type is not None and event.get("event_type") != event_type:
            continue
        filtered.append(event)
        if len(filtered) >= limit:
            break

    return SecurityEventListResponse(
        data=[_to_response(event) for event in filtered],
        count=len(filtered),
    )


__all__ = ["router"]