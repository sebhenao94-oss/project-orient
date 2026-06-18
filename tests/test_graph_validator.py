import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from graph_validator import validate  # noqa: E402


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
    def test_empty_edges_passes_with_orphans(self):
        equipment = {"VAV_2-01": "VAV", "AHU_2-01": "AHU"}
        report = validate([], equipment)
        self.assertTrue(report.passed)
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


if __name__ == "__main__":
    unittest.main()
