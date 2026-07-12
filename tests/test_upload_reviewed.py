import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "upload_reviewed.py"

spec = importlib.util.spec_from_file_location("upload_reviewed", SCRIPT_PATH)
upload_reviewed = importlib.util.module_from_spec(spec)
sys.modules["upload_reviewed"] = upload_reviewed
spec.loader.exec_module(upload_reviewed)

# db.transaction resolves connection kwargs from the environment BEFORE calling
# an injected connector, so these tests must not depend on a local .env being
# present (there is none on CI). Same hermetic pattern as
# tests/test_review_store_sessions.py.
DB_ENV = {
    "DB_HOST": "test-host",
    "DB_NAME": "test-db",
    "DB_USER": "test-user",
    "DB_PASSWORD": "test-password",
    "DB_PORT": "5433",
}


class HermeticDbEnvTestCase(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, DB_ENV, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    """Minimal connection satisfying db.transaction + _apply_readonly."""

    def __init__(self, rows):
        self._rows = rows
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def set_session(self, readonly=False):
        pass

    def cursor(self):
        return FakeCursor(self._rows)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def connector_returning(rows):
    def connector(**kwargs):
        return FakeConnection(rows)

    return connector


class FakeCommitResult:
    def __init__(self, session_id):
        self.session_id = session_id
        self.committed = True
        self.n_committed = 3
        self.n_corrections = 1
        self.committed_at = datetime.now(timezone.utc)


class FakeStore:
    def __init__(self):
        self.committed_ids = []

    def commit_session(self, session_id):
        self.committed_ids.append(session_id)
        return FakeCommitResult(session_id)


class TestCheck(HermeticDbEnvTestCase):
    def test_ready_when_all_tables_exist(self):
        rows = [("review_session",), ("review_action",), ("correction_log",), ("equipment_details",)]
        out = io.StringIO()
        with redirect_stdout(out):
            exit_code = upload_reviewed.run_check(connector=connector_returning(rows))
        self.assertEqual(exit_code, 0)
        self.assertIn("READY", out.getvalue())

    def test_missing_review_tables_reports_and_exits_1(self):
        rows = [("equipment_details",)]
        out = io.StringIO()
        with redirect_stdout(out):
            exit_code = upload_reviewed.run_check(connector=connector_returning(rows))
        self.assertEqual(exit_code, 1)
        self.assertIn("review_session: MISSING", out.getvalue())
        self.assertIn("create-tables", out.getvalue())

    def test_connection_failure_gives_hint(self):
        def failing_connector(**kwargs):
            raise OSError("no route to host")

        out = io.StringIO()
        with redirect_stdout(out):
            exit_code = upload_reviewed.run_check(connector=failing_connector)
        self.assertEqual(exit_code, 1)
        self.assertIn("NOT READY", out.getvalue())
        self.assertIn("SSH tunnel", out.getvalue())


class TestList(HermeticDbEnvTestCase):
    def test_lists_sessions(self):
        session_id = uuid4()
        rows = [(session_id, "Floor_02", "open", "seb", datetime.now(timezone.utc), 5, 2, 1)]
        out = io.StringIO()
        with redirect_stdout(out):
            exit_code = upload_reviewed.run_list(connector=connector_returning(rows))
        self.assertEqual(exit_code, 0)
        self.assertIn(str(session_id), out.getvalue())
        self.assertIn("open", out.getvalue())

    def test_empty_session_table(self):
        out = io.StringIO()
        with redirect_stdout(out):
            exit_code = upload_reviewed.run_list(connector=connector_returning([]))
        self.assertEqual(exit_code, 0)
        self.assertIn("no review sessions", out.getvalue())


class TestCommit(unittest.TestCase):
    def test_commit_reports_result_without_export(self):
        store = FakeStore()
        session_id = str(uuid4())
        exports = []

        out = io.StringIO()
        with redirect_stdout(out):
            exit_code = upload_reviewed.run_commit(
                session_id,
                snapshot_dir=PROJECT_ROOT / "data" / "snapshots" / "w06",
                store=store,
                export_fn=lambda **kwargs: exports.append(kwargs) or 0,
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(store.committed_ids), 1)
        self.assertEqual(exports, [])  # no --export-fewshot
        self.assertIn("applied_to_production=3", out.getvalue())
        self.assertIn("corrections=1", out.getvalue())

    def test_commit_with_export_runs_outbox(self):
        store = FakeStore()
        exports = []

        def fake_export(**kwargs):
            exports.append(kwargs)
            return 2

        out = io.StringIO()
        with redirect_stdout(out):
            exit_code = upload_reviewed.run_commit(
                str(uuid4()),
                snapshot_dir=PROJECT_ROOT / "data" / "snapshots" / "w06",
                export_fewshot=True,
                store=store,
                export_fn=fake_export,
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(exports), 1)
        self.assertIn("2 new correction(s)", out.getvalue())

    def test_invalid_session_id_exits_2(self):
        out = io.StringIO()
        with redirect_stdout(out):
            exit_code = upload_reviewed.run_commit(
                "not-a-uuid",
                snapshot_dir=PROJECT_ROOT / "data" / "snapshots" / "w06",
                store=FakeStore(),
            )
        self.assertEqual(exit_code, 2)


class TestExport(unittest.TestCase):
    def test_export_alone(self):
        out = io.StringIO()
        with redirect_stdout(out):
            exit_code = upload_reviewed.run_export(export_fn=lambda **kwargs: 4)
        self.assertEqual(exit_code, 0)
        self.assertIn("4 new correction(s)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
