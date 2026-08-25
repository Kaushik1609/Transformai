"""Strict validation and grounding checks for provider output."""

from __future__ import annotations

import uuid

from app.content_intelligence.schemas import CanonicalContentPayload


class ContentValidationError(ValueError):
    """Raised when provider output is not safe to persist."""


def validate_payload(payload: dict, chunks: list[dict]) -> CanonicalContentPayload:
    try:
        result = CanonicalContentPayload.model_validate(payload)
    except Exception as exc:
        raise ContentValidationError(f"Invalid canonical content payload: {exc}") from exc

    valid_ids = {chunk["id"] for chunk in chunks}
    if not result.title and not result.summary:
        raise ContentValidationError("Canonical content requires a title or summary.")

    for item_type in (
        "topics", "entities", "key_points", "claims", "statistics", "dates", "recommendations", "source_references"
    ):
        for item in getattr(result, item_type):
            item_ids = set(item.source_chunk_ids)
            if not item_ids.issubset(valid_ids):
                unknown = item_ids - valid_ids
                raise ContentValidationError(f"{item_type} contains unknown source chunk references: {unknown}")

    return result
