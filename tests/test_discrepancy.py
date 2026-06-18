import csv
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
REAL_NORMALIZED = PROJECT_ROOT / "data" / "snapshots" / "w04" / "normalized_equipment_floor_02.csv"
sys.path.insert(0, str(PIPELINE_DIR))

import discrepancy  # noqa: E402
from discrepancy import (  # noqa: E402
    DiscrepancyReportRecord,
    build_canonical_rows,
    build_discrepancy_records,
    load_normalized_rows,
    summarize,
)


def normalized_row(canonical_key, equipment_type, category, in_topics=True, in_drawings=True, **extra):
    row = {
        "snapshot_version": "w04",
        "property_id": "pid",
        "property_name": "msa_orient_building_1",
        "floor": "Floor_02",
        "canonical_name": canonical_key,
        "canonical_key": canonical_key,
        "equipment_type": equipment_type,
        "discrepancy_category": category,
        "status": "settled" if category == "matched" else "review_required",
        "in_topics": "true" if in_topics else "false",
        "in_drawings": "true" if in_drawings else "false",
        "topics_raw_label": extra.get("topics_raw_label", ""),
        "drawing_raw_label": extra.get("drawing_raw_label", ""),
        "review_required": "false" if category == "matched" else "true",
        "review_reason": extra.get("review_reason", ""),
    }
    return row


class TestCanonicalRows(unittest.TestCase):
    def test_clean_row_gets_convention_and_mapped_type(self):
        rows = build_canonical_rows([normalized_row("VAVRH_2_1", "VAVRH", "matched")])
        self.assertEqual(rows[0]["equipment_type"], "VAV-RH-HW")
        self.assertEqual(rows[0]["canonical_name"], "VAV-RH-HW_2-1")
        self.assertEqual(rows[0]["review_required"], "true")  # VAVRH subtype flag

    def test_misread_label_preserves_key(self):
        rows = build_canonical_rows([normalized_row("DAWNV_2_9", "VAV", "drawing_only", in_topics=False)])
        self.assertEqual(rows[0]["canonical_name"], "DAWNV_2_9")
        self.assertEqual(rows[0]["review_required"], "true")
        self.assertIn("misread", rows[0]["review_reason"])

    def test_floor_ambiguous_preserves_key(self):
        rows = build_canonical_rows([normalized_row("OAVAV_1_2", "OAVAV", "floor_ambiguous", in_drawings=False)])
        self.assertEqual(rows[0]["canonical_name"], "OAVAV_1_2")
        self.assertIn("floor contested", rows[0]["review_reason"])

    def test_collision_falls_back_to_keys(self):
        rows = build_canonical_rows(
            [
                normalized_row("VAV_2_1", "VAV", "matched"),
                normalized_row("VAV_02_1", "VAV", "topics_only", in_drawings=False),
            ]
        )
        names = {row["canonical_name"] for row in rows}
        self.assertEqual(names, {"VAV_2_1", "VAV_02_1"})
        for row in rows:
            self.assertIn("collision", row["review_reason"])


class TestDiscrepancyRecords(unittest.TestCase):
    def _record(self, category, equipment_type="VAV", **kw):
        canonical = build_canonical_rows([normalized_row("X_2_1", equipment_type, category, **kw)])
        return build_discrepancy_records(canonical)[0]

    def test_status_mapping(self):
        self.assertEqual(self._record("matched").status, "matched")
        self.assertEqual(self._record("topics_only", in_drawings=False).status, "missing_from_drawings")
        self.assertEqual(self._record("drawing_only", in_topics=False).status, "missing_from_points")
        self.assertEqual(self._record("floor_ambiguous", in_drawings=False).status, "floor_ambiguous")

    def test_severity_high_for_ahu_gap(self):
        record = self._record("topics_only", equipment_type="AHU", in_drawings=False)
        self.assertEqual(record.severity_hint, "high")

    def test_severity_medium_for_terminal_gap(self):
        record = self._record("topics_only", equipment_type="VAV", in_drawings=False)
        self.assertEqual(record.severity_hint, "medium")

    def test_severity_low_for_matched(self):
        self.assertEqual(self._record("matched").severity_hint, "low")

    def test_record_carries_provenance(self):
        record = self._record("matched", topics_raw_label="VAV_02_01", drawing_raw_label="VAV_2_01")
        self.assertEqual(record.evidence_point, "VAV_02_01")
        self.assertEqual(record.evidence_drawing, "VAV_2_01")
        self.assertTrue(record.in_points)
        self.assertTrue(record.in_drawings)


class TestRealSnapshot(unittest.TestCase):
    def test_real_normalized_snapshot_reconciles(self):
        rows = load_normalized_rows(REAL_NORMALIZED)
        canonical = build_canonical_rows(rows)
        records = build_discrepancy_records(canonical)

        # Canonical names are unique (they become equipment_id downstream).
        names = [row["canonical_name"] for row in canonical]
        self.assertEqual(len(names), len(set(names)))

        summary = summarize(records)
        self.assertEqual(summary.get("matched"), 11)
        self.assertEqual(summary.get("missing_from_drawings"), 19)
        self.assertEqual(summary.get("missing_from_points"), 19)
        self.assertEqual(summary.get("floor_ambiguous"), 7)


class TestWriters(unittest.TestCase):
    def test_round_trip(self):
        rows = build_canonical_rows([normalized_row("AHU_2_1", "AHU", "matched")])
        records = build_discrepancy_records(rows)
        with tempfile.TemporaryDirectory() as tmp:
            canonical_path = Path(tmp) / "canonical.csv"
            report_path = Path(tmp) / "report.csv"
            discrepancy.write_canonical_equipment(rows, canonical_path)
            discrepancy.write_discrepancy_report(records, report_path)

            with report_path.open(encoding="utf-8-sig", newline="") as handle:
                report_rows = list(csv.DictReader(handle))

        self.assertEqual(report_rows[0]["equipment_id"], "AHU_2-1")
        self.assertEqual(report_rows[0]["equipment_type"], "AHU")
        # Re-validate through the model.
        DiscrepancyReportRecord(
            building=report_rows[0]["building"],
            floor=report_rows[0]["floor"],
            equipment_type=report_rows[0]["equipment_type"],
            equipment_id=report_rows[0]["equipment_id"],
            in_points=report_rows[0]["in_points"] == "true",
            in_drawings=report_rows[0]["in_drawings"] == "true",
            status=report_rows[0]["status"],
            severity_hint=report_rows[0]["severity_hint"],
        )


if __name__ == "__main__":
    unittest.main()
