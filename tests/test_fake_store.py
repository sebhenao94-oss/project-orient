"""Offline tests for the W5 FakeReviewStore (Track B).

Verifies the store reproduces the committed W4 Floor-02 data faithfully and that
the in-memory session/action/commit semantics match the agreed action rules.
No network, AWS, or DB.
"""

import sys
import unittest
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.models import NormalizationStatus  # noqa: E402
from review_api.contracts import (  # noqa: E402
    ActionRequest,
    ActionType,
    DiscrepancyGroupBy,
    DiscrepancyQuery,
    DiscrepancyStatus,
    EquipmentQuery,
    EquipmentSort,
    ItemType,
    RelationshipQuery,
    SessionStatus,
    SeverityHint,
    ZoneQuery,
)
from review_api.fake_store import FakeReviewStore  # noqa: E402

PROPERTY_ID = "b470b97b-4ea7-481c-97b7-22a81a219587"


class FakeStoreReadTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeReviewStore()

    def test_equipment_count_and_settled(self):
        items = self.store.list_equipment(EquipmentQuery())
        self.assertEqual(len(items), 56)
        settled = [it for it in items if it.status == NormalizationStatus.SETTLED]
        self.assertEqual(len(settled), 11)

    def test_equipment_confidence_unscored(self):
        items = self.store.list_equipment(EquipmentQuery())
        self.assertTrue(all(it.confidence is None for it in items))

    def test_equipment_evidence_present(self):
        items = self.store.list_equipment(EquipmentQuery())
        self.assertTrue(all(it.evidence_count >= 1 for it in items))

    def test_equipment_default_sort_is_deterministic(self):
        first = self.store.list_equipment(EquipmentQuery())
        second = self.store.list_equipment(EquipmentQuery())
        self.assertEqual(
            [it.canonical_name for it in first],
            [it.canonical_name for it in second],
        )
        # All unscored, so default confidence_asc falls back to name order.
        names = [it.canonical_name for it in first]
        self.assertEqual(names, sorted(names))

    def test_equipment_filter_review_required(self):
        flagged = self.store.list_equipment(EquipmentQuery(review_required=True))
        self.assertTrue(flagged)
        self.assertTrue(all(it.review_required for it in flagged))

    def test_equipment_filter_status_settled(self):
        settled = self.store.list_equipment(
            EquipmentQuery(status=NormalizationStatus.SETTLED)
        )
        self.assertEqual(len(settled), 11)

    def test_discrepancy_counts(self):
        view = self.store.list_discrepancies(DiscrepancyQuery())
        self.assertEqual(
            view.counts,
            {
                "matched": 11,
                "missing_from_drawings": 19,
                "missing_from_points": 19,
                "resolved_out_of_scope": 7,
            },
        )

    def test_floor_ambiguous_pre_resolved(self):
        resolved = self.store.list_discrepancies(
            DiscrepancyQuery(status=DiscrepancyStatus.RESOLVED_OUT_OF_SCOPE)
        )
        self.assertEqual(len(resolved.items), 7)
        self.assertTrue(all(it.resolved_floor == "1" for it in resolved.items))

    def test_discrepancy_group_by_equipment_type(self):
        view = self.store.list_discrepancies(
            DiscrepancyQuery(group_by=DiscrepancyGroupBy.EQUIPMENT_TYPE)
        )
        self.assertEqual(view.group_by, DiscrepancyGroupBy.EQUIPMENT_TYPE)
        self.assertIn("AHU", view.groups)
        total = sum(len(rows) for rows in view.groups.values())
        self.assertEqual(total, len(view.items))

    def test_discrepancy_group_by_floor_and_severity(self):
        by_floor = self.store.list_discrepancies(
            DiscrepancyQuery(group_by=DiscrepancyGroupBy.FLOOR)
        )
        self.assertEqual(list(by_floor.groups.keys()), ["Floor_02"])
        by_sev = self.store.list_discrepancies(
            DiscrepancyQuery(group_by=DiscrepancyGroupBy.SEVERITY_HINT)
        )
        self.assertEqual(set(by_sev.groups.keys()), {"high", "medium", "low"})

    def test_discrepancy_severity_filter(self):
        high = self.store.list_discrepancies(
            DiscrepancyQuery(severity=SeverityHint.HIGH)
        )
        self.assertTrue(high.items)
        self.assertTrue(all(it.severity_hint == SeverityHint.HIGH for it in high.items))

    def test_discrepancy_rollups_headline(self):
        view = self.store.list_discrepancies(DiscrepancyQuery())
        self.assertIn(
            "Floor_02: 4 AHU missing from drawings (high severity)", view.rollups
        )

    def test_relationships_w06_graphics_snapshot(self):
        # The W6 graphics-derived snapshot supersedes the W4 empty set: 44
        # candidate edges; passed=false with unknown_node errors is EXPECTED
        # until the reviewer confirms the discovered DOAS/plant candidates.
        view = self.store.list_relationships(RelationshipQuery())
        self.assertEqual(view.edge_count, 44)
        self.assertEqual(view.orphan_count, 30)
        self.assertFalse(view.passed)
        self.assertTrue(all(f.check_id == "unknown_node" for f in view.errors))
        conflicted = [e for e in view.edges if e.conflict]
        self.assertEqual(
            [(e.child, e.parent) for e in conflicted],
            [("VAV-RH-HW_2-01", "AHU_2-A")],
        )
        flagged = [e for e in view.edges if e.review_required]
        self.assertEqual(len(flagged), 16)
        self.assertTrue(all(e.review_reason for e in flagged))

    def test_relationships_floor_scope_returns_full_view(self):
        # The reconciled RelationshipQuery scopes by property/floor only; the
        # view always carries its orphans/errors for the client to render.
        view = self.store.list_relationships(RelationshipQuery(floor="Floor_02"))
        self.assertEqual(view.edge_count, 44)
        self.assertEqual(view.orphan_count, 30)

    def test_zones_empty(self):
        self.assertEqual(self.store.list_zones(ZoneQuery()), [])


class FakeStoreSessionTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeReviewStore()
        self.equipment = self.store.list_equipment(EquipmentQuery())

    def _key(self, index):
        return self.equipment[index].canonical_name

    def test_open_session_has_pending_work(self):
        state = self.store.open_session(uuid4(), "Floor_02", "tester")
        self.assertEqual(state.status, SessionStatus.OPEN)
        self.assertGreater(state.n_pending, 0)
        self.assertEqual(state.n_approved, 0)
        self.assertEqual(state.n_rejected, 0)

    def test_action_counts_and_commit(self):
        state = self.store.open_session(uuid4(), "Floor_02", "tester")
        sid = state.session_id
        self.store.record_action(
            sid,
            ActionRequest(
                item_type=ItemType.EQUIPMENT, item_key=self._key(0), action=ActionType.APPROVE
            ),
        )
        self.store.record_action(
            sid,
            ActionRequest(
                item_type=ItemType.EQUIPMENT,
                item_key=self._key(1),
                action=ActionType.EDIT,
                payload={"equipment_type": "AHU"},
                reason="corrected type",
            ),
        )
        self.store.record_action(
            sid,
            ActionRequest(
                item_type=ItemType.EQUIPMENT,
                item_key=self._key(2),
                action=ActionType.REJECT,
                reason="misread",
            ),
        )
        mid = self.store.get_session(sid)
        # approve + edit both count as approved-into-production
        self.assertEqual(mid.n_approved, 2)
        self.assertEqual(mid.n_rejected, 1)

        result = self.store.commit_session(sid)
        self.assertTrue(result.committed)
        # approve + edit -> production; edit + reject -> correction_log
        self.assertEqual(result.n_committed, 2)
        self.assertEqual(result.n_corrections, 2)
        self.assertIsNotNone(result.committed_at)
        self.assertEqual(self.store.get_session(sid).status, SessionStatus.COMMITTED)

    def test_pending_decrements_with_actions(self):
        state = self.store.open_session(uuid4(), "Floor_02", "tester")
        sid = state.session_id
        # Action an item that is in the pending set.
        pending_item = next(it for it in self.equipment if it.review_required
                            and it.status != NormalizationStatus.FLOOR_AMBIGUOUS)
        before = self.store.get_session(sid).n_pending
        self.store.record_action(
            sid,
            ActionRequest(
                item_type=ItemType.EQUIPMENT,
                item_key=pending_item.canonical_name,
                action=ActionType.APPROVE,
            ),
        )
        after = self.store.get_session(sid).n_pending
        self.assertEqual(after, before - 1)

    def test_reaction_same_item_updates_in_place(self):
        state = self.store.open_session(uuid4(), "Floor_02", "tester")
        sid = state.session_id
        self.store.record_action(
            sid,
            ActionRequest(
                item_type=ItemType.EQUIPMENT, item_key=self._key(0), action=ActionType.APPROVE
            ),
        )
        self.store.record_action(
            sid,
            ActionRequest(
                item_type=ItemType.EQUIPMENT,
                item_key=self._key(0),
                action=ActionType.REJECT,
                reason="changed my mind",
            ),
        )
        state2 = self.store.get_session(sid)
        # One decision per item: net is a single rejection, not approve+reject.
        self.assertEqual(state2.n_approved, 0)
        self.assertEqual(state2.n_rejected, 1)

    def test_commit_twice_raises(self):
        state = self.store.open_session(uuid4(), "Floor_02", "tester")
        self.store.commit_session(state.session_id)
        with self.assertRaises(ValueError):
            self.store.commit_session(state.session_id)

    def test_action_on_committed_session_raises(self):
        state = self.store.open_session(uuid4(), "Floor_02", "tester")
        self.store.commit_session(state.session_id)
        with self.assertRaises(ValueError):
            self.store.record_action(
                state.session_id,
                ActionRequest(
                    item_type=ItemType.EQUIPMENT,
                    item_key=self._key(0),
                    action=ActionType.APPROVE,
                ),
            )

    def test_unknown_session_raises(self):
        with self.assertRaises(KeyError):
            self.store.get_session(uuid4())


if __name__ == "__main__":
    unittest.main()
