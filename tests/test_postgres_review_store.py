import sys
import unittest
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
for path in (PROJECT_ROOT, PIPELINE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from review_store import PostgresReviewStore  # noqa: E402
from review_api.contracts import (  # noqa: E402
    DiscrepancyGroupBy,
    DiscrepancyQuery,
    DiscrepancyStatus,
    EquipmentQuery,
    NormalizationStatus,
    RelationshipQuery,
    ReviewStore,
    SeverityHint,
    ZoneQuery,
)


class PostgresReviewStoreReadTests(unittest.TestCase):
    """A3 read methods loaded from the committed W4 snapshots."""

    def setUp(self):
        self.store = PostgresReviewStore()

    def test_store_satisfies_review_store_protocol(self):
        self.assertIsInstance(self.store, ReviewStore)

    def test_list_equipment_loads_full_union(self):
        self.assertEqual(len(self.store.list_equipment(EquipmentQuery())), 56)

    def test_equipment_status_filter_returns_settled_matches(self):
        settled = self.store.list_equipment(
            EquipmentQuery(status=NormalizationStatus.SETTLED)
        )
        self.assertEqual(len(settled), 11)

    def test_equipment_floor_filter(self):
        items = self.store.list_equipment(EquipmentQuery(floor="Floor_99"))
        self.assertEqual(items, [])

    def test_list_relationships_renders_empty_set_correctly(self):
        view = self.store.list_relationships(RelationshipQuery())
        self.assertEqual(view.edge_count, 0)
        self.assertEqual(view.orphan_count, 50)
        self.assertTrue(view.passed)
        self.assertEqual(view.errors, [])

    def test_discrepancy_counts_and_floor1_resolution(self):
        view = self.store.list_discrepancies(DiscrepancyQuery())
        self.assertEqual(len(view.items), 56)
        self.assertEqual(view.counts.get("matched"), 11)
        self.assertEqual(view.counts.get("missing_from_drawings"), 19)
        self.assertEqual(view.counts.get("missing_from_points"), 19)
        self.assertEqual(view.counts.get("resolved_out_of_scope"), 7)
        self.assertNotIn("floor_ambiguous", view.counts)  # remapped, not pending
        resolved = [
            i for i in view.items if i.status == DiscrepancyStatus.RESOLVED_OUT_OF_SCOPE
        ]
        self.assertEqual(len(resolved), 7)
        self.assertTrue(all(i.resolved_floor == "1" for i in resolved))

    def test_discrepancy_grouping_by_severity_isolates_high_ahus(self):
        view = self.store.list_discrepancies(
            DiscrepancyQuery(group_by=DiscrepancyGroupBy.SEVERITY_HINT)
        )
        self.assertIsNotNone(view.groups)
        self.assertEqual(len(view.groups.get("high", [])), 4)  # the 4 AHUs

    def test_discrepancy_severity_filter(self):
        view = self.store.list_discrepancies(DiscrepancyQuery(severity=SeverityHint.HIGH))
        self.assertEqual(len(view.items), 4)

    def test_discrepancy_rollups_are_engineer_facing(self):
        view = self.store.list_discrepancies(DiscrepancyQuery())
        self.assertTrue(any("missing from drawings" in r for r in view.rollups))
        self.assertTrue(any(r.startswith("Floor 2:") for r in view.rollups))

    def test_list_zones_is_empty_until_w7(self):
        self.assertEqual(self.store.list_zones(ZoneQuery()), [])

    def test_write_methods_deferred_to_a4(self):
        with self.assertRaises(NotImplementedError):
            self.store.commit_session(uuid4())


if __name__ == "__main__":
    unittest.main()
