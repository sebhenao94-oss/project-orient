import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from equipment_response_parser import (  # noqa: E402
    EmptyEquipmentResponseError,
    EquipmentResponseParseError,
    EquipmentResponseRootError,
    EquipmentResponseSchemaError,
    EquipmentResponseSerializationError,
    parse_equipment_extraction_response,
)
from models import EquipmentExtractionResponse  # noqa: E402


def valid_response_data():
    return {
        "equipment": [
            {
                "raw_label": "AHU 02 A",
                "canonical_name": "AHU_02A",
                "equipment_type": "AHU",
                "confidence": 0.98,
            }
        ]
    }


def response_text(data):
    return json.dumps(data, separators=(",", ":"))


class TestParseEquipmentExtractionResponseValidInputs(unittest.TestCase):
    def test_valid_bare_json_object_passes(self):
        response = parse_equipment_extraction_response(
            response_text(valid_response_data())
        )

        self.assertIsInstance(response, EquipmentExtractionResponse)
        self.assertEqual(response.equipment[0].raw_label, "AHU 02 A")
        self.assertEqual(response.equipment[0].equipment_type, "AHU")

    def test_valid_json_markdown_code_fence_passes(self):
        raw_text = "```json\n" + response_text(valid_response_data()) + "\n```"

        response = parse_equipment_extraction_response(raw_text)

        self.assertEqual(response.equipment[0].canonical_name, "AHU_02A")

    def test_valid_generic_markdown_code_fence_passes(self):
        raw_text = "```\n" + response_text(valid_response_data()) + "\n```"

        response = parse_equipment_extraction_response(raw_text)

        self.assertEqual(response.equipment[0].raw_label, "AHU 02 A")

    def test_surrounding_whitespace_is_accepted(self):
        raw_text = "\n  " + response_text(valid_response_data()) + " \n"

        response = parse_equipment_extraction_response(raw_text)

        self.assertEqual(len(response.equipment), 1)

    def test_multiple_candidates_preserve_order(self):
        data = valid_response_data()
        data["equipment"].append(
            {
                "raw_label": "VAVRH 2-1",
                "canonical_name": "VAVRH_2_1",
                "equipment_type": "VAV-RH-HW",
                "confidence": 0.91,
            }
        )

        response = parse_equipment_extraction_response(response_text(data))

        self.assertEqual(
            [candidate.raw_label for candidate in response.equipment],
            ["AHU 02 A", "VAVRH 2-1"],
        )

    def test_empty_candidate_collection_is_accepted(self):
        response = parse_equipment_extraction_response(response_text({"equipment": []}))

        self.assertEqual(response.equipment, [])

    def test_extra_fields_follow_existing_model_configuration(self):
        data = valid_response_data()
        data["prompt_version"] = "equipment_extraction_v2"
        data["equipment"][0]["source_file"] = "AHU_02A.png"

        response = parse_equipment_extraction_response(response_text(data))

        self.assertEqual(len(response.equipment), 1)
        self.assertFalse(hasattr(response, "prompt_version"))
        self.assertFalse(hasattr(response.equipment[0], "source_file"))


class TestParseEquipmentExtractionResponseInvalidSerialization(unittest.TestCase):
    def assertSerializationFails(self, raw_text):
        with self.assertRaises(EquipmentResponseSerializationError):
            parse_equipment_extraction_response(raw_text)

    def test_non_string_input_fails(self):
        with self.assertRaises(EquipmentResponseParseError):
            parse_equipment_extraction_response({"equipment": []})

    def test_empty_string_fails(self):
        with self.assertRaises(EmptyEquipmentResponseError):
            parse_equipment_extraction_response("")

    def test_whitespace_only_string_fails(self):
        with self.assertRaises(EmptyEquipmentResponseError):
            parse_equipment_extraction_response("  \n\t ")

    def test_malformed_json_fails(self):
        self.assertSerializationFails('{"equipment": [}')

    def test_truncated_json_fails(self):
        self.assertSerializationFails('{"equipment": [{"raw_label": "AHU 02 A"}')

    def test_prose_only_response_fails(self):
        self.assertSerializationFails("I found one AHU in the image.")

    def test_multiple_json_objects_fail(self):
        first = response_text(valid_response_data())
        second = response_text({"equipment": []})

        self.assertSerializationFails(first + "\n" + second)

    def test_prose_before_json_fails(self):
        self.assertSerializationFails(
            "Here is the result:\n" + response_text(valid_response_data())
        )

    def test_prose_after_json_fails(self):
        self.assertSerializationFails(
            response_text(valid_response_data()) + "\nThat is all."
        )

    def test_extra_trailing_non_whitespace_content_fails(self):
        self.assertSerializationFails(response_text(valid_response_data()) + " x")

    def test_improperly_closed_code_fence_fails(self):
        self.assertSerializationFails(
            "```json\n" + response_text(valid_response_data()) + "\n``"
        )

    def test_unsupported_code_fence_language_fails(self):
        self.assertSerializationFails(
            "```python\n" + response_text(valid_response_data()) + "\n```"
        )

    def test_json_array_root_fails(self):
        with self.assertRaises(EquipmentResponseRootError):
            parse_equipment_extraction_response("[]")

    def test_json_string_root_fails(self):
        with self.assertRaises(EquipmentResponseRootError):
            parse_equipment_extraction_response('"hello"')

    def test_json_number_root_fails(self):
        with self.assertRaises(EquipmentResponseRootError):
            parse_equipment_extraction_response("42")


class TestParseEquipmentExtractionResponseInvalidSchema(unittest.TestCase):
    def assertSchemaFails(self, data):
        with self.assertRaises(EquipmentResponseSchemaError):
            parse_equipment_extraction_response(response_text(data))

    def test_missing_required_top_level_field_fails(self):
        self.assertSchemaFails({})

    def test_missing_candidate_field_fails(self):
        data = valid_response_data()
        del data["equipment"][0]["canonical_name"]

        self.assertSchemaFails(data)

    def test_invalid_equipment_type_fails(self):
        data = valid_response_data()
        data["equipment"][0]["equipment_type"] = "WIDGET"

        self.assertSchemaFails(data)

    def test_confidence_below_allowed_minimum_fails(self):
        data = valid_response_data()
        data["equipment"][0]["confidence"] = -0.01

        self.assertSchemaFails(data)

    def test_confidence_above_allowed_maximum_fails(self):
        data = valid_response_data()
        data["equipment"][0]["confidence"] = 1.01

        self.assertSchemaFails(data)

    def test_wrong_top_level_field_type_fails(self):
        self.assertSchemaFails({"equipment": "AHU 02 A"})

    def test_wrong_candidate_field_type_fails(self):
        data = valid_response_data()
        data["equipment"][0]["confidence"] = "high"

        self.assertSchemaFails(data)

    def test_point_level_label_is_not_programmatically_rejected_by_schema(self):
        data = valid_response_data()
        data["equipment"][0]["raw_label"] = "Supply Air Temp"
        data["equipment"][0]["canonical_name"] = "SUPPLY_AIR_TEMP"
        data["equipment"][0]["equipment_type"] = "unknown class"

        response = parse_equipment_extraction_response(response_text(data))

        self.assertEqual(response.equipment[0].raw_label, "Supply Air Temp")


if __name__ == "__main__":
    unittest.main()
