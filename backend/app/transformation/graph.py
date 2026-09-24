"""LangGraph transformation workflow for Phase 6.

Stage flow:
    load_input
      -> retrieve_if_required (only when RAG is required)
      -> generate
      -> validate
      -> verify_hook
      -> finalize

The orchestrator owns coordination; the graph nodes implement each stage.
DB access (authoritative state) is injected through TransformationDependencies
so the same workflow runs from the worker and from tests.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.canonical_content import CanonicalContent
from app.db.models.generation_configuration import GenerationConfiguration
from app.db.models.output import Output
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.db.models.transformation_job import TransformationJob
from app.db.models.verification_result import VerificationResult
from app.core.config import settings
from app.rag.query import formulate_retrieval_query
from app.rag.service import RAGService
from app.transformation.artifacts import (
    get_storage,
    save_output_artifact,
    sha256_hex,
)
from app.transformation.brief import build_canonical_brief
from app.transformation.output_schemas import (
    Infographic,
    PresentationStructure,
    VideoPackage,
)
from app.transformation.output_schemas.parser import OutputSchemaError
from app.transformation.security import BLOCKED, SecurityVerdict, validate_output
from app.transformation.render.infographic import (
    INF_PNG_MIME_TYPE,
    PDF_MIME_TYPE,
    render_infographic_pdf,
    render_infographic_png,
)
from app.transformation.render.pptx import PPTX_MIME_TYPE, render_presentation
from app.transformation.render.video import (
    SRT_MIME_TYPE,
    render_video_package_pdf,
    render_video_package_srt,
)
from app.transformation.schemas import TransformationState
from app.transformation.verification import VerificationHook, run_verification_hook


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_MEDIA_OUTPUT_TYPES = frozenset({"presentation", "infographic", "video"})
_STRUCTURED_OUTPUT_TYPES = frozenset({"advisory"})

# Phase 11H: neutral schema-feedback line injected into the shared prompt
# boundary during bounded regeneration.  It is transient (never persisted) and
# carries no source content or secrets.
_REGEN_FEEDBACK = (
    "Your previous response was rejected because it did not conform to the "
    "requested JSON structure. Return a single valid JSON object that exactly "
    "matches the requested fields and types."
)


def _classify_output(output_type: str) -> str:
    """Classify an output for orchestration planning.

    text       — plain, mostly prose outputs (LLM -> text).
    structured — typed structured content (LLM -> validated model).
    media      — structured content rendered deterministically to a binary
                 artifact by a dedicated renderer (LLM -> model -> render).
    """
    if output_type in _MEDIA_OUTPUT_TYPES:
        return "media"
    if output_type in _STRUCTURED_OUTPUT_TYPES:
        return "structured"
    return "text"


def _safe_error_message(exc: BaseException, limit: int = 4000) -> str:
    """Return a bounded, credential-redacted exception snapshot for persistence.

    Phase 11E-F: exceptions are surfaced to clients (erroneously) if they embed
    raw provider text, so we redact credentials and cap the length before it is
    stored on an Output or included in the State errors list.  The original
    exception is always preserved for local logging; only the persisted string
    is sanitized here.
    """
    from app.transformation.llm.resilience import _redact

    return _redact(str(exc) or exc.__class__.__name__)[:limit]


@dataclass
class TransformationDependencies:
    """Dependencies injected into the transformation workflow."""

    session: Session
    rag_service: RAGService | None = None
    verification_hook: VerificationHook | None = None
    get_generator: Callable[[str], Any | None] | None = None
    rag_mode: str = "auto"  # "auto" | "always-on" | "off"
    llm_provider: Any | None = None
    storage: Any | None = None
    # Phase 11D: optional override of the per-transformation execution budget.
    transformation_job_timeout: int | None = None
    # Optional overrides for deterministic tests.
    requested_output_types_override: list[str] | None = None
    rag_required_override: bool | None = None
    # Phase 11H: optional overrides for L5 output security (None = use settings).
    output_security_enabled: bool | None = None
    output_regen_budget: int | None = None

    def __post_init__(self) -> None:
        if self.rag_service is None:
            self.rag_service = RAGService()
        if self.get_generator is None:
            from app.transformation.generators import get_generator as _registry

            provider = self.llm_provider
            self.get_generator = lambda output_type: _registry(
                output_type, llm_provider=provider
            )
        if self.storage is None:
            self.storage = get_storage()


class TransformationWorkflow:
    """Implements each LangGraph node for the transformation pipeline."""

    def __init__(self, deps: TransformationDependencies):
        self.deps = deps

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def load_input(self, state: TransformationState) -> TransformationState:
        session = self.deps.session
        job = session.get(TransformationJob, uuid.UUID(state["job_id"]))
        if job is None:
            raise ValueError(f"Transformation job {state['job_id']} was not found.")

        # Transition to running as soon as a worker begins.
        job.status = "running"
        job.started_at = _utcnow()

        requested = self.deps.requested_output_types_override or list(
            job.requested_outputs.get("output_types", []) if job.requested_outputs else []
        )

        project_id = str(job.project_id)
        source_id = str(job.source_id) if job.source_id is not None else None
        configuration_id = str(job.configuration_id)

        # Load user configuration for generation context.
        config: dict[str, Any] = {}
        config_record = session.get(GenerationConfiguration, job.configuration_id)
        if config_record is not None:
            config = {
                "target_audience": config_record.target_audience,
                "tone": config_record.tone,
                "language": config_record.language,
                "detail_level": config_record.detail_level,
                "communication_objective": config_record.communication_objective,
                "content_style": config_record.content_style,
                "custom_instructions": config_record.custom_instructions,
            }

        session.flush()
        return {
            "job_id": state["job_id"],
            "project_id": project_id,
            "source_id": source_id,
            "configuration_id": configuration_id,
            "requested_output_types": requested,
            "config": config,
            "prompt": job.prompt,
            "canonical_ready": False,
            "canonical_missing": False,
            "outputs": [],
            "errors": [],
            "verification_hooks": [],
            "rag_required": self._rag_required(config, job),
        }

    def _rag_required(self, config: dict[str, Any], job: TransformationJob) -> bool:
        if self.deps.rag_required_override is not None:
            return self.deps.rag_required_override
        mode = self.deps.rag_mode
        if mode == "always-on":
            return True
        if mode == "off":
            return False
        # auto: use RAG for detailed/large-format or decision-support outputs
        meta = job.requested_outputs or {}
        if meta.get("use_rag") is True:
            return True
        objective = (config.get("communication_objective") or "").lower()
        return objective in {"decision support", "education"}

    def load_canonical_content(self, state: TransformationState) -> TransformationState:
        session = self.deps.session
        # Phase 15 prompt-only mode: no source exists, so there is no canonical
        # content to load. The operator prompt (carried in state) drives the
        # generation instead; canonical readiness is satisfied with an empty
        # canonical payload so the graph continues through the normal pipeline.
        if not state.get("source_id"):
            return {"canonical": {}, "canonical_ready": True, "canonical_missing": False}

        result = session.execute(
            select(CanonicalContent).where(CanonicalContent.source_id == uuid.UUID(state["source_id"]))
        ).scalar_one_or_none()

        canonical: dict[str, Any] = {}
        if result is None:
            state["canonical_missing"] = True
            state["canonical_ready"] = False
            state["errors"] = [
                {
                    "stage": "load_canonical_content",
                    "message": "Canonical content is missing for the source.",
                }
            ]
            return state

        if result.status != "completed":
            state["canonical_missing"] = True
            state["canonical_ready"] = False
            state["errors"] = [
                {
                    "stage": "load_canonical_content",
                    "message": (
                        f"Canonical content is not completed (status: {result.status!r}). "
                        "Run content intelligence before transforming."
                    ),
                }
            ]
            return state

        canonical = {
            "id": str(result.id),
            "source_id": str(result.source_id),
            "title": result.title,
            "summary": result.summary,
            "topics": result.topics or [],
            "entities": result.entities or [],
            "key_points": result.key_points or [],
            "claims": result.claims or [],
            "statistics": result.statistics or [],
            "dates": result.dates or [],
            "recommendations": result.recommendations or [],
            "source_references": result.source_references or [],
        }
        return {"canonical": canonical, "canonical_ready": True, "canonical_missing": False}

    def retrieve_if_required(self, state: TransformationState) -> TransformationState:
        """Retrieve RAG context only when required by the transformation."""
        if not state.get("canonical_ready"):
            return {}
        if not state.get("rag_required"):
            return {}
        if not state.get("source_id"):
            # Prompt-only mode has no source to retrieve evidence from.
            return {}

        session = self.deps.session
        source_id = uuid.UUID(state["source_id"])
        project_id = uuid.UUID(state["project_id"])
        canonical = state.get("canonical", {})
        config = state.get("config", {})
        # Task-aware retrieval query (compact, source-grounded) rather than a
        # raw full-source summary. Falls back to a small stable token so
        # retrieval is never skipped or duplicated silently.
        query = formulate_retrieval_query(canonical, config)
        task_context = "; ".join(
            f"{k}: {v}" for k, v in config.items() if v
        )

        try:
            context = self.deps.rag_service.retrieve_context_for_source(
                session,
                source_id,
                query,
                project_id=project_id,
                top_k=5,
                task_context=task_context or None,
            )
            return {"rag_context": context}
        except Exception as exc:  # retrieval is best-effort; never corrupt source
            import structlog
            _logger = structlog.get_logger(__name__)
            _logger.error(
                "RAG retrieval failed unexpectedly",
                error=str(exc),
                exc_type=type(exc).__name__,
                source_id=str(source_id),
                project_id=str(project_id),
            )
            return {
                "errors": [
                    {
                        "stage": "retrieve_if_required",
                        "message": f"RAG retrieval failed: {type(exc).__name__}: {exc}",
                    }
                ]
            }

    def build_brief(self, state: TransformationState) -> TransformationState:
        """Build the shared canonical semantic brief once per transformation.

        The brief is a deterministic, bounded, output-agnostic representation of
        the trusted canonical content plus bounded RAG evidence.  It is built a
        single time and reused by every generator, so the full canonical/RAG
        payload is not independently re-formatted/re-tokenized per output.  No
        LLM is used; no facts are invented.
        """
        if not state.get("canonical_ready"):
            return {}
        canonical = state.get("canonical", {})
        config = state.get("config", {})
        rag_context = state.get("rag_context")
        brief = build_canonical_brief(
            canonical,
            rag_context,
            config,
            operator_prompt=state.get("prompt"),
        )

        # Persist a reference to the shared brief on the job so it is durable
        # and inspectable (bounded by RAG_MAX_CONTEXT_CHARS).
        has_job_id = state.get("job_id")
        if has_job_id:
            try:
                job = self.deps.session.get(TransformationJob, uuid.UUID(has_job_id))
                if job is not None:
                    import hashlib
                    meta = dict(job.requested_outputs or {})
                    meta["brief"] = brief
                    if rag_context and getattr(rag_context, "citations", None):
                        meta["evidence_citations"] = [
                            {
                                "source_id": str(c.source_id),
                                "chunk_id": str(c.chunk_id),
                                "chunk_index": c.chunk_index,
                                "content_hash": (
                                    hashlib.sha256(c.evidence.encode("utf-8")).hexdigest()[:16]
                                    if c.evidence else None
                                ),
                                "relevance_score": c.relevance_score,
                                "excerpt": c.evidence[:250] if c.evidence else "",
                            }
                            for c in rag_context.citations
                        ]
                    job.requested_outputs = meta
                    self.deps.session.flush()
            except (ValueError, TypeError):
                pass
        return {"brief": brief}

    def plan_outputs(self, state: TransformationState) -> TransformationState:
        """Plan/fan-out: resolve generators, classify outputs, pre-create output rows.

        Establishes an explicit planning boundary before generation.  Each
        requested output type is resolved against the generator registry; known
        types get a persisted ``Output`` row in ``pending`` state, while
        unknown types are recorded as ``failed`` (so unknown-output failure stays
        isolated and does not abort the rest).  Output classification
        (``text`` / ``structured`` / ``media``) is stored server-side.
        """
        session = self.deps.session
        job_id = uuid.UUID(state["job_id"])
        requested = state.get("requested_output_types", [])

        # Phase 11E — idempotent planning.  If a prior (partially committed) run
        # already persisted an Output row for this job/output_type, reuse it
        # instead of creating a duplicate.  This prevents duplicate logical
        # outputs (and duplicate artifacts) when the same job is retried by the
        # worker/graph after an earlier partial commit.
        existing = {
            o.output_type: o
            for o in session.execute(select(Output).where(Output.job_id == job_id)).scalars().all()
        }

        outputs: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = list(state.get("errors", []))

        for output_type in requested:
            generator = self.deps.get_generator(output_type) if self.deps.get_generator else None
            existing_output = existing.get(output_type)
            if existing_output is not None and existing_output.status == "completed":
                # Already finalized in a prior run; treat as an already-complete
                # sibling so a retry never re-plans or re-generates it.  Carry its
                # persisted content forward so the downstream validate/verify
                # stages see a real completed output (never a fabricated one).
                outputs.append(
                    {
                        "output_id": str(existing_output.id),
                        "output_type": output_type,
                        "status": "completed",
                        "class": _classify_output(output_type),
                        "structured_content": existing_output.structured_content,
                        "text_content": existing_output.text_content,
                    }
                )
                continue
            output = existing_output or Output(
                id=uuid.uuid4(),
                job_id=job_id,
                output_type=output_type,
                status="pending",
                created_at=_utcnow(),
            )
            if existing_output is None:
                session.add(output)
                session.flush()

            if generator is None:
                output.status = "failed"
                output.error_message = f"No generator registered for output type {output_type!r}."
                errors.append(
                    {
                        "stage": "plan",
                        "output_type": output_type,
                        "message": output.error_message,
                    }
                )
                session.flush()
                outputs.append(
                    {
                        "output_id": str(output.id),
                        "output_type": output_type,
                        "status": "failed",
                        "class": "unknown",
                    }
                )
                continue

            outputs.append(
                {
                    "output_id": str(output.id),
                    "output_type": output_type,
                    "status": "pending",
                    "class": _classify_output(output_type),
                }
            )

        return {"outputs": outputs, "errors": errors}

    def generate(self, state: TransformationState) -> TransformationState:
        """Execute each planned (pending) output independently.

        Each pending output transitions ``pending -> running -> completed|failed``.
        Generation is isolated per output so a single failure never prevents the
        remaining outputs from executing (partial success is preserved).  Job
        progress is updated incrementally and per-output timing/stage metadata is
        recorded server-side.  A per-output savepoint keeps a persistence/flush
        failure from erasing previously successful sibling outputs.

        Phase 11D: per-output resilience metadata (from the ProviderManager, when
        one is injected) is persisted under ``output_metadata["resilience"]``, and
        pending outputs are not started after the configured transformation job
        budget (``TRANSFORMATION_JOB_TIMEOUT``) has elapsed — a soft execution
        guard that keeps a long provider tail from monopolizing the worker.
        """
        session = self.deps.session
        if not state.get("canonical_ready"):
            return {}

        canonical = state["canonical"]
        config = state.get("config", {})
        rag_context = state.get("rag_context")
        brief = state.get("brief")

        planned: list[dict[str, Any]] = list(state.get("outputs", []))
        outputs: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = list(state.get("errors", []))

        job = session.get(TransformationJob, uuid.UUID(state["job_id"]))
        total = len(planned)
        resolved = 0

        job_budget = getattr(
            self.deps, "transformation_job_timeout", None
        )
        if job_budget is None:
            job_budget = getattr(settings, "TRANSFORMATION_JOB_TIMEOUT", 600)
        gen_started = time.monotonic()

        for plan_entry in planned:
            output_type = plan_entry["output_type"]
            # Unknown / already-failed planned outputs pass through untouched.
            if plan_entry.get("status") != "pending":
                outputs.append(plan_entry)
                resolved += 1
                self._update_job_progress(job, resolved, total)
                continue

            # Phase 11D: if the transformation execution budget has elapsed, mark
            # remaining pending outputs as failed rather than starting new
            # provider calls that could exhaust the worker's RQ hard timeout.
            if not (time.monotonic() - gen_started) < job_budget:
                output = session.get(Output, uuid.UUID(plan_entry["output_id"]))
                if output is not None:
                    output.status = "failed"
                    output.error_message = (
                        f"Transformation job budget ({job_budget}s) exceeded; output "
                        f"{output_type!r} not started."
                    )
                    session.flush()
                errors.append(
                    {
                        "stage": "generate",
                        "output_type": output_type,
                        "message": f"Transformation job budget ({job_budget}s) exceeded.",
                    }
                )
                outputs.append(
                    {
                        "output_id": plan_entry["output_id"],
                        "output_type": output_type,
                        "status": "failed",
                        "class": plan_entry.get("class", _classify_output(output_type)),
                    }
                )
                resolved += 1
                self._update_job_progress(job, resolved, total)
                continue

            output = session.get(Output, uuid.UUID(plan_entry["output_id"]))
            if output is None:
                resolved += 1
                self._update_job_progress(job, resolved, total)
                continue

            start = _utcnow()

            # A per-output savepoint gives strict persistence isolation: if the
            # generator/persist/flush for THIS output fails at the DB level
            # (e.g. IntegrityError), we roll back only that output's nested
            # transaction instead of poisoning the shared worker transaction and
            # erasing previously successful sibling outputs.
            try:
                output.status = "running"
                output.output_metadata = {
                    **(output.output_metadata or {}),
                    "started_at": start.isoformat(),
                    "stage": "generate",
                }
                session.flush()

                nested = session.begin_nested()
                try:
                    generator = (
                        self.deps.get_generator(output_type)
                        if self.deps.get_generator
                        else None
                    )
                    if generator is None:
                        raise ValueError(
                            f"No generator registered for output type {output_type!r}."
                        )

                    # Phase 11H bounded regeneration.  Retry ONLY when the
                    # model's output fails SCHEMA validation (OutputSchemaError);
                    # provider failures and verification warnings never trigger
                    # regeneration.  Budget 0 (default) = exact legacy behavior.
                    regen_budget = getattr(self.deps, "output_regen_budget", None)
                    if regen_budget is None:
                        regen_budget = getattr(settings, "OUTPUT_REGEN_BUDGET", 0)
                        if not isinstance(regen_budget, int) or regen_budget < 0:
                            regen_budget = 0
                    regen_attempts = 0
                    generation_config: dict[str, Any] = config
                    generated: dict[str, Any] | None = None
                    while True:
                        try:
                            generated = generator.generate(
                                canonical=canonical,
                                config=generation_config,
                                rag_context=rag_context,
                                brief=brief,
                            )
                            break
                        except OutputSchemaError:
                            if regen_attempts >= regen_budget:
                                raise
                            regen_attempts += 1
                            generation_config = {
                                **config,
                                "regen_feedback": _REGEN_FEEDBACK,
                                "regen_attempt": regen_attempts,
                            }
                    if generated is None:
                        raise ValueError(
                            f"Generator produced no output for {output_type!r}."
                        )

                    # Phase 11H — L5 output security (post schema-parse, before
                    # rendering/persistence).  A blocked verdict is an
                    # output-local failure; warnings are recorded but do not stop
                    # processing.  Verdict metadata contains only codes, severities
                    # and field names — never source text or secrets.
                    security_enabled = getattr(
                        self.deps, "output_security_enabled", None
                    )
                    if security_enabled is None:
                        security_enabled = bool(
                            getattr(settings, "OUTPUT_SECURITY_ENABLED", True)
                        )
                    security_verdict: SecurityVerdict | None = None
                    if security_enabled:
                        security_verdict = validate_output(output_type, generated)
                        if security_verdict.status == BLOCKED:
                            raise ValueError(
                                "L5 output security validation failed: "
                                f"{security_verdict.summary}"
                            )

                    text_content = generated.get("text", "")
                    if not isinstance(text_content, str) or not text_content.strip():
                        raise ValueError("Generator produced empty text content.")

                    output.structured_content = generated
                    output.text_content = text_content
                    output.mime_type = generated.get("mime_type") or "text/plain"
                    security_meta: dict[str, Any] | None = None
                    if security_verdict is not None:
                        security_meta = {
                            "status": security_verdict.status,
                            "codes": security_verdict.codes,
                            "reasons": [
                                {
                                    "code": r.code,
                                    "severity": r.severity,
                                    "field": r.field,
                                }
                                for r in security_verdict.reasons
                            ],
                            "regenerations": regen_attempts,
                        }
                    output.output_metadata = {
                        **(output.output_metadata or {}),
                        "provider": "phase7",
                        "generator": type(generator).__name__,
                    }
                    if security_meta is not None:
                        output.output_metadata["security"] = security_meta
                    self._persist_output_artifact(
                        state, output, generated,
                        project_id=uuid.UUID(state["project_id"]),
                        job_id=uuid.UUID(state["job_id"]),
                    )
                    # Phase 11E-D — artifact completion gating.  A media output is
                    # only completed once its binary artifact has been rendered
                    # and persisted (a storage key is required).  This invariant
                    # guarantees "generation succeeds + rendering succeeds +
                    # persistence succeeds -> completed" and treats a missing
                    # artifact as a per-output failure, never a job-level abort.
                    if plan_entry.get("class") == "media" and not output.storage_key:
                        raise RuntimeError(
                            f"Media output {output_type!r} completed without a "
                            "persisted artifact (storage_key missing)."
                        )
                    completed_at = _utcnow()
                    resilience_meta = self._resilience_metadata()
                    output.output_metadata = {
                        **(output.output_metadata or {}),
                        "stage": "render",
                        "completed_at": completed_at.isoformat(),
                        "duration_ms": int((completed_at - start).total_seconds() * 1000),
                    }
                    if resilience_meta:
                        output.output_metadata["resilience"] = resilience_meta
                    output.status = "completed"
                    session.flush()
                    nested.commit()
                except Exception:
                    nested.rollback()
                    raise

                outputs.append(
                    {
                        "output_id": str(output.id),
                        "output_type": output_type,
                        "status": "completed",
                        "structured_content": generated,
                        "text_content": text_content,
                        "class": plan_entry.get("class", _classify_output(output_type)),
                    }
                )
            except Exception as exc:
                failed_at = _utcnow()
                # Re-fetch the output after a rollback; the outer transaction is
                # still usable so the failure is recorded without erasing siblings.
                failed_output = session.get(Output, uuid.UUID(plan_entry["output_id"]))
                if failed_output is not None:
                    failed_output.status = "failed"
                    failed_output.error_message = _safe_error_message(exc)
                    resilience_meta = self._resilience_metadata()
                    failed_output.output_metadata = {
                        **(failed_output.output_metadata or {}),
                        "stage": "generate",
                        "failed_at": failed_at.isoformat(),
                        "duration_ms": int((failed_at - start).total_seconds() * 1000),
                    }
                    if resilience_meta:
                        failed_output.output_metadata["resilience"] = resilience_meta
                    try:
                        session.flush()
                    except Exception:
                        pass
                errors.append(
                    {
                        "stage": "generate",
                        "output_type": output_type,
                        "message": _safe_error_message(exc),
                    }
                )
                outputs.append(
                    {
                        "output_id": plan_entry["output_id"],
                        "output_type": output_type,
                        "status": "failed",
                        "class": plan_entry.get("class", _classify_output(output_type)),
                    }
                )
            resolved += 1
            self._update_job_progress(job, resolved, total)

        return {"outputs": outputs, "errors": errors}

    def _resilience_metadata(self) -> dict[str, Any] | None:
        """Read bounded, redacted Phase 11D resilience metadata from the provider.

        Only present when a resilient ProviderManager is injected; safe for raw
        providers (FakeLLMProvider, stubs) which expose no such attribute.

        Phase 11E-F: the returned dict is strictly bounded to the enumerable
        allowlist below, every string value is run through a credential redactor,
        and no stack traces / raw provider credentials / probe objects can leak.
        """
        provider = getattr(self.deps, "llm_provider", None)
        meta = getattr(provider, "last_metadata", None)
        if not isinstance(meta, dict) or not meta:
            return None
        # Never persist secrets/probes; keep only enumerable bounded fields.
        allowed = (
            "provider",
            "model",
            "attempts",
            "max_attempts",
            "retryable",
            "last_error_type",
            "last_error_message",
            "last_attempt_at",
            "latency_ms",
            "retried",
            "used_fallback",
            "final_status",
        )
        from app.transformation.llm.resilience import _redact

        def _safe(v: Any) -> Any:
            if isinstance(v, str):
                return _redact(v)[:4000]
            if isinstance(v, (int, float, bool)) or v is None:
                return v
            if isinstance(v, list):
                # Bounded retry trace (ProviderManager caps it); sanitize entries.
                return [_safe(i) if isinstance(i, (str, int, float, bool)) or i is None else i for i in v[:25]]
            return None  # drop arbitrary nested structures to stay bounded

        safe: dict[str, Any] = {}
        for key in allowed:
            if key not in meta:
                continue
            cleaned = _safe(meta[key])
            if cleaned is not None or key == "retried":
                safe[key] = cleaned if cleaned is not None else []
        return safe

    def _update_job_progress(
        self,
        job: "TransformationJob | None",
        resolved: int,
        total: int,
    ) -> None:
        """Update job progress monotonically within 0..100 based on resolved outputs."""
        if job is None or total <= 0:
            return
        pct = int(round(resolved * 100 / total))
        if pct > job.progress:
            job.progress = min(100, pct)
            try:
                self.deps.session.flush()
            except Exception:
                pass

    def _artifact_persisted(self, output: Output, marker_key: str) -> bool:
        """Phase 11E — idempotent artifact persistence guard.

        Returns True when this output's artifacts were already successfully
        rendered and stored on a prior attempt (detected via an existing primary
        ``storage_key`` plus a companion-marker in ``output_metadata``).  Reusing
        the existing keys — instead of re-rendering/re-writing — prevents
        duplicate artifacts when the same output is retried by the worker/graph.
        """
        if not output.storage_key:
            return False
        return (output.output_metadata or {}).get(marker_key) is not None

    def _persist_output_artifact(
        self,
        state: TransformationState,
        output: Output,
        generated: dict[str, Any],
        *,
        project_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> None:
        """Render and store binary artifacts for completed outputs.

        Presentation outputs produce a real PPTX; infographic outputs produce a
        real PNG (primary artifact) plus a PDF (sibling artifact); video
        outputs produce a structured video-package PDF (primary artifact) plus
        an SRT subtitle file (sibling artifact).  All other output types are
        persisted entirely in the `outputs` table.  Raises on a
        render/persist failure so the caller's existing generate-stage error
        handling records a controlled per-output failure without destroying
        other outputs in the same job.
        """
        if output.output_type == "presentation":
            self._persist_presentation_artifact(
                state, output, generated,
                project_id=project_id,
                job_id=job_id,
            )
            return
        if output.output_type == "infographic":
            self._persist_infographic_artifact(
                state, output, generated,
                project_id=project_id,
                job_id=job_id,
            )
            return
        if output.output_type == "video":
            self._persist_video_artifact(
                state, output, generated,
                project_id=project_id,
                job_id=job_id,
            )
            return

    def _persist_presentation_artifact(
        self,
        state: TransformationState,
        output: Output,
        generated: dict[str, Any],
        *,
        project_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> None:
        """Render and store a PPTX artifact for a completed presentation output."""
        if self._artifact_persisted(output, "artifact") and output.mime_type == PPTX_MIME_TYPE:
            return  # Phase 11E: artifact already persisted on a prior attempt
        structure = PresentationStructure.model_validate(generated)
        pptx_bytes = render_presentation(structure)
        key = save_output_artifact(
            project_id=project_id,
            job_id=job_id,
            output_id=output.id,
            mime_type=PPTX_MIME_TYPE,
            content=pptx_bytes,
            storage=self.deps.storage,
        )
        output.mime_type = PPTX_MIME_TYPE
        output.storage_key = key
        output.output_metadata = {
            **(output.output_metadata or {}),
            "artifact": "pptx",
            "bytes": len(pptx_bytes),
            "artifact_sha256": sha256_hex(pptx_bytes),
        }

    def _persist_infographic_artifact(
        self,
        state: TransformationState,
        output: Output,
        generated: dict[str, Any],
        *,
        project_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> None:
        """Render and store PNG (primary) and PDF (sibling) infographic artifacts.

        The PNG image is the primary artifact reflected in ``storage_key`` and
        ``mime_type``; the PDF twin is saved at a sibling storage key recorded
        in ``output_metadata["pdf_storage_key"]`` so both PRD target formats
        (Image/PDF) are preserved.
        """
        if self._artifact_persisted(output, "pdf_storage_key"):
            return  # Phase 11E: PNG + PDF pair already persisted on a prior attempt
        infographic = Infographic.model_validate(generated)
        pdf_bytes = render_infographic_pdf(infographic)
        png_bytes = render_infographic_png(infographic)
        png_key = save_output_artifact(
            project_id=project_id,
            job_id=job_id,
            output_id=output.id,
            mime_type=INF_PNG_MIME_TYPE,
            content=png_bytes,
            storage=self.deps.storage,
        )
        pdf_key = save_output_artifact(
            project_id=project_id,
            job_id=job_id,
            output_id=output.id,
            mime_type=PDF_MIME_TYPE,
            content=pdf_bytes,
            storage=self.deps.storage,
        )
        output.mime_type = INF_PNG_MIME_TYPE
        output.storage_key = png_key
        output.output_metadata = {
            **(output.output_metadata or {}),
            "artifact": "infographic",
            "pdf_storage_key": pdf_key,
            "png_bytes": len(png_bytes),
            "pdf_bytes": len(pdf_bytes),
            "artifact_sha256": sha256_hex(png_bytes),
            "pdf_sha256": sha256_hex(pdf_bytes),
        }

    def _persist_video_artifact(
        self,
        state: TransformationState,
        output: Output,
        generated: dict[str, Any],
        *,
        project_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> None:
        """Render and store the structured video package PDF (primary) and SRT (sibling).

        The video package document is the PRD-defined MVP video deliverable (a
        structured document, not a playable MP4).  The PDF is the primary
        artifact reflected in ``storage_key`` and ``mime_type``; the SRT
        subtitle companion is saved at a sibling storage key recorded in
        ``output_metadata["subtitle_storage_key"]`` so both target formats are
        preserved.
        """
        if self._artifact_persisted(output, "subtitle_storage_key"):
            return  # Phase 11E: PDF + SRT pair already persisted on a prior attempt
        video_package = VideoPackage.model_validate(generated)
        pdf_bytes = render_video_package_pdf(video_package)
        srt_bytes = render_video_package_srt(video_package)
        pdf_key = save_output_artifact(
            project_id=project_id,
            job_id=job_id,
            output_id=output.id,
            mime_type=PDF_MIME_TYPE,
            content=pdf_bytes,
            storage=self.deps.storage,
        )
        srt_key = save_output_artifact(
            project_id=project_id,
            job_id=job_id,
            output_id=output.id,
            mime_type=SRT_MIME_TYPE,
            content=srt_bytes,
            storage=self.deps.storage,
        )
        output.mime_type = PDF_MIME_TYPE
        output.storage_key = pdf_key
        output.output_metadata = {
            **(output.output_metadata or {}),
            "artifact": "video",
            "subtitle_storage_key": srt_key,
            "pdf_bytes": len(pdf_bytes),
            "srt_bytes": len(srt_bytes),
            "artifact_sha256": sha256_hex(pdf_bytes),
            "srt_sha256": sha256_hex(srt_bytes),
        }

    def validate(self, state: TransformationState) -> TransformationState:
        """Light structural validation of completed outputs.

        A completed output that no longer has usable text is flagged as failed.
        This never destroys successful outputs from the same job (partial success).
        """
        session = self.deps.session
        if not state.get("outputs"):
            return {}

        errors = list(state.get("errors", []))
        outputs: list[dict[str, Any]] = []
        for output in state["outputs"]:
            if output["status"] != "completed":
                outputs.append(output)
                continue
            if not output.get("structured_content"):
                record = session.get(Output, uuid.UUID(output["output_id"]))
                if record is not None:
                    record.status = "failed"
                    record.error_message = "Validation failed: no structured content."
                    session.flush()
                errors.append(
                    {
                        "stage": "validate",
                        "output_type": output["output_type"],
                        "message": "Validation failed: no structured content.",
                    }
                )
                continue
            outputs.append(output)

        return {"outputs": outputs, "errors": errors}

    def verify_hook(self, state: TransformationState) -> TransformationState:
        """Run the Phase 8 verification engine for each completed output.

        Loads the source's normalized chunks as evidence, invokes the
        deterministic verification engine per output, and persists one
        VerificationResult record per completed output.  A verification failure
        never destroys the generated output: the output is left untouched and a
        controlled warning result is recorded, preserving failure isolation
        between outputs.
        """
        session = self.deps.session
        hooks: list[dict[str, Any]] = list(state.get("verification_hooks", []))

        source_chunks = self._load_source_chunks(state)

        for output in state.get("outputs", []):
            if output["status"] != "completed":
                continue
            try:
                result = run_verification_hook(
                    output=output["structured_content"],
                    canonical=state.get("canonical", {}),
                    hook=self.deps.verification_hook,
                    source_chunks=source_chunks,
                )
            except Exception as exc:  # verification must never destroy output
                result = {
                    "output_type": output["output_type"],
                    "status": "error",
                    "overall_status": "warning",
                    "message": f"Verification failed: {exc}",
                    "grounding_score": None,
                    "consistency_score": None,
                    "claims_checked": 0,
                    "claims_supported": 0,
                    "warnings": {
                        "status": "warning",
                        "message": f"Verification failed: {exc}",
                        "items": [
                            {
                                "type": "verification_error",
                                "severity": "error",
                                "message": f"Verification failed: {exc}",
                                "claim_text": None,
                                "evidence": None,
                                "chunk_index": None,
                            }
                        ],
                        "count": 1,
                    },
                    "details": {
                        "status": "error",
                        "generator": "deterministic-phase8-factcheck",
                        "error": str(exc),
                    },
                }
            hooks.append(
                {
                    "output_id": output["output_id"],
                    "output_type": output["output_type"],
                    "result": result,
                }
            )
            # Persist a verification result record reusing the existing model.
            record = session.get(Output, uuid.UUID(output["output_id"]))
            if record is not None:
                session.add(
                    VerificationResult(
                        id=uuid.uuid4(),
                        output_id=record.id,
                        overall_status=result.get("overall_status", "warning"),
                        grounding_score=result.get("grounding_score"),
                        consistency_score=result.get("consistency_score"),
                        claims_checked=result.get("claims_checked", 0),
                        claims_supported=result.get("claims_supported", 0),
                        warnings=result.get("warnings"),
                        details=result,
                        created_at=_utcnow(),
                    )
                )
                session.flush()

        return {"verification_hooks": hooks}

    def _load_source_chunks(self, state: TransformationState) -> list[str]:
        """Load the source's normalized chunks as evidence for verification."""
        session = self.deps.session
        source_id = state.get("source_id")
        if not source_id:
            return []
        try:
            rows = (
                session.execute(
                    select(SourceChunk)
                    .where(SourceChunk.source_id == uuid.UUID(str(source_id)))
                    .order_by(SourceChunk.chunk_index)
                )
                .scalars()
                .all()
            )
            chunks = [row.content for row in rows]
            if not chunks:
                source = session.get(Source, uuid.UUID(str(source_id)))
                if source is not None and source.extracted_text:
                    chunks = [source.extracted_text]
            return chunks
        except (ValueError, TypeError):
            return []

    def finalize(self, state: TransformationState) -> TransformationState:
        """Update job status based on canonical readiness and output outcomes."""
        session = self.deps.session
        job = session.get(TransformationJob, uuid.UUID(state["job_id"]))
        if job is None:
            return {}

        completed = sum(1 for o in state.get("outputs", []) if o["status"] == "completed")
        requested = len(state.get("requested_output_types", []))

        if not state.get("canonical_ready"):
            job.status = "failed"
            job.progress = 100
            job.error_message = "Canonical content is missing or not completed; cannot transform."
            job.completed_at = _utcnow()
            session.flush()
            return {"errors": state.get("errors", [])}

        failures = sum(1 for o in state.get("outputs", []) if o["status"] == "failed")

        if completed >= 1:
            # Partial success: keep successful outputs, mark job completed.
            job.status = "completed"
            job.progress = 100
        elif requested == 0:
            job.status = "failed"
            job.error_message = "No output types were requested."
            job.progress = 100
        else:
            job.status = "failed"
            job.error_message = f"All {requested} requested outputs failed ({failures} failed)."
            job.progress = 100
        job.completed_at = _utcnow()
        session.flush()
        return {}


