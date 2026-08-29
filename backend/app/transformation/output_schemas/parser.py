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
from typing import Any

from pydantic import BaseModel, ValidationError

from app.transformation.output_schemas import ALL_OUTPUT_SCHEMAS


class OutputSchemaError(ValueError):
    """Raised when an output cannot be parsed or validated."""


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
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise OutputSchemaError(
            f"Invalid {output_type} output: {exc}"
        ) from exc
