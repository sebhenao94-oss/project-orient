import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from graph_validator import (  # noqa: E402
    DEFAULT_CANONICAL_EQUIPMENT,
    DEFAULT_RELATIONSHIPS,
    DEFAULT_REPORT_OUT,
    load_equipment_catalog,
    load_relationship_document,
    validate,
)


WORKED_EXAMPLE_EQUIPMENT = {
    "AHU_1-01": "AHU",
    "VAVRH_1-01": "VAV-RH-HW",
    "VAV-RH-HW_1-01": "VAV-RH-HW",
    "HW-PLANT_1": "HW-PLANT",
    "CHW-PLANT_1": "CHW-PLANT",
    "COND-PLANT_1": "COND-PLANT",
}

WORKED_EXAMPLE_EDGES = [
    {"child": "VAVRH_1-01", "parent": "AHU_1-01", "ref_type": "airRef", "confidence": 0.95, "conflict": False},
    {"child": "VAV-RH-HW_1-01", "parent": "AHU_1-01", "ref_type": "airRef", "confidence": 0.95, "conflict": False},
    {"child": "AHU_1-01", "parent": "CHW-PLANT_1", "ref_type": "chilledWaterRef", "confidence": 0.9, "conflict": False},
    {"child": "AHU_1-01", "parent": "HW-PLANT_1", "ref_type": "hotWaterRef", "confidence": 0.9, "conflict": False},
    {"child": "VAV-RH-HW_1-01", "parent": "HW-PLANT_1", "ref_type": "hotWaterRef", "confidence": 0.88, "conflict": False},
]


