"""
TransformIQ Backend — Standard API Response Schemas

All API responses follow these conventions:
- Success: wrapped in a data envelope where appropriate
- Errors: { "detail": "<message>" } compatible with FastAPI defaults
- Health/ready: flat response (no envelope, orchestration-friendly)

These schemas establish the contract for Phase 1.
Detailed domain schemas (Source, Job, Output, etc.) will be added in Phase 2+.
"""
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """
    Standard envelope for paginated or enumerated responses.

    Example:
        {"data": [...], "count": 3}
    """

    data: T
    count: int | None = None


class ErrorDetail(BaseModel):
    """
    Standard error body.

    FastAPI uses {"detail": "..."} by default, so this matches that shape.
    """

    detail: str


class MessageResponse(BaseModel):
    """
    Simple acknowledgement response for operations that don't return data.

    Example:
        {"message": "Job queued successfully"}
    """

    message: str
