"""Parse and validate LLM output into a typed output schema.

An LLM is asked to return JSON.  The provider may wrap that JSON in markdown
fences or add prose, so we extract the JSON defensively.  The result is then
validated against the requested schema; invalid output raises a controlled
error (the Phase 6 workflow records it as an output failure rather than a
catastrophic job failure).
"""

from __future__ import annotations

import json
import re
from typing import Any, get_args, get_origin

from pydantic import BaseModel, ValidationError

from app.transformation.output_schemas import ALL_OUTPUT_SCHEMAS


class OutputSchemaError(ValueError):
    """Raised when an output cannot be parsed or validated."""


def _field_is_list_of_strings(schema: type[BaseModel], field: str) -> bool:
    """True when `field` is declared as ``list[str]`` (a string collection)."""
    field_info = schema.model_fields.get(field)
    if field_info is None:
        return False
    annotation = field_info.annotation
    if get_origin(annotation) is not list:
        return False
    args = get_args(annotation)
    if not args:
        return False
    inner = args[0]
    # Nested Pydantic models (e.g. list[PresentationSlide]) are arrays of objects —
    # never coerce those; a string there is genuinely malformed.
    return not hasattr(inner, "model_fields")


def _split_string_collection(value: str) -> list[str]:
    """Split a model-rendered collection string into element strings.

    Prefer explicit separators that preserve meaningful whitespace inside an
    element: newlines, then commas/semicolons. Only when none are present do we
    fall back to splitting on whitespace (the common ``"#A #B #C"`` style for
    tags, whose elements never contain spaces). Empty fragments are dropped.
    """
    for separator in ("\n", ",", ";"):
        if separator in value:
            return [part.strip() for part in value.split(separator) if part.strip()]
    return [part for part in value.split() if part]


def normalize_output_data(
    data: dict[str, Any], schema: type[BaseModel]
) -> dict[str, Any]:
    """Normalize common LLM JSON slips before schema validation.

    Real models frequently render a collection field (``hashtags``,
    ``supporting_points``, ``thread``) as a single space/comma-separated string
    instead of a JSON array. For any field the schema declares as ``list[str]``,
    if the model returned a string, split it into a list. This is a pure
    formatting normalization: every element still has to satisfy the schema's
    ``list[str]`` contract during ``model_validate``, so validation is not
    weakened — genuinely invalid values still raise ``OutputSchemaError``.
    """
    for field in schema.model_fields:
        if field not in data or field == "type":
            continue
        value = data[field]
        if isinstance(value, str) and _field_is_list_of_strings(schema, field):
            parts = _split_string_collection(value)
            if parts:
                data[field] = parts
    return data


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from arbitrary model text."""
    text = text.strip()
    # Try the whole string first.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    # Strip markdown fences.
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    # Find the first balanced top-level object as a last resort.
    start = text.find("{")
    if start != -1:
        depth = 0
        in_str = False
        esc = False
        for index in range(start, len(text)):
            char = text[index]
            if in_str:
                if esc:
                    esc = False
                elif char == "\\":
                    esc = True
                elif char == '"':
                    in_str = False
                continue
            if char == '"':
                in_str = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : index + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except (json.JSONDecodeError, ValueError):
                        break
    raise OutputSchemaError("Could not extract a JSON object from model output.")


def parse_output(output_type: str, text: str) -> BaseModel:
    """Parse LLM text into the validated schema for `output_type`."""
    schema = ALL_OUTPUT_SCHEMAS.get(output_type)
    if schema is None:
        raise OutputSchemaError(f"No schema registered for output type {output_type!r}.")
    data = extract_json_object(text)
    data["type"] = output_type
    normalize_output_data(data, schema)
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise OutputSchemaError(
            f"Invalid {output_type} output: {exc}"
        ) from exc
