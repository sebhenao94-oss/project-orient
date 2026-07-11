import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from discrepancy import build_canonical_rows  # noqa: E402
from extraction import _dedupe_within_image  # noqa: E402
from models import EquipmentExtractionCandidate  # noqa: E402
from normalization import reconcile_floor_02  # noqa: E402


def topics_row(raw_label, inferred_type="AHU"):
    return {
        "snapshot_version": "w03",
        "property_id": "prop-1",
        "property_name": "msa_orient_building_1",
        "floor": "Floor_02",
        "raw_equipment_context": raw_label,
        "raw_label": raw_label,
        "inferred_raw_type": inferred_type,
        "topic_count": "5",
        "evidence_strength": "multiple_point_evidence",
        "source_type": "topics",
        "review_required": "false",
        "review_reason": "",
    }


def drawing_row(raw_label, canonical, source_filename, equipment_type="AHU"):
    return {
        "snapshot_version": "w03",
        "property_name": "msa_orient_building_1",
        "property_id": "prop-1",
        "floor": "Floor_02",
        "source_filename": source_filename,
        "source_relative_path": source_filename,
        "source_sha256": "a" * 64,
        "pdf_page_number": "",
        "prompt_version": "equipment_extraction_v4",
        "model_id": "claude-haiku-4-5",
        "raw_label": raw_label,
        "llm_proposed_canonical_name": canonical,
        "equipment_type": equipment_type,
        "confidence": "0.99",
        "run_status": "succeeded",
        "review_required": "false",
        "review_reason": "",
    }


class TestSourceFilesAggregation(unittest.TestCase):
    def test_all_contributing_drawings_are_listed_per_unit(self):
        records = reconcile_floor_02(
            [topics_row("AHU-02A")],
            [
                drawing_row("AHU 02 A", "AHU_02A", "ahu_02a.png"),
                drawing_row("AHU 02 A", "AHU_02A", "mech.pdf"),
                drawing_row("AHU 02 A", "AHU_02A", "ahu_02a.png"),  # repeat file
            ],
            {},
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_files, "ahu_02a.png;mech.pdf")

    def test_topics_only_unit_has_no_source_files(self):
        records = reconcile_floor_02([topics_row("AHU-02B")], [], {})
        self.assertEqual(records[0].source_files, "")


def normalized_row(key, canonical_name=None, category="matched", status="settled", **overrides):
    row = {
        "snapshot_version": "w04",
        "property_id": "prop-1",
        "property_name": "msa_orient_building_1",
        "floor": "Floor_02",
        "canonical_name": canonical_name or key,
        "canonical_key": key,
        "equipment_type": key.split("_")[0],
        "discrepancy_category": category,
        "status": status,
        "in_topics": "true",
        "in_drawings": "true",
        "topics_raw_label": key,
        "topics_inferred_type": key.split("_")[0],
        "drawing_raw_label": key,
        "drawing_equipment_type": key.split("_")[0],
        "source_files": "",
        "review_required": "false",
        "review_reason": "",
    }
    row.update(overrides)
    return row


class TestRelationshipRefColumns(unittest.TestCase):
    def _rows(self):
        return [
            normalized_row("AHU_02A"),
            normalized_row("VAV_2_1"),
            normalized_row("VAV_2_5"),
            normalized_row("VAV_2_9"),
        ]

    def test_trusted_edge_fills_air_ref_with_canonical_parent_name(self):
        doc = {
            "relationships": [
                {
                    "child": "VAV_2-01",
                    "parent": "AHU_2-A",
                    "ref_type": "airRef",
                    "conflict": False,
                    "review_required": False,
                }
            ]
        }
        rows = build_canonical_rows(self._rows(), doc)
        vav = next(row for row in rows if row["raw_equipment_type"] == "VAV" and "1" in row["canonical_name"].split("-")[-1])
        ahu = next(row for row in rows if row["raw_equipment_type"] == "AHU")
        self.assertEqual(vav["airRef"], ahu["canonical_name"])
        self.assertEqual(vav["review_required"], "false")

    def test_conflicting_edge_flags_review_and_leaves_ref_empty(self):
        doc = {
            "relationships": [
                {
                    "child": "VAV_2-05",
                    "parent": "AHU_2-A",
                    "ref_type": "airRef",
                    "conflict": True,
                    "conflict_reason": "drawing shows AHU-3",
                }
            ]
        }
        rows = build_canonical_rows(self._rows(), doc)
        vav = next(row for row in rows if "airRef conflict" in row["review_reason"])
        self.assertEqual(vav["airRef"], "")
        self.assertEqual(vav["review_required"], "true")
        self.assertIn("drawing shows AHU-3", vav["review_reason"])

    def test_flagged_edge_fills_ref_but_routes_to_review(self):
        doc = {
            "relationships": [
                {
                    "child": "VAV_2-09",
                    "parent": "AHU_2-A",
                    "ref_type": "airRef",
                    "conflict": False,
                    "review_required": True,
                    "review_reason": "values dashed (unit offline)",
                }
            ]
        }
        rows = build_canonical_rows(self._rows(), doc)
        vav = next(row for row in rows if row["airRef"])
        self.assertEqual(vav["review_required"], "true")
        self.assertIn("inferred but unconfirmed", vav["review_reason"])

    def test_unknown_child_edge_is_ignored(self):
        doc = {
            "relationships": [
                {"child": "FCU_9-99", "parent": "AHU_2-A", "ref_type": "airRef"}
            ]
        }
        rows = build_canonical_rows(self._rows(), doc)
        self.assertTrue(all(row["airRef"] == "" for row in rows))

    def test_source_files_passes_through_to_canonical_rows(self):
        rows = build_canonical_rows(
            [normalized_row("AHU_02A", source_files="ahu_02a.png;mech.pdf")]
        )
        self.assertEqual(rows[0]["source_files"], "ahu_02a.png;mech.pdf")


class TestWithinImageDedup(unittest.TestCase):
    def _candidate(self, canonical, confidence=0.9, raw=None, equipment_type="FCU"):
        return EquipmentExtractionCandidate(
            raw_label=raw or canonical,
            canonical_name=canonical,
            equipment_type=equipment_type,
            confidence=confidence,
        )

    def test_repeated_label_is_suppressed_keeping_highest_confidence(self):
        deduped = _dedupe_within_image(
            [
                self._candidate("FCU_02_5", confidence=0.80),
                self._candidate("FCU_02_5", confidence=0.95),
                self._candidate("FCU_02_6", confidence=0.90),
            ]
        )
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0].canonical_name, "FCU_02_5")
        self.assertEqual(deduped[0].confidence, 0.95)

    def test_separator_and_zero_padding_variants_collapse(self):
        deduped = _dedupe_within_image(
            [
                self._candidate("FCU_02_5", confidence=0.80),
                self._candidate("FCU-2-5", confidence=0.70),
            ]
        )
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].confidence, 0.80)

    def test_distinct_units_survive(self):
        deduped = _dedupe_within_image(
            [
                self._candidate("AHU_02A", equipment_type="AHU"),
                self._candidate("AHU_02C", equipment_type="AHU"),
            ]
        )
        self.assertEqual(len(deduped), 2)


if __name__ == "__main__":
    unittest.main()
