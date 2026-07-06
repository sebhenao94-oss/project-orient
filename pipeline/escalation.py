"""Escalation rules for equipment extraction results.

This module turns model output and source classification into review decisions.
It does not call an LLM and does not mutate extraction results; it only explains
whether a row should be accepted, retried, sent to a drawing second pass, or sent
to human/source-type review.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

if __package__:
    from .models import EquipmentExtractionCandidate, EquipmentExtractionRunResult
else:
    from models import EquipmentExtractionCandidate, EquipmentExtractionRunResult


UNKNOWN_EQUIPMENT_CLASS = "unknown class"

ACCEPT = "accept"
RETRY_SCREENSHOT_EXTRACTION = "retry_screenshot_extraction"
MECHANICAL_DRAWING_SECOND_PASS = "mechanical_drawing_second_pass"
SOURCE_TYPE_REVIEW = "source_type_review"
COMPLEX_IMAGE_REVIEW = "complex_image_review"
HUMAN_REVIEW = "human_review"

ESCALATION_MODEL_ENV = {
    ACCEPT: "LLM_MODEL",
    RETRY_SCREENSHOT_EXTRACTION: "LLM_RETRY_MODEL",
    MECHANICAL_DRAWING_SECOND_PASS: "LLM_MECHANICAL_DRAWING_MODEL",
    SOURCE_TYPE_REVIEW: "LLM_SOURCE_TYPE_REVIEW_MODEL",
    COMPLEX_IMAGE_REVIEW: "LLM_COMPLEX_IMAGE_MODEL",
    HUMAN_REVIEW: "LLM_HUMAN_REVIEW_MODEL",
}


@dataclass(frozen=True)
class EscalationDecision:
    review_required: bool
    review_reasons: List[str]
    next_action: str

    @property
    def review_reason_text(self) -> str:
        return ";".join(self.review_reasons)

    def model_for_action(self, default_model: str) -> str:
        return model_for_escalation_action(self.next_action, default_model)


def model_for_escalation_action(action: str, default_model: str) -> str:
    """Return the configured model for an escalation action.

    Missing action-specific model environment variables fall back to the first
    pass model so local smoke tests work with only LLM_MODEL configured.
    """
    env_name = ESCALATION_MODEL_ENV.get(action)
    if not env_name:
        return default_model
    return os.getenv(env_name) or default_model


def _next_action(source_document_type: str, reasons: List[str]) -> str:
    if not reasons:
        return ACCEPT
    if "mechanical_drawing_second_pass_required" in reasons:
        return MECHANICAL_DRAWING_SECOND_PASS
    if source_document_type == "unknown":
        return SOURCE_TYPE_REVIEW
    if "image_complexity_complex" in reasons:
        return COMPLEX_IMAGE_REVIEW
    if reasons == ["low_confidence"]:
        return RETRY_SCREENSHOT_EXTRACTION
    return HUMAN_REVIEW


def evaluate_equipment_candidate(
    result: EquipmentExtractionRunResult,
    candidate: EquipmentExtractionCandidate,
    *,
    low_confidence_threshold: float = 0.75,
) -> EscalationDecision:
    """Route one extracted equipment row to accept, retry, or review."""
    reasons: List[str] = []

    if result.image_complexity == "complex":
        reasons.append("image_complexity_complex")
    elif result.image_complexity == "unknown":
        reasons.append("image_complexity_unknown")

    if result.source_document_type == "mechanical_drawing" and result.image_complexity == "complex":
        reasons.append("mechanical_drawing_second_pass_required")
    elif result.source_document_type == "unknown":
        reasons.append("source_type_unknown")

    if candidate.confidence < low_confidence_threshold:
        reasons.append("low_confidence")

    if candidate.equipment_type == UNKNOWN_EQUIPMENT_CLASS:
        reasons.append("unknown_equipment_type")

    return EscalationDecision(
        review_required=bool(reasons),
        review_reasons=reasons,
        next_action=_next_action(result.source_document_type, reasons),
    )


def evaluate_extraction_run(
    result: EquipmentExtractionRunResult,
    *,
    low_confidence_threshold: float = 0.75,
) -> Optional[EscalationDecision]:
    """Return a run-level escalation when a successful run produced no rows."""
    if result.status != "succeeded" or result.parsed_response is None:
        return None
    if result.parsed_response.equipment:
        return None

    reasons: List[str] = []
    if result.image_complexity == "complex":
        reasons.append("image_complexity_complex")
    elif result.image_complexity == "unknown":
        reasons.append("image_complexity_unknown")

    if result.source_document_type == "mechanical_drawing" and result.image_complexity == "complex":
        reasons.append("mechanical_drawing_second_pass_required")
    elif result.source_document_type == "unknown":
        reasons.append("source_type_unknown")
    else:
        reasons.append("no_equipment_found")

    return EscalationDecision(
        review_required=True,
        review_reasons=reasons,
        next_action=_next_action(result.source_document_type, reasons),
    )
