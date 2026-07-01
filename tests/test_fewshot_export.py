import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

from fewshot_export import export_corrections_to_fewshot  # noqa: E402

DB_ENV = {"DB_HOST": "h", "DB_NAME": "n", "DB_USER": "u", "DB_PASSWORD": "p", "DB_PORT": "5432"}


class FakeCursor:
    def __init__(self, select_rows):
        self.select_rows = select_rows
        self.executed = []
        self._last = None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params))
        if "FROM correction_log" in normalized and normalized.startswith("SELECT"):
            self._last = self.select_rows
        else:
            self._last = None

    def fetchall(self):
        return self._last or []


class FakeConnection:
    def __init__(self, select_rows):
        self._cursor = FakeCursor(select_rows)
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


def _connector(conn):
    return lambda **kwargs: conn


def _correction_row(correction_id, *, original, corrected, reason):
    return (
        correction_id,
        uuid4(),
        "equipment",
        "AHU_2-B",
        original,
        corrected,
        reason,
        "engineer@example.com",
        datetime.now(timezone.utc),
    )


class FewshotExportTests(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, DB_ENV, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.pool = Path(self.tmpdir) / "pool.jsonl"

    def _update_calls(self, conn):
        return [e for e in conn._cursor.executed if "UPDATE correction_log" in e[0]]

    def test_exports_unfed_rows_and_marks_them_fed(self):
        cid = uuid4()
        rows = [
            _correction_row(
                cid,
                original={"name": "AHU-02B"},
                corrected={"name": "AHU_2-2"},
                reason="drawing label is authoritative",
            )
        ]
        conn = FakeConnection(rows)
        count = export_corrections_to_fewshot(pool_path=self.pool, connector=_connector(conn))

        self.assertEqual(count, 1)
        lines = self.pool.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["correction_id"], str(cid))
        self.assertEqual(record["corrected"], {"name": "AHU_2-2"})
        self.assertEqual(record["original"], {"name": "AHU-02B"})

        updates = self._update_calls(conn)
        self.assertEqual(len(updates), 1)
        self.assertIn(cid, updates[0][1][0])  # selected_ids carries the row
        self.assertTrue(conn.committed)

    def test_rerun_is_idempotent_and_does_not_duplicate(self):
        cid = uuid4()
        row = _correction_row(cid, original={"a": 1}, corrected=None, reason="rejected")
        # First export writes the pool line.
        export_corrections_to_fewshot(pool_path=self.pool, connector=_connector(FakeConnection([row])))
        # Simulate a crash before the DB mark persisted: the same row comes back unfed.
        conn2 = FakeConnection([row])
        count2 = export_corrections_to_fewshot(pool_path=self.pool, connector=_connector(conn2))

        self.assertEqual(count2, 0)  # already in the pool -> no second append
        self.assertEqual(len(self.pool.read_text(encoding="utf-8").strip().splitlines()), 1)
        # ...but it is still marked fed on the retry.
        self.assertEqual(len(self._update_calls(conn2)), 1)

    def test_no_unfed_rows_is_a_noop(self):
        conn = FakeConnection([])
        count = export_corrections_to_fewshot(pool_path=self.pool, connector=_connector(conn))

        self.assertEqual(count, 0)
        self.assertFalse(self.pool.exists())
        self.assertEqual(self._update_calls(conn), [])

    def test_export_runs_read_write(self):
        conn = FakeConnection(
            [_correction_row(uuid4(), original={"a": 1}, corrected={"a": 2}, reason="r")]
        )
        export_corrections_to_fewshot(pool_path=self.pool, connector=_connector(conn))
        self.assertFalse(conn.readonly)  # the mark-fed update needs read-write


if __name__ == "__main__":
    unittest.main()
