import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from extraction import (  # noqa: E402
    RAW_DRAWING_EQUIPMENT_HEADERS,
    RawSnapshotValidationError,
    load_raw_drawing_equipment_snapshot,
)


SEEDED_SNAPSHOT = (
    PROJECT_ROOT
    / "data"
    / "snapshots"
    / "w03"
    / "equipment_from_drawings_raw.csv"
)


def _write_snapshot(rows, headers=RAW_DRAWING_EQUIPMENT_HEADERS):
    temp_dir = tempfile.TemporaryDirectory()
    csv_path = Path(temp_dir.name) / "equipment_from_drawings_raw.csv"
    lines = [",".join(headers)]
    lines.extend(",".join(row) for row in rows)
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return temp_dir, csv_path


def _valid_row():
    return [
        "b470b97b-4ea7-481c-97b7-22a81a219587",
        "Floor_02",
        "Floor_2A.pdf",
        "mechanical_drawing",
        "AHU 2-2",
        "AHU",
        "Equipment label shown on mechanical floor plan",
        "0.98",
    ]


def _file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestRawDrawingEquipmentSnapshotLoader(unittest.TestCase):
    def test_seeded_snapshot_loads_three_records(self):
        records = load_raw_drawing_equipment_snapshot(SEEDED_SNAPSHOT)

        self.assertEqual(len(records), 3)

    def test_record_order_is_preserved(self):
        records = load_raw_drawing_equipment_snapshot(SEEDED_SNAPSHOT)

        self.assertEqual(
            [record.raw_equipment_label for record in records],
            ["AHU 02 A", "VAVRH_2_1", "AHU 2-2"],
        )

    def test_malformed_confidence_fails_with_csv_row_number(self):
        row = _valid_row()
        row[-1] = "not-a-confidence"
        temp_dir, csv_path = _write_snapshot([row])
        self.addCleanup(temp_dir.cleanup)

        with self.assertRaisesRegex(RawSnapshotValidationError, "CSV row 2"):
            load_raw_drawing_equipment_snapshot(csv_path)

    def test_non_floor_02_row_fails_with_csv_row_number(self):
        row = _valid_row()
        row[1] = "Floor_03"
        temp_dir, csv_path = _write_snapshot([row])
        self.addCleanup(temp_dir.cleanup)

        with self.assertRaisesRegex(RawSnapshotValidationError, "CSV row 2"):
            load_raw_drawing_equipment_snapshot(csv_path)

    def test_missing_required_header_fails_clearly(self):
        headers = [
            header
            for header in RAW_DRAWING_EQUIPMENT_HEADERS
            if header != "raw_equipment_label"
        ]
        row = _valid_row()
        row.pop(4)
        temp_dir, csv_path = _write_snapshot([row], headers=headers)
        self.addCleanup(temp_dir.cleanup)

        with self.assertRaisesRegex(
            RawSnapshotValidationError,
            "missing required header\(s\): raw_equipment_label",
        ):
            load_raw_drawing_equipment_snapshot(csv_path)

    def test_unexpected_extra_header_fails_clearly(self):
        headers = list(RAW_DRAWING_EQUIPMENT_HEADERS) + ["extra_column"]
        row = _valid_row() + ["unexpected"]
        temp_dir, csv_path = _write_snapshot([row], headers=headers)
        self.addCleanup(temp_dir.cleanup)

        with self.assertRaisesRegex(
            RawSnapshotValidationError,
            "unexpected header\(s\): extra_column",
        ):
            load_raw_drawing_equipment_snapshot(csv_path)

    def test_source_csv_is_unchanged_after_loading(self):
        before_digest = _file_digest(SEEDED_SNAPSHOT)

        load_raw_drawing_equipment_snapshot(SEEDED_SNAPSHOT)

        after_digest = _file_digest(SEEDED_SNAPSHOT)
        self.assertEqual(after_digest, before_digest)


if __name__ == "__main__":
    unittest.main()