class TestValidate(unittest.TestCase):
    def test_empty_edges_fails_with_orphans(self):
        equipment = {"VAV_2-01": "VAV", "AHU_2-01": "AHU"}
        report = validate([], equipment)
        self.assertFalse(report.passed)
        self.assertEqual(report.edge_count, 0)
        orphan_nodes = {node for finding in report.orphans for node in finding.nodes}
        self.assertIn("VAV_2-01", orphan_nodes)
        self.assertNotIn("AHU_2-01", orphan_nodes)  # AHU is not a terminal

    def test_worked_example_passes(self):
        report = validate(WORKED_EXAMPLE_EDGES, WORKED_EXAMPLE_EQUIPMENT)
        self.assertTrue(report.passed)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.orphans, [])  # both terminals have an airRef

    def test_unknown_node_is_error(self):
        report = validate(
            [{"child": "VAV_2-01", "parent": "AHU_2-99", "ref_type": "airRef", "confidence": 0.9}],
            {"VAV_2-01": "VAV", "AHU_2-01": "AHU"},
        )
        self.assertFalse(report.passed)
        self.assertTrue(any(f.check_id == "unknown_node" for f in report.errors))

    def test_multiple_air_parents_is_error(self):
        equipment = {"VAV_2-01": "VAV", "AHU_2-01": "AHU", "AHU_2-02": "AHU"}
        edges = [
            {"child": "VAV_2-01", "parent": "AHU_2-01", "ref_type": "airRef", "confidence": 0.9},
            {"child": "VAV_2-01", "parent": "AHU_2-02", "ref_type": "airRef", "confidence": 0.9},
        ]
        report = validate(edges, equipment)
        self.assertTrue(any(f.check_id == "multiple_air_parents" for f in report.errors))

    def test_cycle_is_error(self):
        equipment = {"AHU_2-01": "AHU", "AHU_2-02": "AHU"}
        edges = [
            {"child": "AHU_2-01", "parent": "AHU_2-02", "ref_type": "systemRef", "confidence": 0.9},
            {"child": "AHU_2-02", "parent": "AHU_2-01", "ref_type": "systemRef", "confidence": 0.9},
        ]
        report = validate(edges, equipment)
        self.assertTrue(any(f.check_id == "cycle" for f in report.errors))

    def test_airref_parent_must_be_air_source(self):
        equipment = {"VAV_2-01": "VAV", "VAV_2-02": "VAV"}
        edges = [{"child": "VAV_2-01", "parent": "VAV_2-02", "ref_type": "airRef", "confidence": 0.9}]
        report = validate(edges, equipment)
        self.assertTrue(any(f.check_id == "ref_type_sanity" for f in report.errors))

    def test_water_ref_parent_must_be_plant(self):
        equipment = {"AHU_2-01": "AHU", "AHU_2-02": "AHU"}
        edges = [{"child": "AHU_2-01", "parent": "AHU_2-02", "ref_type": "chilledWaterRef", "confidence": 0.9}]
        report = validate(edges, equipment)
        self.assertTrue(any(f.check_id == "ref_type_sanity" for f in report.errors))

    def test_low_confidence_and_conflict_are_review_items(self):
        equipment = {"VAV_2-01": "VAV", "AHU_2-01": "AHU"}
        edges = [
            {"child": "VAV_2-01", "parent": "AHU_2-01", "ref_type": "airRef", "confidence": 0.5, "conflict": False},
            {"child": "VAV_2-01", "parent": "AHU_2-01", "ref_type": "airRef", "confidence": 0.9, "conflict": True},
        ]
        report = validate(edges, equipment)
        # No structural error from a single duplicate-parent? Two airRef to same parent -> still one parent set.
        self.assertEqual(len(report.review_items), 2)

    def test_normalized_raw_alias_resolves_to_canonical_equipment(self):
        equipment = {"VAV-RH-HW_2-01": "VAV-RH-HW", "AHU_2-A": "AHU"}
        edges = [
            {
                "child": "VAVRH_02_1",
                "child_raw": "VAVRH_2_01",
                "parent": "AHU 02 A",
                "parent_raw": "AHU_02A",
                "ref_type": "airRef",
                "confidence": 0.9,
            }
        ]
        aliases = {"VAVRH_2_01": "VAV-RH-HW_2-01", "AHU_02A": "AHU_2-A"}
        report = validate(edges, equipment, aliases=aliases)
        self.assertTrue(report.passed)
        self.assertEqual(report.accepted_edge_count, 1)
        self.assertEqual(report.alias_resolution_count, 2)
        self.assertEqual(report.unresolved_endpoint_count, 0)

    def test_canonical_and_raw_alias_disagreement_is_not_silently_chosen(self):
        equipment = {"VAV_2-01": "VAV", "VAV_2-02": "VAV", "AHU_2-A": "AHU"}
        edges = [
            {
                "child": "VAV_2-01",
                "child_raw": "VAV_02_02",
                "parent": "AHU_2-A",
                "ref_type": "airRef",
                "confidence": 0.9,
            }
        ]
        report = validate(edges, equipment)
        self.assertFalse(report.passed)
        self.assertEqual(report.accepted_edge_count, 0)
        self.assertEqual(report.ambiguous_endpoint_count, 1)
        self.assertTrue(any(f.check_id == "ambiguous_node" for f in report.errors))
        self.assertTrue(
            any(f.check_id == "endpoint_resolution_conflict" for f in report.review_items)
        )

    def test_conflicted_edge_does_not_satisfy_orphan_check(self):
        equipment = {"VAV_2-01": "VAV", "AHU_2-A": "AHU"}
        edges = [
            {
                "child": "VAV_2-01",
                "parent": "AHU_2-A",
                "ref_type": "airRef",
                "confidence": 0.9,
                "conflict": True,
                "review_required": True,
            }
        ]
        report = validate(edges, equipment)
        self.assertFalse(report.passed)
        self.assertEqual(report.accepted_edge_count, 0)
        self.assertEqual(len(report.orphans), 1)
        self.assertEqual(len(report.review_items), 1)

    def test_upstream_review_required_is_preserved_above_threshold(self):
        equipment = {"VAV_2-01": "VAV", "AHU_2-A": "AHU"}
        edges = [
            {
                "child": "VAV_2-01",
                "parent": "AHU_2-A",
                "ref_type": "airRef",
                "confidence": 0.95,
                "review_required": True,
                "review_reason": "subtype unresolved",
            }
        ]
        report = validate(edges, equipment)
        self.assertTrue(report.passed)
        self.assertEqual(len(report.review_items), 1)
        self.assertIn("subtype unresolved", report.review_items[0].message)

    def test_repeated_candidate_endpoint_is_one_error_and_one_review_item(self):
        equipment = {"OAVAV_2-01": "OAVAV", "OAVAV_2-02": "OAVAV"}
        edges = [
            {"child": "OAVAV_2-01", "parent": "DOAS_22_1", "ref_type": "airRef"},
            {"child": "OAVAV_2-02", "parent": "DOAS_22_1", "ref_type": "airRef"},
        ]
        report = validate(edges, equipment, equipment_candidates=["DOAS_22_1"])
        self.assertEqual(report.unresolved_endpoint_count, 1)
        self.assertEqual(len([f for f in report.errors if f.check_id == "unknown_node"]), 1)
        unresolved_reviews = [
            f for f in report.review_items if f.check_id == "unresolved_endpoint"
        ]
        self.assertEqual(len(unresolved_reviews), 1)
        self.assertIn("referenced by 2 edge(s)", unresolved_reviews[0].message)
        self.assertIn("equipment_candidates", unresolved_reviews[0].message)


