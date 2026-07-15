"""Two-connection review-ledger mode (REVIEW_LEDGER=local).

These cover the split where the review ledger (review_session, review_action,
correction_log) lives in a separate database (LEDGER_DB_*) from production
equipment_details (DB_*), so no ledger tables are needed in the production
schema. The default ``bas_data`` mode keeps everything on one connection and is
covered by tests/test_review_store_commit.py.
"""

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

import review_store  # noqa: E402
from review_api.contracts import EquipmentQuery  # noqa: E402
from review_store import PostgresReviewStore  # noqa: E402

PROD_ENV = {
    "DB_HOST": "prod-host",
    "DB_NAME": "prod-db",
    "DB_USER": "prod-user",
    "DB_PASSWORD": "p",
    "DB_PORT": "5432",
}
LEDGER_ENV = {
    "LEDGER_DB_HOST": "ledger-host",
    "LEDGER_DB_NAME": "ledger-db",
    "LEDGER_DB_USER": "ledger-user",
    "LEDGER_DB_PASSWORD": "p",
    "LEDGER_DB_PORT": "5433",
}


class ScriptedCursor:
    def __init__(self, steps):
        self.steps = list(steps)
        self.executed = []
        self._result = None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        # The per-action idempotency guard is best-effort here; when the next
        # scripted step is something else, let its JOIN probe fall through as
        # "not yet applied" without consuming a step.
        if self.steps and self.steps[0][0] not in normalized:
            if "FROM review_action a JOIN review_session s" in normalized:
                self._result = None
                return
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


class RecordingConnection:
    """Scripted connection that records commit order via a shared list."""

    def __init__(self, name, steps, commit_order):
        self.name = name
        self._cursor = ScriptedCursor(steps)
        self._commit_order = commit_order
        self.kwargs = None
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def set_session(self, readonly=None):
        self.readonly = readonly

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True
        self._commit_order.append(self.name)

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def connector_for(connection):
    def factory(**kwargs):
        connection.kwargs = kwargs
        return connection

    return factory


def executed_sql(connection):
    return [sql for sql, _ in connection._cursor.executed]


class LocalLedgerCommitTests(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(
            os.environ, {**PROD_ENV, **LEDGER_ENV}, clear=False
        )
        self._env.start()
        self.addCleanup(self._env.stop)
        self.session_id = uuid4()
        self.created_at = datetime.now(timezone.utc)
        reader = PostgresReviewStore()
        self.property_id = UUID(
            next(
                item.property_id
                for item in reader.list_equipment(EquipmentQuery())
                if item.property_id
            )
        )
        self.items = reader._reviewable_equipment(self.property_id, "Floor_02")

    def session_row(self, *, status="open", n_approved=0, n_rejected=0):
        return (
            self.session_id,
            self.property_id,
            "Floor_02",
            status,
            "engineer@example.com",
            self.created_at,
            self.created_at if status == "committed" else None,
            0,
            n_approved,
            n_rejected,
        )

    def action_row(self, item, action, *, reason=None):
        return (
            uuid4(),
            "equipment",
            item.canonical_name,
            action,
            None,
            None,
            None,
            "engineer@example.com",
            reason,
        )

    def test_commit_splits_connections_and_commits_production_first(self):
        approved, rejected = self.items[:2]
        actions = [
            self.action_row(approved, "approve"),
            self.action_row(rejected, "reject", reason="drawing disproves unit"),
        ]
        commit_order = []
        ledger = RecordingConnection(
            "ledger",
            [
                ("FOR UPDATE", self.session_row(n_approved=1, n_rejected=1)),
                ("FROM review_action", actions),
                ("INSERT INTO correction_log", None),
                ("UPDATE review_action", None),
                (
                    "SET status = 'committed'",
                    self.session_row(
                        status="committed", n_approved=1, n_rejected=1
                    ),
                ),
            ],
            commit_order,
        )
        production = RecordingConnection(
            "production",
            [
                ("FROM public.equipment_details", []),
                ("INSERT INTO public.equipment_details", (501,)),
            ],
            commit_order,
        )
        store = PostgresReviewStore(
            connector=connector_for(production),
            ledger_connector=connector_for(ledger),
            ledger_mode="local",
        )

        result = store.commit_session(self.session_id)

        self.assertTrue(result.committed)
        self.assertEqual(result.n_committed, 1)
        self.assertEqual(result.n_corrections, 1)
        # Two distinct databases, each configured from its own env prefix.
        self.assertEqual(production.kwargs["host"], "prod-host")
        self.assertEqual(ledger.kwargs["host"], "ledger-host")
        # Production is committed before the ledger bookkeeping.
        self.assertEqual(commit_order, ["production", "ledger"])
        self.assertTrue(production.committed and ledger.committed)
        self.assertFalse(production.rolled_back or ledger.rolled_back)
        # SQL routed to the right connection: equipment_details on production,
        # the ledger tables on the ledger.
        prod_sql = " ".join(executed_sql(production))
        ledger_sql = " ".join(executed_sql(ledger))
        self.assertIn("public.equipment_details", prod_sql)
        self.assertNotIn("correction_log", prod_sql)
        self.assertNotIn("review_session", prod_sql)
        self.assertIn("correction_log", ledger_sql)
        self.assertIn("review_session", ledger_sql)
        self.assertNotIn("equipment_details", ledger_sql)

    def test_open_session_touches_only_the_ledger(self):
        commit_order = []
        ledger = RecordingConnection(
            "ledger",
            [
                ("FROM review_action a JOIN review_session s", []),
                ("INSERT INTO review_session", self.session_row()),
            ],
            commit_order,
        )
        production = RecordingConnection("production", [], commit_order)
        store = PostgresReviewStore(
            connector=connector_for(production),
            ledger_connector=connector_for(ledger),
            ledger_mode="local",
        )

        state = store.open_session(self.property_id, "Floor_02", "engineer@example.com")

        self.assertEqual(state.session_id, self.session_id)
        self.assertEqual(ledger.kwargs["host"], "ledger-host")
        self.assertTrue(ledger.committed)
        # The production database is never opened for a ledger-only operation.
        self.assertIsNone(production.kwargs)


class LedgerTargetingTests(unittest.TestCase):
    def test_local_mode_targets_ledger_prefix(self):
        with mock.patch.dict(
            os.environ, {**PROD_ENV, **LEDGER_ENV, "REVIEW_LEDGER": "local"}, clear=False
        ):
            self.assertEqual(review_store.ledger_env_prefix(), "LEDGER_DB")

            recorded = {}

            class Cur:
                def execute(self, sql, params=None):
                    recorded.setdefault("statements", []).append(sql)

            class Conn:
                def __init__(self):
                    self.committed = False

                def set_session(self, readonly=None):
                    pass

                def cursor(self):
                    return Cur()

                def commit(self):
                    self.committed = True

                def rollback(self):
                    pass

                def close(self):
                    pass

            conn = Conn()

            def factory(**kwargs):
                recorded["kwargs"] = kwargs
                return conn

            count = review_store.create_tables(connector=factory)

            self.assertEqual(count, 4)  # 3 CREATE TABLE + 1 ALTER TABLE
            self.assertEqual(recorded["kwargs"]["host"], "ledger-host")
            self.assertTrue(conn.committed)

    def test_bas_data_mode_targets_production_prefix(self):
        with mock.patch.dict(os.environ, PROD_ENV, clear=True):
            self.assertEqual(review_store.ledger_env_prefix(), "DB")


if __name__ == "__main__":
    unittest.main()
