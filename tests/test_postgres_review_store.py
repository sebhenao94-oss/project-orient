import sys
import unittest
from pathlib import Path

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
    EvidenceSource,
    NormalizationStatus,
    RelationshipQuery,
    ReviewStore,
    SeverityHint,
    ZoneQuery,
)


class PostgresReviewStoreReadTests(unittest.TestCase):
    """A3 read methods loaded from the committed W6 snapshots."""

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
        self.assertEqual(len(settled), 8)

    def test_equipment_occurrences_are_aggregated_as_evidence(self):
        items = self.store.list_equipment(EquipmentQuery())
        evidenced = [item for item in items if item.evidence]
        self.assertTrue(evidenced)
        self.assertTrue(
            any(
                {EvidenceSource.TOPICS, EvidenceSource.DRAWING}.issubset(
                    {evidence.source for evidence in item.evidence}
                )
                for item in evidenced
            )
        )
        self.assertTrue(any(item.evidence_count > 1 for item in evidenced))

    def test_uncalibrated_source_confidence_is_not_promoted(self):
        items = self.store.list_equipment(EquipmentQuery())
        self.assertTrue(
            any(
                evidence.confidence is not None
                for item in items
                for evidence in item.evidence
            )
        )
        self.assertTrue(all(item.confidence is None for item in items))

    def test_equipment_floor_filter(self):
        items = self.store.list_equipment(EquipmentQuery(floor="Floor_99"))
        self.assertEqual(items, [])

    def test_list_relationships_loads_current_w6_candidates(self):
        view = self.store.list_relationships(RelationshipQuery())
        self.assertEqual(view.edge_count, 44)
        self.assertEqual(view.orphan_count, 38)
        self.assertFalse(view.passed)
        self.assertEqual(len(view.errors), 3)

    def test_list_relationships_wrong_property_scope_is_empty(self):
        view = self.store.list_relationships(RelationshipQuery(property_id="not-a-property"))
        self.assertEqual(view.edge_count, 0)
        self.assertEqual(view.orphan_count, 0)
        self.assertTrue(view.passed)

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

    def test_write_methods_are_present_for_a4(self):
        for method_name in (
            "open_session",
            "get_session",
            "record_action",
            "clear_action",
            "clear_all_actions",
            "commit_session",
        ):
            self.assertTrue(callable(getattr(self.store, method_name)))


if __name__ == "__main__":
    unittest.main()
