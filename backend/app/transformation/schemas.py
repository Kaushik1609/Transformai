"""Typed contracts for the Phase 6 transformation engine."""

from __future__ import annotations

from typing import Any, TypedDict

from app.rag.schemas import RAGContext


# ---------------------------------------------------------------------------
# LangGraph workflow state
# ---------------------------------------------------------------------------

class TransformationState(TypedDict, total=False):
    """State threaded through the LangGraph transformation workflow.

    The orchestrator owns workflow coordination; each node reads/writes only
    the fields it is responsible for.  DB access is injected at graph build
    time (see app.transformation.graph).
    """
    job_id: str
    project_id: str
    source_id: str
    configuration_id: str
    requested_output_types: list[str]

    # Canonical content (Phase 4), serialized for generators.
    canonical: dict[str, Any]

    # User configuration (audience, tone, language, detail, objective...).
    config: dict[str, Any]

    # Optional RAG context (Phase 5), populated only when retrieval is needed.
    rag_context: RAGContext | None
    rag_required: bool

    # Results of the generate stage: one entry per requested output.
    outputs: list[dict[str, Any]]

    # Controlled errors accumulated during the run (do not corrupt source).
    errors: list[dict[str, Any]]

    # Verification hook result (Phase 6 returns a pending Phase 8 marker).
    verification_hooks: list[dict[str, Any]]

    # Canonical content availability gate.
    canonical_ready: bool
    canonical_missing: bool
