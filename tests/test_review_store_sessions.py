import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from uuid import UUID, uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
for path in (PROJECT_ROOT, PIPELINE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from review_api.contracts import (  # noqa: E402
    ActionRequest,
    ActionType,
    EquipmentQuery,
    ItemType,
    RelationshipProposal,
    RelationshipRefType,
    SessionStatus,
)
from review_store import (  # noqa: E402
    PostgresReviewStore,
    ReviewItemNotFoundError,
    ReviewSessionStateError,
)

DB_ENV = {
    "DB_HOST": "h",
    "DB_NAME": "n",
    "DB_USER": "u",
    "DB_PASSWORD": "p",
    "DB_PORT": "5432",
}


class ScriptedCursor:
    def __init__(self, steps):
        self.steps = list(steps)
        self.executed = []
        self._row = None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if self.steps and self.steps[0][0] not in normalized:
            if "FROM review_action a JOIN review_session s" in normalized:
                self._row = [] if "SELECT a.item_type, a.item_key" in normalized else None
                return
        if not self.steps:
            raise AssertionError(f"unexpected SQL: {normalized}")
        expected, row = self.steps.pop(0)
        if expected not in normalized:
            raise AssertionError(f"expected {expected!r} in SQL: {normalized}")
        self.executed.append((normalized, params))
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._row or []


class ScriptedConnection:
    def __init__(self, steps):
        self._cursor = ScriptedCursor(steps)
        self.readonly = None
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def set_session(self, readonly=None):
        self.readonly = readonly

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def connector_for(connection):
    return lambda **kwargs: connection


class ReviewStoreSessionTests(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, DB_ENV, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.property_id = uuid4()
        self.session_id = uuid4()
        self.created_at = datetime.now(timezone.utc)

    def session_row(
        self,
        *,
        status="open",
        n_pending=42,
        n_approved=0,
        n_rejected=0,
    ):
        return (
            self.session_id,
            self.property_id,
            "Floor_02",
            status,
            "engineer@example.com",
            self.created_at,
            None,
            n_pending,
            n_approved,
            n_rejected,
        )

    def snapshot_property_id(self, store):
        return UUID(
            next(
                item.property_id
                for item in store.list_equipment(EquipmentQuery())
                if item.property_id
            )
        )

    def test_pending_count_uses_unique_equipment_and_excludes_resolved_floor_rows(self):
        store = PostgresReviewStore()
        target_property = self.snapshot_property_id(store)
        self.assertEqual(
            store._initial_pending_count(target_property, "Floor_02"),
            93,
        )
        reviewable = store._reviewable_equipment(target_property, "Floor_02")
        self.assertEqual(len(reviewable), 49)
        self.assertTrue(any(not item.review_required for item in reviewable))

    def test_open_session_persists_initial_pending_count(self):
        row = self.session_row()
        connection = ScriptedConnection([("INSERT INTO review_session", row)])
        store = PostgresReviewStore(connector=connector_for(connection))
        # Use the actual snapshot property so W6 equipment and relationship
        # review items are counted.
        property_id = self.snapshot_property_id(store)
        self.property_id = property_id
        row = list(row)
        row[1] = property_id
        row[7] = 93
        connection._cursor.steps[0] = ("INSERT INTO review_session", tuple(row))

        state = store.open_session(property_id, "Floor_02", "engineer@example.com")

        self.assertEqual(state.n_pending, 93)
        params = connection._cursor.executed[0][1]
        self.assertEqual(params[1:], (property_id, "Floor_02", "engineer@example.com", 93))
        self.assertTrue(connection.committed)
        self.assertFalse(connection.readonly)

    def test_open_session_excludes_previously_applied_items(self):
        store = PostgresReviewStore()
        property_id = self.snapshot_property_id(store)
        applied_key = store._reviewable_equipment(property_id, "Floor_02")[0].canonical_name
        row = list(self.session_row())
        row[1] = property_id
        row[7] = 92
        connection = ScriptedConnection(
            [
                ("SELECT a.item_type, a.item_key", [(ItemType.EQUIPMENT.value, applied_key)]),
                ("INSERT INTO review_session", tuple(row)),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        state = store.open_session(property_id, "Floor_02", "engineer@example.com")

        self.assertEqual(state.n_pending, 92)
        params = connection._cursor.executed[1][1]
        self.assertEqual(params[4], 92)

    def test_get_session_uses_read_only_transaction(self):
        connection = ScriptedConnection([("FROM review_session WHERE session_id", self.session_row())])
        store = PostgresReviewStore(connector=connector_for(connection))

        state = store.get_session(self.session_id)

        self.assertEqual(state.session_id, self.session_id)
        self.assertTrue(connection.readonly)
        self.assertTrue(connection.committed)

    def test_record_action_canonicalizes_key_and_recounts(self):
        store_for_item = PostgresReviewStore()
        property_id = self.snapshot_property_id(store_for_item)
        equipment = store_for_item._reviewable_equipment(
            property_id,
            "Floor_02",
        )[0]
        self.property_id = property_id
        locked = list(self.session_row())
        locked[1] = property_id
        updated = list(locked)
        updated[7:10] = [41, 1, 0]
        action_id = uuid4()
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", tuple(locked)),
                ("INSERT INTO review_action", (action_id, False)),
                ("count(*) FILTER", (1, 0)),
                ("UPDATE review_session", tuple(updated)),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))
        request = ActionRequest(
            item_type=ItemType.EQUIPMENT,
            item_key=equipment.canonical_name,
            action=ActionType.APPROVE,
        )

        result = store.record_action(self.session_id, request)

        self.assertEqual(result.item_key, equipment.canonical_name)
        self.assertEqual(result.action_id, action_id)
        self.assertEqual(result.session_state.n_pending, 41)
        self.assertEqual(result.session_state.n_approved, 1)
        action_params = connection._cursor.executed[1][1]
        self.assertEqual(action_params[3], equipment.canonical_name)
        self.assertIn("ON CONFLICT", connection._cursor.executed[1][0])
        self.assertTrue(connection.committed)

    def test_record_action_rejects_item_committed_in_prior_session(self):
        store_for_item = PostgresReviewStore()
        property_id = self.snapshot_property_id(store_for_item)
        equipment = store_for_item._reviewable_equipment(property_id, "Floor_02")[0]
        locked = list(self.session_row())
        locked[1] = property_id
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", tuple(locked)),
                ("SELECT 1", (1,)),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        with self.assertRaisesRegex(ReviewItemNotFoundError, "already committed"):
            store.record_action(
                self.session_id,
                ActionRequest(
                    item_type=ItemType.EQUIPMENT,
                    item_key=equipment.canonical_name,
                    action=ActionType.APPROVE,
                ),
            )

        self.assertTrue(connection.rolled_back)

    def test_replacing_action_recounts_without_consuming_another_pending_item(self):
        store_for_item = PostgresReviewStore()
        property_id = self.snapshot_property_id(store_for_item)
        equipment = store_for_item._reviewable_equipment(property_id, "Floor_02")[0]
        self.property_id = property_id
        locked = list(self.session_row(n_pending=41, n_approved=1))
        locked[1] = property_id
        updated = list(locked)
        updated[7:10] = [41, 0, 1]
        existing_action_id = uuid4()
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", tuple(locked)),
                ("ON CONFLICT", (existing_action_id, False)),
                ("count(*) FILTER", (0, 1)),
                ("UPDATE review_session", tuple(updated)),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))
        request = ActionRequest(
            item_type=ItemType.EQUIPMENT,
            item_key=equipment.canonical_name,
            action=ActionType.REJECT,
            reason="drawing evidence disproves this unit",
        )

        result = store.record_action(self.session_id, request)

        self.assertEqual(result.action_id, existing_action_id)
        self.assertEqual(result.session_state.n_pending, 41)
        self.assertEqual(result.session_state.n_approved, 0)
        self.assertEqual(result.session_state.n_rejected, 1)
        action_params = connection._cursor.executed[1][1]
        self.assertEqual(action_params[9], "drawing evidence disproves this unit")

    def test_clear_action_deletes_unapplied_row_and_recounts(self):
        item_key = "AHU_2-A"
        locked = self.session_row(n_pending=86, n_approved=1, n_rejected=1)
        updated = self.session_row(n_pending=87, n_approved=0, n_rejected=1)
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", locked),
                ("SELECT applied", (False, None)),
                ("DELETE FROM review_action", None),
                ("count(*) FILTER", (0, 1)),
                ("UPDATE review_session", updated),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        state = store.clear_action(
            self.session_id, ItemType.EQUIPMENT, item_key
        )

        self.assertEqual(state.n_pending, 87)
        self.assertEqual(state.n_approved, 0)
        self.assertEqual(state.n_rejected, 1)
        delete_sql, delete_params = connection._cursor.executed[2]
        self.assertIn("applied = false", delete_sql)
        self.assertEqual(
            delete_params, (self.session_id, ItemType.EQUIPMENT.value, item_key)
        )
        self.assertTrue(connection.committed)

    def test_clear_action_rejects_applied_row_without_deleting(self):
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", self.session_row(n_pending=87, n_approved=1)),
                ("SELECT applied", (True, None)),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        with self.assertRaisesRegex(ValueError, "already applied and frozen"):
            store.clear_action(
                self.session_id, ItemType.EQUIPMENT, "AHU_2-A"
            )

        self.assertFalse(
            any(
                "DELETE FROM review_action" in sql
                for sql, _params in connection._cursor.executed
            )
        )
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)

    def test_clear_all_deletes_only_unapplied_rows(self):
        locked = self.session_row(n_pending=85, n_approved=2, n_rejected=1)
        updated = self.session_row(n_pending=87, n_approved=1, n_rejected=0)
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", locked),
                ("SELECT count(*)", (0,)),
                ("DELETE FROM review_action", None),
                ("count(*) FILTER", (1, 0)),
                ("UPDATE review_session", updated),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        state = store.clear_all_actions(self.session_id)

        self.assertEqual(state.n_pending, 87)
        self.assertEqual(state.n_approved, 1)
        self.assertEqual(state.n_rejected, 0)
        delete_sql = connection._cursor.executed[2][0]
        self.assertIn("applied = false", delete_sql)
        self.assertTrue(connection.committed)

    def test_record_action_rejects_closed_session(self):
        connection = ScriptedConnection(
            [("FOR UPDATE", self.session_row(status=SessionStatus.COMMITTED.value))]
        )
        store = PostgresReviewStore(connector=connector_for(connection))
        request = ActionRequest(
            item_type=ItemType.EQUIPMENT,
            item_key="anything",
            action=ActionType.REJECT,
            reason="duplicate",
        )

        with self.assertRaises(ReviewSessionStateError):
            store.record_action(self.session_id, request)

        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)

    def test_discrepancy_is_context_not_a_second_action(self):
        connection = ScriptedConnection([("FOR UPDATE", self.session_row())])
        store = PostgresReviewStore(connector=connector_for(connection))
        request = ActionRequest(
            item_type=ItemType.DISCREPANCY,
            item_key="AHU_2-1",
            action=ActionType.REJECT,
            reason="not present",
        )

        with self.assertRaisesRegex(ReviewItemNotFoundError, "equipment evidence"):
            store.record_action(self.session_id, request)

        self.assertTrue(connection.rolled_back)

    def test_new_relationship_proposal_is_persisted_and_expands_denominator_once(self):
        store_for_item = PostgresReviewStore()
        property_id = self.snapshot_property_id(store_for_item)
        self.property_id = property_id
        locked = list(self.session_row(n_pending=93))
        locked[1] = property_id
        updated = list(locked)
        updated[7:10] = [93, 1, 0]
        proposal = RelationshipProposal(
            child="AHU_2-A",
            parent="AHU_2-B",
            ref_type=RelationshipRefType.SYSTEM_REF,
        )
        action_id = uuid4()
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", tuple(locked)),
                ("SELECT source_item", None),
                ("INSERT INTO review_action", (action_id, False)),
                ("count(*) FILTER", (1, 0)),
                ("UPDATE review_session", tuple(updated)),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        result = store.record_action(
            self.session_id,
            ActionRequest(
                item_type=ItemType.RELATIONSHIP,
                item_key=proposal.item_key,
                action=ActionType.APPROVE,
                source_item=proposal,
            ),
        )

        self.assertEqual(result.session_state.n_pending, 93)
        self.assertEqual(result.session_state.n_approved, 1)
        action_params = connection._cursor.executed[2][1]
        self.assertIsNone(action_params[5])  # approve payload remains null
        self.assertIn('"ref_type":"systemRef"', action_params[6])

    def test_clearing_new_relationship_proposal_removes_dynamic_item(self):
        proposal_json = '{"child":"AHU_2-A","parent":"AHU_2-B","ref_type":"systemRef"}'
        locked = self.session_row(n_pending=93, n_approved=1)
        updated = self.session_row(n_pending=93, n_approved=0)
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", locked),
                ("SELECT applied", (False, proposal_json)),
                ("DELETE FROM review_action", None),
                ("count(*) FILTER", (0, 0)),
                ("UPDATE review_session", updated),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        state = store.clear_action(
            self.session_id,
            ItemType.RELATIONSHIP,
            "AHU_2-A|systemRef|AHU_2-B",
        )

        self.assertEqual(state.n_pending, 93)
        self.assertEqual(state.n_approved, 0)

    def test_new_relationship_proposal_rejects_unknown_endpoint_before_insert(self):
        store_for_item = PostgresReviewStore()
        property_id = self.snapshot_property_id(store_for_item)
        locked = list(self.session_row(n_pending=93))
        locked[1] = property_id
        connection = ScriptedConnection([("FOR UPDATE", tuple(locked))])
        store = PostgresReviewStore(connector=connector_for(connection))
        proposal = RelationshipProposal(
            child="UNKNOWN_2-99",
            parent="AHU_2-A",
            ref_type=RelationshipRefType.AIR_REF,
        )

        with self.assertRaisesRegex(ReviewItemNotFoundError, "endpoint.*not reviewable"):
            store.record_action(
                self.session_id,
                ActionRequest(
                    item_type=ItemType.RELATIONSHIP,
                    item_key=proposal.item_key,
                    action=ActionType.APPROVE,
                    source_item=proposal,
                ),
            )

        self.assertTrue(connection.rolled_back)
        self.assertFalse(
            any("INSERT INTO review_action" in sql for sql, _ in connection._cursor.executed)
        )


if __name__ == "__main__":
    unittest.main()
