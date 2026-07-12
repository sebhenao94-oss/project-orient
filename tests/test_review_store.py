import os
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import review_store  # noqa: E402
from review_store import create_tables, iter_statements, load_schema_sql  # noqa: E402

DB_ENV = {"DB_HOST": "h", "DB_NAME": "n", "DB_USER": "u"}


class FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self._cursor = FakeCursor()
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.readonly = None

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


def _connector_returning(conn):
    def _factory(**kwargs):
        return conn

    return _factory


class SchemaContentTests(unittest.TestCase):
    def test_three_tables_and_idempotent_source_item_migration(self):
        statements = iter_statements(load_schema_sql())
        self.assertEqual(len(statements), 4)
        joined = "\n".join(statements).lower()
        for table in ("review_session", "review_action", "correction_log"):
            self.assertIn(f"create table if not exists {table}", joined)
        self.assertIn(
            "alter table review_action add column if not exists source_item jsonb",
            joined,
        )

    def test_foreign_keys_and_unique_present(self):
        sql = load_schema_sql().lower()
        self.assertEqual(sql.count("references review_session"), 2)
        self.assertIn("unique (session_id, item_type, item_key)", sql)

    def test_action_reason_is_persisted_until_commit(self):
        sql = load_schema_sql().lower()
        review_action = sql.split("create table if not exists review_action", 1)[1]
        review_action = review_action.split("create table if not exists correction_log", 1)[0]
        self.assertIn("reason      text", review_action)

    def test_relationship_source_item_is_persisted_separately_from_payload(self):
        sql = load_schema_sql().lower()
        self.assertIn("payload     jsonb", sql)
        self.assertIn("source_item jsonb", sql)


class CreateTablesTests(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, DB_ENV, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_runs_all_statements_and_commits_read_write(self):
        conn = FakeConnection()
        count = create_tables(connector=_connector_returning(conn))
        self.assertEqual(count, 4)
        self.assertEqual(len(conn._cursor.executed), 4)
        self.assertTrue(
            all(
                "CREATE TABLE IF NOT EXISTS" in s or "ALTER TABLE" in s
                for s in conn._cursor.executed
            )
        )
        self.assertTrue(conn.committed)
        self.assertFalse(conn.rolled_back)
        self.assertTrue(conn.closed)
        self.assertFalse(conn.readonly)  # DDL must run read-write

    def test_idempotent_second_run_does_not_raise(self):
        count_first = create_tables(connector=_connector_returning(FakeConnection()))
        count_second = create_tables(connector=_connector_returning(FakeConnection()))
        self.assertEqual(count_first, count_second)


if __name__ == "__main__":
    unittest.main()
