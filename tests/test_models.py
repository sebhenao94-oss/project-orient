import sys
import unittest
from pathlib import Path

from pydantic import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from models import (  # noqa: E402
    EquipmentExtractionCandidate,
    EquipmentExtractionResponse,
    RawDrawingEquipmentRecord,
)


def valid_record_data():
    return {
        "property_id": "b470b97b-4ea7-481c-97b7-22a81a219587",
        "floor": "Floor_02",
        "source_file": "Floor_2A.pdf",
        "source_type": "mechanical_drawing",
        "raw_equipment_label": "AHU 2-2",
        "raw_equipment_type": "AHU",
        "evidence_detail": "Equipment label shown on mechanical floor plan",
        "confidence": 0.98,
    }



def valid_candidate_data():
    return {
        "raw_label": "AHU 2-2",
        "canonical_name": "AHU_2_2",
        "equipment_type": "AHU",
        "confidence": 0.92,
    }


class TestEquipmentExtractionCandidate(unittest.TestCase):
    def test_valid_ahu_candidate_passes(self):
        candidate = EquipmentExtractionCandidate(**valid_candidate_data())

        self.assertEqual(candidate.raw_label, "AHU 2-2")
        self.assertEqual(candidate.canonical_name, "AHU_2_2")
        self.assertEqual(candidate.equipment_type, "AHU")
        self.assertEqual(candidate.confidence, 0.92)

    def test_valid_vavrh_candidate_passes(self):
        data = valid_candidate_data()
        data["raw_label"] = "VAVRH 2-1"
        data["canonical_name"] = "VAVRH_2_1"
        data["equipment_type"] = "VAV-RH-HW"

        candidate = EquipmentExtractionCandidate(**data)

        self.assertEqual(candidate.equipment_type, "VAV-RH-HW")

    def test_valid_unknown_candidate_passes(self):
        data = valid_candidate_data()
        data["equipment_type"] = "unknown class"

        candidate = EquipmentExtractionCandidate(**data)

        self.assertEqual(candidate.equipment_type, "unknown class")

    def test_label_whitespace_is_trimmed(self):
        data = valid_candidate_data()
        data["raw_label"] = "  AHU 2-2  "
        data["canonical_name"] = "  AHU_2_2  "

        candidate = EquipmentExtractionCandidate(**data)

        self.assertEqual(candidate.raw_label, "AHU 2-2")
        self.assertEqual(candidate.canonical_name, "AHU_2_2")

    def test_blank_raw_label_fails(self):
        data = valid_candidate_data()
        data["raw_label"] = ""

        with self.assertRaises(ValidationError):
            EquipmentExtractionCandidate(**data)

    def test_whitespace_only_raw_label_fails(self):
        data = valid_candidate_data()
        data["raw_label"] = "   "

        with self.assertRaises(ValidationError):
            EquipmentExtractionCandidate(**data)

    def test_blank_canonical_name_fails(self):
        data = valid_candidate_data()
        data["canonical_name"] = ""

        with self.assertRaises(ValidationError):
            EquipmentExtractionCandidate(**data)

    def test_whitespace_only_canonical_name_fails(self):
        data = valid_candidate_data()
        data["canonical_name"] = "   "

        with self.assertRaises(ValidationError):
            EquipmentExtractionCandidate(**data)

    def test_confidence_zero_is_accepted(self):
        data = valid_candidate_data()
        data["confidence"] = 0.0

        candidate = EquipmentExtractionCandidate(**data)

        self.assertEqual(candidate.confidence, 0.0)

    def test_confidence_one_is_accepted(self):
        data = valid_candidate_data()
        data["confidence"] = 1.0

        candidate = EquipmentExtractionCandidate(**data)

        self.assertEqual(candidate.confidence, 1.0)

    def test_confidence_below_zero_fails(self):
        data = valid_candidate_data()
        data["confidence"] = -0.01

        with self.assertRaises(ValidationError):
            EquipmentExtractionCandidate(**data)

    def test_confidence_above_one_fails(self):
        data = valid_candidate_data()
        data["confidence"] = 1.01

        with self.assertRaises(ValidationError):
            EquipmentExtractionCandidate(**data)

    def test_unsupported_equipment_type_fails(self):
        data = valid_candidate_data()
        data["equipment_type"] = "WIDGET"

        with self.assertRaises(ValidationError):
            EquipmentExtractionCandidate(**data)

    def test_lowercase_equipment_type_fails(self):
        data = valid_candidate_data()
        data["equipment_type"] = "ahu"

        with self.assertRaises(ValidationError):
            EquipmentExtractionCandidate(**data)


class TestEquipmentExtractionResponse(unittest.TestCase):
    def test_multiple_candidates_are_accepted_and_order_is_preserved(self):
        first = valid_candidate_data()
        second = valid_candidate_data()
        second["raw_label"] = "VAVRH 2-1"
        second["canonical_name"] = "VAVRH_2_1"
        second["equipment_type"] = "VAV-RH-HW"

        response = EquipmentExtractionResponse(equipment=[first, second])

        self.assertEqual([item.raw_label for item in response.equipment], ["AHU 2-2", "VAVRH 2-1"])

    def test_empty_equipment_list_is_accepted(self):
        response = EquipmentExtractionResponse(equipment=[])

        self.assertEqual(response.equipment, [])

class TestRawDrawingEquipmentRecord(unittest.TestCase):
    def test_valid_floor_02_record_passes(self):
        record = RawDrawingEquipmentRecord(**valid_record_data())

        self.assertEqual(record.floor, "Floor_02")
        self.assertEqual(record.raw_equipment_label, "AHU 2-2")
        self.assertEqual(record.confidence, 0.98)

    def test_non_floor_02_record_fails(self):
        data = valid_record_data()
        data["floor"] = "Floor_03"

        with self.assertRaises(ValidationError):
            RawDrawingEquipmentRecord(**data)

    def test_confidence_below_zero_fails(self):
        data = valid_record_data()
        data["confidence"] = -0.01

        with self.assertRaises(ValidationError):
            RawDrawingEquipmentRecord(**data)

    def test_confidence_above_one_fails(self):
        data = valid_record_data()
        data["confidence"] = 1.01

        with self.assertRaises(ValidationError):
            RawDrawingEquipmentRecord(**data)

    def test_blank_source_file_fails(self):
        data = valid_record_data()
        data["source_file"] = "   "

        with self.assertRaises(ValidationError):
            RawDrawingEquipmentRecord(**data)

    def test_blank_raw_equipment_label_fails(self):
        data = valid_record_data()
        data["raw_equipment_label"] = ""

        with self.assertRaises(ValidationError):
            RawDrawingEquipmentRecord(**data)

    def test_unresolved_equipment_type_is_preserved(self):
        data = valid_record_data()
        data["raw_equipment_type"] = "EAVAV"

        record = RawDrawingEquipmentRecord(**data)

        self.assertEqual(record.raw_equipment_type, "EAVAV")


if __name__ == "__main__":
    unittest.main()
