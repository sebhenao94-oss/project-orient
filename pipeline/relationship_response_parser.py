"""Strict offline parsing for relationship-mapping model responses.

Mirrors `equipment_response_parser` exactly: malformed, truncated, or
schema-invalid output is preserved and rejected rather than silently repaired.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError

if __package__:
    from .models import RelationshipExtractionResponse
else:
    from models import RelationshipExtractionResponse


class RelationshipResponseParseError(ValueError):
    """Base error for raw relationship-mapping response parsing failures."""


class EmptyRelationshipResponseError(RelationshipResponseParseError):
    """Raised when the model response is empty or whitespace-only."""


class RelationshipResponseSerializationError(RelationshipResponseParseError):
    """Raised when the response is not one strict JSON payload."""


class RelationshipResponseRootError(RelationshipResponseParseError):
    """Raised when the parsed JSON root has the wrong shape."""


class RelationshipResponseSchemaError(RelationshipResponseParseError):
    """Raised when parsed JSON does not match RelationshipExtractionResponse."""


def parse_relationship_extraction_response(raw_text: str) -> RelationshipExtractionResponse:
    """Parse one strict raw model response into RelationshipExtractionResponse."""
    if not isinstance(raw_text, str):
        raise RelationshipResponseParseError("relationship response must be a string")

    stripped_text = raw_text.strip()
    if not stripped_text:
        raise EmptyRelationshipResponseError("relationship response must not be empty")

    json_text = _unwrap_optional_markdown_json_fence(stripped_text)
    parsed_payload = _parse_single_json_payload(json_text)

    if not isinstance(parsed_payload, Mapping):
        raise RelationshipResponseRootError(
            "relationship response JSON root must be an object"
        )

    try:
        return RelationshipExtractionResponse(**parsed_payload)
    except ValidationError as exc:
        raise RelationshipResponseSchemaError(
            "relationship response failed schema validation"
        ) from exc


def _unwrap_optional_markdown_json_fence(text: str) -> str:
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if len(lines) < 3:
        raise RelationshipResponseSerializationError(
            "markdown code fence must contain fenced JSON content and a closing fence"
        )

    opening_fence = lines[0].strip()
    if opening_fence not in {"```", "```json", "```JSON"}:
        raise RelationshipResponseSerializationError(
            "only plain or json markdown code fences are supported"
        )

    closing_fence = lines[-1].strip()
    if closing_fence != "```":
        raise RelationshipResponseSerializationError(
            "markdown code fence must end with a standalone closing fence"
        )

    fenced_content = "\n".join(lines[1:-1]).strip()
    if not fenced_content:
        raise EmptyRelationshipResponseError("fenced relationship response is empty")
    return fenced_content


def _parse_single_json_payload(json_text: str) -> Any:
    decoder = json.JSONDecoder()
    try:
        parsed_payload, end_index = decoder.raw_decode(json_text)
    except json.JSONDecodeError as exc:
        raise RelationshipResponseSerializationError(
            "relationship response is not valid JSON "
            f"at line {exc.lineno}, column {exc.colno}; "
            f"preview={_preview_text(json_text)}"
        ) from exc

    trailing_content = json_text[end_index:].strip()
    if trailing_content:
        raise RelationshipResponseSerializationError(
            "relationship response contains trailing content after the JSON "
            f"payload; preview={_preview_text(trailing_content)}"
        )

    return parsed_payload


def _preview_text(text: str, max_length: int = 160) -> str:
    compact_text = " ".join(text.split())
    if len(compact_text) > max_length:
        compact_text = compact_text[: max_length - 3] + "..."
    return repr(compact_text)