class TestLoadersAndCurrentSnapshot(unittest.TestCase):
    def test_catalog_indexes_topic_and_drawing_raw_labels(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "canonical.csv"
            csv_path.write_text(
                "canonical_name,equipment_type,topics_raw_label,drawing_raw_label\n"
                "VAV-RH-HW_2-01,VAV-RH-HW,VAVRH_2_01,VAVRH 02 1\n",
                encoding="utf-8",
            )
            catalog = load_equipment_catalog(csv_path)
        self.assertEqual(catalog.alias_to_canonical["VAVRH_2_1"], "VAV-RH-HW_2-01")
        self.assertEqual(catalog.ambiguous_aliases, {})

    def test_catalog_preserves_alias_collisions_for_validator_review(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "canonical.csv"
            csv_path.write_text(
                "canonical_name,equipment_type,topics_raw_label,drawing_raw_label\n"
                "VAV_2-01,VAV,VAV_SHARED,\n"
                "VAV_2-02,VAV,VAV_SHARED,\n"
                "AHU_2-A,AHU,,\n",
                encoding="utf-8",
            )
            catalog = load_equipment_catalog(csv_path)

        self.assertEqual(
            catalog.ambiguous_aliases["VAV_SHARED"], ("VAV_2-01", "VAV_2-02")
        )
        report = validate(
            [
                {
                    "child": "VAV_SHARED",
                    "parent": "AHU_2-A",
                    "ref_type": "airRef",
                    "confidence": 0.9,
                }
            ],
            catalog.equipment,
            aliases=catalog.alias_to_canonical,
            ambiguous_aliases=catalog.ambiguous_aliases,
        )
        self.assertEqual(report.ambiguous_endpoint_count, 1)
        self.assertEqual(report.accepted_edge_count, 0)

    def test_defaults_and_current_w06_snapshot_have_honest_counts(self):
        self.assertIn("w06", DEFAULT_RELATIONSHIPS.parts)
        self.assertIn("w06", DEFAULT_CANONICAL_EQUIPMENT.parts)
        self.assertIn("w06", DEFAULT_REPORT_OUT.parts)

        document = load_relationship_document(DEFAULT_RELATIONSHIPS)
        catalog = load_equipment_catalog(DEFAULT_CANONICAL_EQUIPMENT)
        report = validate(
            document["relationships"],
            catalog.equipment,
            aliases=catalog.alias_to_canonical,
            ambiguous_aliases=catalog.ambiguous_aliases,
            equipment_candidates=document["equipment_candidates"],
        )
        self.assertFalse(report.passed)
        self.assertEqual(report.edge_count, 44)
        self.assertEqual(report.accepted_edge_count, 12)
        self.assertEqual(report.equipment_count, 56)
        self.assertEqual(report.alias_resolution_count, 0)
        self.assertEqual(report.unresolved_endpoint_count, 3)
        self.assertEqual(report.ambiguous_endpoint_count, 0)
        self.assertEqual(len(report.errors), 3)
        self.assertEqual(len(report.orphans), 38)
        self.assertEqual(len(report.review_items), 19)


if __name__ == "__main__":
    unittest.main()
