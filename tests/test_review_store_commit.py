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
    EquipmentQuery,
    RelationshipQuery,
    RelationshipRefType,
    RelationshipReviewItem,
    RelationshipView,
)
from review_store import (  # noqa: E402
    PostgresReviewStore,
    ProductionIdentityConflictError,
    ReviewSessionStateError,
    _production_identity,
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
        self._result = None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if not self.steps:
            raise AssertionError(f"unexpected SQL: {normalized}")
        expected, result = self.steps.pop(0)
        if expected not in normalized:
            raise AssertionError(f"expected {expected!r} in SQL: {normalized}")
        self.executed.append((normalized, params))
        if isinstance(result, BaseException):
            raise result
        self._result = result

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._result


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


class CommitSessionTests(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, DB_ENV, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.session_id = uuid4()
        self.created_at = datetime.now(timezone.utc)
        self.committed_at = datetime.now(timezone.utc)
        snapshot_store = PostgresReviewStore()
        self.property_id = UUID(
            next(
                item.property_id
                for item in snapshot_store.list_equipment(EquipmentQuery())
                if item.property_id
            )
        )
        self.items = snapshot_store._reviewable_equipment(
            self.property_id, "Floor_02"
        )

    def session_row(
        self,
        *,
        status="open",
        n_pending=0,
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
            self.committed_at if status == "committed" else None,
            n_pending,
            n_approved,
            n_rejected,
        )

    def action_row(self, item, action, *, payload=None, reason=None):
        return (
            uuid4(),
            "equipment",
            item.canonical_name,
            action,
            payload,
            None,
            "engineer@example.com",
            reason,
        )

    def test_commit_applies_approval_and_logs_rejection_atomically(self):
        approved, rejected = self.items[:2]
        actions = [
            self.action_row(approved, "approve"),
            self.action_row(rejected, "reject", reason="drawing disproves unit"),
        ]
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", self.session_row(n_approved=1, n_rejected=1)),
                ("FROM review_action", actions),
                ("FROM public.equipment_details", []),
                ("INSERT INTO public.equipment_details", (501,)),
                ("INSERT INTO correction_log", None),
                ("UPDATE review_action", None),
                (
                    "SET status = 'committed'",
                    self.session_row(status="committed", n_approved=1, n_rejected=1),
                ),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        result = store.commit_session(self.session_id)

        self.assertTrue(result.committed)
        self.assertEqual(result.n_committed, 1)
        self.assertEqual(result.n_corrections, 1)
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        insert_sql = connection._cursor.executed[3][0]
        self.assertNotIn("equipment_id,", insert_sql)
        self.assertNotIn("systemRef_type", insert_sql)  # type lives in `name`, not here
        correction_params = connection._cursor.executed[4][1]
        self.assertIsNone(correction_params[5])

    def test_edit_updates_original_row_and_logs_corrected_value(self):
        item = self.items[0]
        corrected_name = item.canonical_name + "-CORRECTED"
        action = self.action_row(
            item,
            "edit",
            payload={"canonical_name": corrected_name},
            reason="engineer corrected the identifier",
        )
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", self.session_row(n_approved=1)),
                ("FROM review_action", [action]),
                ("FROM public.equipment_details", [(601, item.canonical_name)]),
                ("UPDATE public.equipment_details", (601,)),
                ("INSERT INTO correction_log", None),
                ("UPDATE review_action", None),
                (
                    "SET status = 'committed'",
                    self.session_row(status="committed", n_approved=1),
                ),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        result = store.commit_session(self.session_id)

        self.assertEqual(result.n_committed, 1)
        self.assertEqual(result.n_corrections, 1)
        update_params = connection._cursor.executed[3][1]
        self.assertEqual(update_params[0], corrected_name)
        correction_params = connection._cursor.executed[4][1]
        self.assertIn(corrected_name, correction_params[5])

    def test_relationship_updates_child_reference_column(self):
        child, parent = self.items[:2]
        edge = RelationshipReviewItem(
            child=child.canonical_name,
            parent=parent.canonical_name,
            ref_type=RelationshipRefType.AIR_REF,
            confidence=0.9,
        )
        item_key = f"{edge.child}|airRef|{edge.parent}"
        action = (
            uuid4(),
            "relationship",
            item_key,
            "approve",
            None,
            0.9,
            "engineer@example.com",
            None,
        )
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", self.session_row(n_approved=1)),
                ("FROM review_action", [action]),
                (
                    "FROM public.equipment_details",
                    [(701, child.canonical_name), (702, parent.canonical_name)],
                ),
                ('SET "airRef" = %s', None),
                ("UPDATE review_action", None),
                (
                    "SET status = 'committed'",
                    self.session_row(status="committed", n_approved=1),
                ),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))
        store.list_relationships = lambda query: RelationshipView(edges=[edge])

        result = store.commit_session(self.session_id)

        self.assertEqual(result.n_committed, 1)
        relationship_params = connection._cursor.executed[3][1]
        self.assertEqual(relationship_params, (702, 701))

    def test_mid_commit_failure_rolls_back_before_actions_are_applied(self):
        first, second = self.items[:2]
        actions = [
            self.action_row(first, "approve"),
            self.action_row(second, "approve"),
        ]
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", self.session_row(n_approved=2)),
                ("FROM review_action", actions),
                ("FROM public.equipment_details", []),
                ("INSERT INTO public.equipment_details", (801,)),
                ("INSERT INTO public.equipment_details", RuntimeError("forced failure")),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        with self.assertRaisesRegex(RuntimeError, "forced failure"):
            store.commit_session(self.session_id)

        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)
        self.assertFalse(
            any("UPDATE review_action" in sql for sql, _ in connection._cursor.executed)
        )

    def test_pending_items_do_not_block_partial_commit(self):
        # Flush-and-continue: commit applies the recorded actions even while
        # other items in the session remain pending (matches FakeReviewStore
        # and the W6 review UI, which commits in batches).
        approved, rejected = self.items[:2]
        actions = [
            self.action_row(approved, "approve"),
            self.action_row(rejected, "reject", reason="drawing disproves unit"),
        ]
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", self.session_row(n_pending=3, n_approved=1, n_rejected=1)),
                ("FROM review_action", actions),
                ("FROM public.equipment_details", []),
                ("INSERT INTO public.equipment_details", (501,)),
                ("INSERT INTO correction_log", None),
                ("UPDATE review_action", None),
                (
                    "SET status = 'committed'",
                    self.session_row(status="committed", n_pending=3, n_approved=1, n_rejected=1),
                ),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        result = store.commit_session(self.session_id)

        self.assertTrue(result.committed)
        self.assertEqual(result.n_committed, 1)
        self.assertEqual(result.n_corrections, 1)
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)

    def test_recommit_is_idempotent(self):
        connection = ScriptedConnection(
            [
                ("FOR UPDATE", self.session_row(status="committed", n_approved=2)),
                ("count(*) FILTER", (2, 1)),
            ]
        )
        store = PostgresReviewStore(connector=connector_for(connection))

        result = store.commit_session(self.session_id)

        self.assertTrue(result.committed)
        self.assertEqual(result.n_committed, 2)
        self.assertEqual(result.n_corrections, 1)
        self.assertEqual(len(connection._cursor.executed), 2)

    def test_alias_equivalent_rows_fail_safe_when_both_exist(self):
        self.assertEqual(
            _production_identity("VAVRH_1-01"),
            _production_identity("VAV-RH-HW_1-01"),
        )
        existing = [
            {"equipment_id": 1, "name": "VAVRH_1-01"},
            {"equipment_id": 2, "name": "VAV-RH-HW_1-01"},
        ]
        with self.assertRaises(ProductionIdentityConflictError):
            PostgresReviewStore._resolve_production_equipment(
                existing, "VAV-RH-HW_1-01"
            )


if __name__ == "__main__":
    unittest.main()
