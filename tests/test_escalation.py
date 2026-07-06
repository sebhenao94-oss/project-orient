import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from escalation import (  # noqa: E402
    ACCEPT,
    COMPLEX_IMAGE_REVIEW,
    HUMAN_REVIEW,
    MECHANICAL_DRAWING_SECOND_PASS,
    RETRY_SCREENSHOT_EXTRACTION,
    SOURCE_TYPE_REVIEW,
    evaluate_equipment_candidate,
    evaluate_extraction_run,
    model_for_escalation_action,
)
from models import EquipmentExtractionCandidate, EquipmentExtractionResponse, EquipmentExtractionRunResult  # noqa: E402


SHA = "a" * 64


def candidate(confidence=0.98, equipment_type="AHU"):
    return EquipmentExtractionCandidate(
        raw_label="AHU 02 A",
        canonical_name="AHU_02_A",
        equipment_type=equipment_type,
        confidence=confidence,
    )


def run_result(source_document_type="bms_screenshot", image_complexity="simple", equipment=None):
    now = datetime.now(timezone.utc)
    route = {
        "bms_screenshot": "standard_screenshot_extraction",
        "mechanical_drawing": "mechanical_drawing_second_pass",
        "unknown": "needs_source_type_review",
    }[source_document_type]
    return EquipmentExtractionRunResult(
        source_filename="a.png",
        source_relative_path="a.png",
        source_sha256=SHA,
        source_file_type="image",
        source_document_type=source_document_type,
        source_document_reason="test",
        image_complexity=image_complexity,
        image_complexity_reason="test complexity",
        extraction_route=route,
        prepared_image_path="/tmp/a.png",
        prepared_image_filename="a.png",
        image_mime_type="image/png",
        prompt_version="equipment_extraction_v3",
        model_id="test-model",
        started_at=now,
        completed_at=now,
        status="succeeded",
        raw_assistant_response='{"equipment":[]}',
        parsed_response=EquipmentExtractionResponse(
            equipment=list([candidate()] if equipment is None else equipment)
        ),
    )


class TestEscalationRules(unittest.TestCase):
    def test_high_confidence_screenshot_is_accepted(self):
        decision = evaluate_equipment_candidate(run_result(), candidate())

        self.assertFalse(decision.review_required)
        self.assertEqual(decision.next_action, ACCEPT)
        self.assertEqual(decision.review_reason_text, "")

    def test_low_confidence_screenshot_gets_retry(self):
        decision = evaluate_equipment_candidate(run_result(), candidate(confidence=0.4))

        self.assertTrue(decision.review_required)
        self.assertEqual(decision.review_reason_text, "low_confidence")
        self.assertEqual(decision.next_action, RETRY_SCREENSHOT_EXTRACTION)

    def test_unknown_equipment_type_goes_to_human_review(self):
        decision = evaluate_equipment_candidate(run_result(), candidate(equipment_type="unknown class"))

        self.assertTrue(decision.review_required)
        self.assertEqual(decision.review_reason_text, "unknown_equipment_type")
        self.assertEqual(decision.next_action, HUMAN_REVIEW)

    def test_simple_mechanical_drawing_can_be_accepted(self):
        decision = evaluate_equipment_candidate(run_result("mechanical_drawing"), candidate())

        self.assertFalse(decision.review_required)
        self.assertEqual(decision.next_action, ACCEPT)
        self.assertEqual(decision.review_reason_text, "")

    def test_complex_mechanical_drawing_goes_to_second_pass(self):
        decision = evaluate_equipment_candidate(
            run_result("mechanical_drawing", image_complexity="complex"),
            candidate(),
        )

        self.assertTrue(decision.review_required)
        self.assertEqual(
            decision.review_reason_text,
            "image_complexity_complex;mechanical_drawing_second_pass_required",
        )
        self.assertEqual(decision.next_action, MECHANICAL_DRAWING_SECOND_PASS)

    def test_complex_screenshot_goes_to_complex_image_review(self):
        decision = evaluate_equipment_candidate(
            run_result("bms_screenshot", image_complexity="complex"),
            candidate(),
        )

        self.assertTrue(decision.review_required)
        self.assertEqual(decision.review_reason_text, "image_complexity_complex")
        self.assertEqual(decision.next_action, COMPLEX_IMAGE_REVIEW)

    def test_unknown_source_type_goes_to_source_type_review(self):
        decision = evaluate_equipment_candidate(run_result("unknown"), candidate())

        self.assertTrue(decision.review_required)
        self.assertEqual(decision.review_reason_text, "source_type_unknown")
        self.assertEqual(decision.next_action, SOURCE_TYPE_REVIEW)

    def test_empty_successful_screenshot_escalates_no_equipment_found(self):
        decision = evaluate_extraction_run(run_result(equipment=[]))

        self.assertIsNotNone(decision)
        self.assertEqual(decision.review_reason_text, "no_equipment_found")
        self.assertEqual(decision.next_action, HUMAN_REVIEW)

    def test_escalation_model_uses_action_specific_env_when_present(self):
        with patch.dict("os.environ", {"LLM_RETRY_MODEL": "retry-model"}, clear=False):
            model = model_for_escalation_action(RETRY_SCREENSHOT_EXTRACTION, "base-model")

        self.assertEqual(model, "retry-model")

    def test_escalation_model_falls_back_to_first_pass_model(self):
        with patch.dict("os.environ", {}, clear=True):
            model = model_for_escalation_action(MECHANICAL_DRAWING_SECOND_PASS, "base-model")

        self.assertEqual(model, "base-model")


if __name__ == "__main__":
    unittest.main()
