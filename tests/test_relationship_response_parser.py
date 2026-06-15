import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from relationship_response_parser import (  # noqa: E402
    EmptyRelationshipResponseError,
    RelationshipResponseParseError,
    RelationshipResponseRootError,
    RelationshipResponseSchemaError,
    RelationshipResponseSerializationError,
    parse_relationship_extraction_response,
)
from models import RelationshipExtractionResponse, RelationshipRefType  # noqa: E402


def valid_response_data():
    return {
        "relationships": [
            {
                "child": "VAVRH_2_01",
                "parent": "AHU_2_01",
                "ref_type": "airRef",
                "confidence": 0.95,
                "conflict": False,
                "conflict_reason": "",
            }
        ]
    }


def response_text(data):
    return json.dumps(data, separators=(",", ":"))


class TestParseRelationshipResponseValidInputs(unittest.TestCase):
    def test_valid_bare_json_object_passes(self):
        response = parse_relationship_extraction_response(
            response_text(valid_response_data())
        )

        self.assertIsInstance(response, RelationshipExtractionResponse)
        self.assertEqual(response.relationships[0].child, "VAVRH_2_01")
        self.assertEqual(response.relationships[0].parent, "AHU_2_01")
        self.assertEqual(
            response.relationships[0].ref_type, RelationshipRefType.AIR_REF
        )

    def test_valid_json_markdown_code_fence_passes(self):
        raw_text = "```json\n" + response_text(valid_response_data()) + "\n```"

        response = parse_relationship_extraction_response(raw_text)

        self.assertEqual(response.relationships[0].parent, "AHU_2_01")

    def test_valid_generic_markdown_code_fence_passes(self):
        raw_text = "```\n" + response_text(valid_response_data()) + "\n```"

        response = parse_relationship_extraction_response(raw_text)

        self.assertEqual(response.relationships[0].child, "VAVRH_2_01")

    def test_surrounding_whitespace_is_accepted(self):
        raw_text = "\n  " + response_text(valid_response_data()) + " \n"

        response = parse_relationship_extraction_response(raw_text)

        self.assertEqual(len(response.relationships), 1)

    def test_multiple_edges_preserve_order(self):
        data = valid_response_data()
        data["relationships"].append(
            {
                "child": "AHU_2_01",
                "parent": "CHW-PLANT_1",
                "ref_type": "chilledWaterRef",
                "confidence": 0.9,
                "conflict": False,
                "conflict_reason": "",
            }
        )

        response = parse_relationship_extraction_response(response_text(data))

        self.assertEqual(
            [(edge.child, edge.parent) for edge in response.relationships],
            [("VAVRH_2_01", "AHU_2_01"), ("AHU_2_01", "CHW-PLANT_1")],
        )

    def test_empty_relationship_collection_is_accepted(self):
        response = parse_relationship_extraction_response(
            response_text({"relationships": []})
        )

        self.assertEqual(response.relationships, [])

    def test_optional_conflict_fields_default(self):
        data = {
            "relationships": [
                {
                    "child": "VAVRH_2_01",
                    "parent": "AHU_2_01",
                    "ref_type": "airRef",
                    "confidence": 0.95,
                }
            ]
        }

        response = parse_relationship_extraction_response(response_text(data))

        self.assertFalse(response.relationships[0].conflict)
        self.assertEqual(response.relationships[0].conflict_reason, "")

    def test_extra_fields_are_ignored(self):
        data = valid_response_data()
        data["prompt_version"] = "relationship_mapping_v1"
        data["relationships"][0]["source_drawing"] = "ahu_02c.png"

        response = parse_relationship_extraction_response(response_text(data))

        self.assertEqual(len(response.relationships), 1)
        self.assertFalse(hasattr(response, "prompt_version"))
        self.assertFalse(hasattr(response.relationships[0], "source_drawing"))


class TestParseRelationshipResponseInvalidSerialization(unittest.TestCase):
    def assertSerializationFails(self, raw_text):
        with self.assertRaises(RelationshipResponseSerializationError):
            parse_relationship_extraction_response(raw_text)

    def test_non_string_input_fails(self):
        with self.assertRaises(RelationshipResponseParseError):
            parse_relationship_extraction_response({"relationships": []})

    def test_empty_string_fails(self):
        with self.assertRaises(EmptyRelationshipResponseError):
            parse_relationship_extraction_response("")

    def test_whitespace_only_string_fails(self):
        with self.assertRaises(EmptyRelationshipResponseError):
            parse_relationship_extraction_response("  \n\t ")

    def test_malformed_json_fails(self):
        self.assertSerializationFails('{"relationships": [}')

    def test_truncated_json_fails(self):
        self.assertSerializationFails('{"relationships": [{"child": "VAVRH_2_01"}')

    def test_prose_only_response_fails(self):
        self.assertSerializationFails("AHU_2_01 serves the listed VAVs.")

    def test_multiple_json_objects_fail(self):
        first = response_text(valid_response_data())
        second = response_text({"relationships": []})

        self.assertSerializationFails(first + "\n" + second)

    def test_prose_before_json_fails(self):
        self.assertSerializationFails(
            "Here are the edges:\n" + response_text(valid_response_data())
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
        with self.assertRaises(RelationshipResponseRootError):
            parse_relationship_extraction_response("[]")

    def test_json_string_root_fails(self):
        with self.assertRaises(RelationshipResponseRootError):
            parse_relationship_extraction_response('"hello"')

    def test_json_number_root_fails(self):
        with self.assertRaises(RelationshipResponseRootError):
            parse_relationship_extraction_response("42")


class TestParseRelationshipResponseInvalidSchema(unittest.TestCase):
    def assertSchemaFails(self, data):
        with self.assertRaises(RelationshipResponseSchemaError):
            parse_relationship_extraction_response(response_text(data))

    def test_missing_required_top_level_field_fails(self):
        self.assertSchemaFails({})

    def test_missing_edge_field_fails(self):
        data = valid_response_data()
        del data["relationships"][0]["parent"]

        self.assertSchemaFails(data)

    def test_generic_water_ref_is_rejected(self):
        data = valid_response_data()
        data["relationships"][0]["ref_type"] = "waterRef"

        self.assertSchemaFails(data)

    def test_unknown_ref_type_fails(self):
        data = valid_response_data()
        data["relationships"][0]["ref_type"] = "servesRef"

        self.assertSchemaFails(data)

    def test_confidence_below_allowed_minimum_fails(self):
        data = valid_response_data()
        data["relationships"][0]["confidence"] = -0.01

        self.assertSchemaFails(data)

    def test_confidence_above_allowed_maximum_fails(self):
        data = valid_response_data()
        data["relationships"][0]["confidence"] = 1.01

        self.assertSchemaFails(data)

    def test_wrong_top_level_field_type_fails(self):
        self.assertSchemaFails({"relationships": "AHU_2_01"})

    def test_wrong_edge_field_type_fails(self):
        data = valid_response_data()
        data["relationships"][0]["confidence"] = "high"

        self.assertSchemaFails(data)

    def test_blank_endpoint_fails(self):
        data = valid_response_data()
        data["relationships"][0]["child"] = "   "

        self.assertSchemaFails(data)


if __name__ == "__main__":
    unittest.main()
