"""Strict offline parsing for equipment-extraction model responses."""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError

if __package__:
    from .models import EquipmentExtractionResponse
else:
    from models import EquipmentExtractionResponse


class EquipmentResponseParseError(ValueError):
    """Base error for raw equipment-extraction response parsing failures."""


class EmptyEquipmentResponseError(EquipmentResponseParseError):
    """Raised when the model response is empty or whitespace-only."""


class EquipmentResponseSerializationError(EquipmentResponseParseError):
    """Raised when the response is not one strict JSON payload."""


class EquipmentResponseRootError(EquipmentResponseParseError):
    """Raised when the parsed JSON root has the wrong shape."""


class EquipmentResponseSchemaError(EquipmentResponseParseError):
    """Raised when parsed JSON does not match EquipmentExtractionResponse."""


def parse_equipment_extraction_response(raw_text: str) -> EquipmentExtractionResponse:
    """Parse one strict raw model response into EquipmentExtractionResponse."""
    if not isinstance(raw_text, str):
        raise EquipmentResponseParseError("equipment extraction response must be a string")

    stripped_text = raw_text.strip()
    if not stripped_text:
        raise EmptyEquipmentResponseError("equipment extraction response must not be empty")

    json_text = _unwrap_optional_markdown_json_fence(stripped_text)
    parsed_payload = _parse_single_json_payload(json_text)

    if not isinstance(parsed_payload, Mapping):
        raise EquipmentResponseRootError(
            "equipment extraction response JSON root must be an object"
        )

    try:
        return EquipmentExtractionResponse(**parsed_payload)
    except ValidationError as exc:
        raise EquipmentResponseSchemaError(
            "equipment extraction response failed schema validation"
        ) from exc


def _unwrap_optional_markdown_json_fence(text: str) -> str:
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if len(lines) < 3:
        raise EquipmentResponseSerializationError(
            "markdown code fence must contain fenced JSON content and a closing fence"
        )

    opening_fence = lines[0].strip()
    if opening_fence not in {"```", "```json", "```JSON"}:
        raise EquipmentResponseSerializationError(
            "only plain or json markdown code fences are supported"
        )

    closing_fence = lines[-1].strip()
    if closing_fence != "```":
        raise EquipmentResponseSerializationError(
            "markdown code fence must end with a standalone closing fence"
        )

    fenced_content = "\n".join(lines[1:-1]).strip()
    if not fenced_content:
        raise EmptyEquipmentResponseError("fenced equipment extraction response is empty")
    return fenced_content


def _parse_single_json_payload(json_text: str) -> Any:
    decoder = json.JSONDecoder()
    try:
        parsed_payload, end_index = decoder.raw_decode(json_text)
    except json.JSONDecodeError as exc:
        raise EquipmentResponseSerializationError(
            "equipment extraction response is not valid JSON "
            f"at line {exc.lineno}, column {exc.colno}; "
            f"preview={_preview_text(json_text)}"
        ) from exc

    trailing_content = json_text[end_index:].strip()
    if trailing_content:
        raise EquipmentResponseSerializationError(
            "equipment extraction response contains trailing content after the JSON "
            f"payload; preview={_preview_text(trailing_content)}"
        )

    return parsed_payload


def _preview_text(text: str, max_length: int = 160) -> str:
    compact_text = " ".join(text.split())
    if len(compact_text) > max_length:
        compact_text = compact_text[: max_length - 3] + "..."
    return repr(compact_text)
