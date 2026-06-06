import sys
import unittest
from pathlib import Path

from pydantic import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from models import RawDrawingEquipmentRecord  # noqa: E402


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
