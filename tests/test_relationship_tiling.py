import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (PROJECT_ROOT, PROJECT_ROOT / "pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from relationship_tiling import union_edges  # noqa: E402


def edge(child, parent, ref="airRef", conf=None, conflict=False, reason=None, drawing="Floor_2A.png"):
    return {
        "child": child, "parent": parent, "ref_type": ref, "confidence": conf,
        "conflict": conflict, "conflict_reason": reason, "source_drawing": drawing,
    }


class UnionEdgesTests(unittest.TestCase):
    def test_distinct_edges_are_kept_separate(self):
        result = union_edges([edge("VAV_2-01", "AHU_2-01"), edge("VAV_2-02", "AHU_2-01")])
        self.assertEqual(len(result), 2)

    def test_same_edge_merges_keeps_max_confidence_and_counts_hits(self):
        result = union_edges([
            edge("VAV_2-01", "AHU_2-01", conf=0.6),
            edge("VAV_2-01", "AHU_2-01", conf=0.9),
        ])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].confidence, 0.9)
        self.assertEqual(result[0].tile_hits, 2)

    def test_conflict_is_ored_across_tiles(self):
        result = union_edges([
            edge("VAV_2-01", "AHU_2-01", conf=0.9, conflict=False),
            edge("VAV_2-01", "AHU_2-01", conf=0.5, conflict=True, reason="ambiguous tag"),
        ])
        self.assertTrue(result[0].conflict)
        self.assertEqual(result[0].conflict_reason, "ambiguous tag")

    def test_source_drawings_accumulate(self):
        result = union_edges([
            edge("VAV_2-01", "AHU_2-01", drawing="Floor_2A.png"),
            edge("VAV_2-01", "AHU_2-01", drawing="Floor_2B.png"),
        ])
        self.assertEqual(sorted(result[0].source_drawings), ["Floor_2A.png", "Floor_2B.png"])

    def test_water_ref_and_air_ref_to_same_pair_are_distinct(self):
        result = union_edges([
            edge("AHU_2-01", "CHW-PLANT_1", ref="chilledWaterRef"),
            edge("AHU_2-01", "HW-PLANT_1", ref="hotWaterRef"),
        ])
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
