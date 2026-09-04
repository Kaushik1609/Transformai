"""Shared helpers for LLM-backed Phase 7 generators.

Reduces duplication across generators: each generator supplies an output
schema class, a human label, and config; this helper assembles prompts,
invokes the LLM (via the injected provider, falling back to the deterministic
fake provider), validates the parsed JSON, and returns the JSON mapping ready
for persistence.
"""

from __future__ import annotations

from typing import Any, get_args, get_origin

from pydantic import BaseModel

from app.rag.schemas import RAGContext
from app.transformation.llm.fake import FakeLLMProvider
from app.transformation.llm.provider import LLMProvider
from app.transformation.output_schemas.parser import parse_output
from app.transformation.prompts.content import build_user_content
from app.transformation.prompts.loader import system_prompt


def _json_type_label(annotation: Any) -> str:
    """Return a human/LLM-readable JSON type label for a Pydantic field annotation."""
    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        inner = args[0] if args else None
        if inner is not None and hasattr(inner, "model_fields"):
            return "array of objects"
        return "array of strings"
    if annotation is bool:
        return "boolean"
    if annotation in (int, float):
        return "number"
    return "string"


def _nested_field_detail(field: Any) -> str:
    """Render a nested-object field definition for a list-of-model annotation.

    e.g. for ``slides: list[PresentationSlide]`` return
    ``array of objects, each object with EXACTLY these keys: title (string),
    key_message (string), supporting_points (array of strings), ...`` so the
    model emits the correct nested key names before schema validation.
    """
    args = get_args(field.annotation)
    inner = args[0] if args else None
    if get_origin(field.annotation) is list and inner is not None and hasattr(inner, "model_fields"):
        keys = ", ".join(
            f"{name} ({_json_type_label(sub.annotation)})"
            for name, sub in inner.model_fields.items()
        )
        return f"array of objects, each object with EXACTLY these keys: {keys}"
    return _json_type_label(field.annotation)


def _typed_field_spec(schema_cls: type[BaseModel]) -> str:
    """Build a field→JSON-type hint line, e.g. ``title: string, hashtags: array of strings``.

    The real LLM frequently returns collection fields (``hashtags``, ``thread``,
    ``supporting_points``) as a space-separated string instead of a JSON array,
    and it improvises the key names of nested objects (``slides``, ``storyboard``,
    ``sections``) when those keys are not spelled out.  Stating each field's JSON
    type — and the exact keys of nested objects — in the prompt steers the model
    toward the schema-valid structure before validation.
    """
    return ", ".join(
        f"{name}: {_nested_field_detail(field)}"
        for name, field in schema_cls.model_fields.items()
        if name != "text"
    )


def generate_structured_output(
    *,
    output_type: str,
    schema_cls: type[BaseModel],
    output_name: str,
    canonical: dict[str, Any],
    config: dict[str, Any],
    rag_context: RAGContext | None,
    llm_provider: LLMProvider | None,
    brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate and validate a structured output for a single generator.

    Returns a JSON-compatible mapping (dict(model_dump)) ready to persist.
    Raises ValueError on empty/invalid output so the Phase 6 workflow records
    a controlled per-output failure.

    When a shared Phase 11C ``brief`` is provided it is used as the trusted,
    bounded source-grounded input (avoiding per-output re-formatting of the full
    canonical/RAG payload); otherwise it falls back to the legacy
    canonical+rag_context user content for full backward compatibility.
    """
    provider = llm_provider if llm_provider is not None else FakeLLMProvider()

    fields = [f for f in schema_cls.model_fields if f != "text"]
    spec = "{" + ", ".join(fields) + ", text}"
    sp = system_prompt(output_name, spec, config)
    typed_spec = _typed_field_spec(schema_cls)
    if typed_spec:
        sp += (
            "\n\nFIELD JSON TYPES — use exactly these JSON types for the "
            f"corresponding fields: {typed_spec}. Collection fields MUST be JSON "
            "arrays (e.g. \"hashtags\": [\"#A\", \"#B\"]), never space-separated strings."
        )
    if brief is not None:
        user = build_user_content(canonical, rag_context, brief=brief)
    else:
        user = build_user_content(canonical, rag_context)

    generated = provider.generate_text(system_prompt=sp, user_content=user)
    if not generated or not generated.strip():
        raise ValueError(f"{output_name} provider returned empty output.")

    validated = parse_output(output_type, generated)
    data = validated.model_dump(mode="json")
    text = data.get("text")
    if not text or not str(text).strip():
        text = _fallback_text(output_name, data)
        data["text"] = text
    data["text"] = str(text)
    return data


def _fallback_text(output_name: str, data: dict[str, Any]) -> str:
    """Build a readable text rendering when the model omitted/blanked `text`."""
    title = data.get("title") or output_name
    lines = [f"# {title}", ""]
    for key in ("summary", "hook", "main_message", "situation", "script"):
        value = data.get(key)
        if value:
            lines.append(str(value))
            lines.append("")
    return "\n".join(lines).strip() or f"# {output_name}: {title}"
