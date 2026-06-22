import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
for path in (PROJECT_ROOT, PIPELINE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from review_api import contracts  # noqa: E402
from review_api.contracts import (  # noqa: E402
    ActionRequest,
    ActionResult,
    ActionType,
    CommitResult,
    DiscrepancyCategory,
    DiscrepancyReviewItem,
    DiscrepancyStatus,
    DiscrepancyView,
    EquipmentQuery,
    EquipmentReviewItem,
    EquipmentSort,
    GraphFinding,
    ItemType,
    NormalizationStatus,
    RelationshipRefType,
    RelationshipReviewItem,
    RelationshipView,
    ReviewStore,
    SessionState,
    SessionStatus,
)


def _equipment_item() -> EquipmentReviewItem:
    return EquipmentReviewItem(
        floor="Floor_02",
        canonical_name="VAV-RH-HW_2-1",
        canonical_key="VAVRH_2_1",
        equipment_type="VAV-RH-HW",
        raw_equipment_type="VAVRH",
        discrepancy_category=DiscrepancyCategory.MATCHED,
        status=NormalizationStatus.SETTLED,
        in_topics=True,
        in_drawings=True,
        confidence=0.99,
        review_required=True,
        review_reason="reheat source assumed hot-water",
    )


def _discrepancy_item() -> DiscrepancyReviewItem:
    return DiscrepancyReviewItem(
        building="msa_orient_building_1",
        floor="Floor_02",
        equipment_type="AHU",
        equipment_id="AHU_2-B",
        in_points=True,
        in_drawings=False,
        status=DiscrepancyStatus.MISSING_FROM_DRAWINGS,
        evidence_point="AHU-02B",
        severity_hint=contracts.SeverityHint.HIGH,
    )


def _session_state() -> SessionState:
    return SessionState(
        session_id=uuid4(),
        property_id=uuid4(),
        floor="Floor_02",
        status=SessionStatus.OPEN,
        created_at=datetime.now(timezone.utc),
        n_pending=3,
    )


class RoundTripTests(unittest.TestCase):
    def _assert_round_trip(self, model):
        clone = type(model).model_validate(model.model_dump())
        self.assertEqual(clone, model)

    def test_equipment_item_round_trip(self):
        self._assert_round_trip(_equipment_item())

    def test_discrepancy_item_round_trip(self):
        self._assert_round_trip(_discrepancy_item())

    def test_session_state_round_trip(self):
        self._assert_round_trip(_session_state())

    def test_relationship_view_round_trip(self):
        view = RelationshipView(
            edges=[
                RelationshipReviewItem(
                    child="VAV-RH-HW_2-1",
                    parent="AHU_2-1",
                    ref_type=RelationshipRefType.AIR_REF,
                    confidence=0.9,
                )
            ],
            orphans=[GraphFinding(check_id="orphan_terminal", severity="orphan",
                                  message="x has no airRef parent", nodes=["FCU_2-1"])],
            passed=True,
        )
        self._assert_round_trip(view)
        self.assertEqual(view.edge_count, 1)
        self.assertEqual(view.orphan_count, 1)

    def test_commit_result_round_trip(self):
        self._assert_round_trip(
            CommitResult(session_id=uuid4(), committed=True, n_committed=11, n_corrections=2)
        )

    def test_action_result_round_trip(self):
        self._assert_round_trip(
            ActionResult(
                action_id=uuid4(),
                session_id=uuid4(),
                item_type=ItemType.EQUIPMENT,
                item_key="VAV-RH-HW_2-1",
                action=ActionType.APPROVE,
                applied=False,
                session_state=_session_state(),
            )
        )


class EnumAndDefaultTests(unittest.TestCase):
    def test_resolved_out_of_scope_status_present(self):
        self.assertEqual(DiscrepancyStatus.RESOLVED_OUT_OF_SCOPE.value, "resolved_out_of_scope")

    def test_equipment_query_defaults_to_confidence_ascending(self):
        self.assertEqual(EquipmentQuery().sort, EquipmentSort.CONFIDENCE_ASC)

    def test_discrepancy_view_grouping_holds_groups(self):
        view = DiscrepancyView(
            items=[_discrepancy_item()],
            group_by=contracts.DiscrepancyGroupBy.SEVERITY_HINT,
            groups={"high": [_discrepancy_item()]},
            counts={"missing_from_drawings": 1},
            rollups=["Floor 2: 4 AHUs missing from drawings"],
        )
        self.assertIn("high", view.groups)


class ProtocolConformanceTests(unittest.TestCase):
    def test_a_full_implementer_satisfies_the_protocol(self):
        class _FakeStore:
            def list_equipment(self, query):
                return []

            def list_relationships(self, query):
                return RelationshipView()

            def list_discrepancies(self, query):
                return DiscrepancyView()

            def list_zones(self, query):
                return []

            def get_session(self, session_id):
                return _session_state()

            def open_session(self, property_id, floor, reviewer=None):
                return _session_state()

            def record_action(self, session_id, request):
                raise NotImplementedError

            def commit_session(self, session_id):
                return CommitResult(session_id=session_id, committed=True)

        self.assertIsInstance(_FakeStore(), ReviewStore)

    def test_incomplete_implementer_is_rejected(self):
        class _Partial:
            def list_equipment(self, query):
                return []

        self.assertNotIsInstance(_Partial(), ReviewStore)


if __name__ == "__main__":
    unittest.main()