def build_transformation_graph(deps: TransformationDependencies):
    """Build and compile the LangGraph transformation workflow."""
    workflow = TransformationWorkflow(deps)

    builder = StateGraph(TransformationState)

    builder.add_node("load_input", workflow.load_input)
    builder.add_node("load_canonical_content", workflow.load_canonical_content)
    builder.add_node("retrieve_if_required", workflow.retrieve_if_required)
    builder.add_node("build_brief", workflow.build_brief)
    builder.add_node("plan_outputs", workflow.plan_outputs)
    builder.add_node("generate", workflow.generate)
    builder.add_node("validate", workflow.validate)
    builder.add_node("verify_hook", workflow.verify_hook)
    builder.add_node("finalize", workflow.finalize)

    builder.set_entry_point("load_input")
    builder.add_edge("load_input", "load_canonical_content")

    def _after_canonical(state: TransformationState) -> str:
        return "retrieve_if_required" if state.get("canonical_ready") else "finalize"

    builder.add_conditional_edges(
        "load_canonical_content",
        _after_canonical,
        {"retrieve_if_required": "retrieve_if_required", "finalize": "finalize"},
    )
    builder.add_edge("retrieve_if_required", "build_brief")
    builder.add_edge("build_brief", "plan_outputs")
    builder.add_edge("plan_outputs", "generate")
    builder.add_edge("generate", "validate")
    builder.add_edge("validate", "verify_hook")
    builder.add_edge("verify_hook", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()
