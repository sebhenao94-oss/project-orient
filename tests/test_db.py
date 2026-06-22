import os
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import db  # noqa: E402
from db import (  # noqa: E402
    DatabaseConfigurationError,
    connect_readonly,
    connect_readwrite,
    transaction,
)

# Importing `db` above with no guarantee of DB_* present already proves the
# module opens no connection at import time (it would have raised otherwise).

DUMMY_ENV = {
    "DB_HOST": "h",
    "DB_NAME": "n",
    "DB_USER": "u",
    "DB_PASSWORD": "p",
    "DB_PORT": "5432",
}


class FakeConnection:
    """psycopg2-style fake: records lifecycle calls and the session mode."""

    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.readonly = None
        self.kwargs = None

    def set_session(self, readonly=None):
        self.readonly = readonly

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class FakeConnectionPsycopg3:
    """psycopg (v3)-style fake: no set_session; mode is applied via execute()."""

    def __init__(self):
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, sql):
        self.executed.append(sql)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def _connector_returning(conn):
    def _factory(**kwargs):
        conn.kwargs = kwargs
        return conn

    return _factory


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, DUMMY_ENV, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_commits_and_closes_on_success(self):
        conn = FakeConnection()
        with transaction(connector=_connector_returning(conn)) as yielded:
            self.assertIs(yielded, conn)
        self.assertTrue(conn.committed)
        self.assertFalse(conn.rolled_back)
        self.assertTrue(conn.closed)
        self.assertFalse(conn.readonly)  # the commit path defaults to read-write

    def test_rolls_back_and_reraises_on_error(self):
        conn = FakeConnection()
        with self.assertRaises(ValueError):
            with transaction(connector=_connector_returning(conn)):
                raise ValueError("boom")
        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)
        self.assertTrue(conn.closed)

    def test_reused_connection_is_not_closed(self):
        conn = FakeConnection()
        with transaction(connection=conn):
            pass
        self.assertTrue(conn.committed)
        self.assertFalse(conn.closed)  # the caller owns a passed-in connection

    def test_connection_kwargs_passed_through(self):
        conn = FakeConnection()
        with transaction(connector=_connector_returning(conn)):
            pass
        self.assertEqual(conn.kwargs["host"], "h")
        self.assertEqual(conn.kwargs["dbname"], "n")
        self.assertEqual(conn.kwargs["user"], "u")


class SessionModeTests(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, DUMMY_ENV, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_connect_readonly_sets_readonly_true(self):
        conn = FakeConnection()
        result = connect_readonly(connector=_connector_returning(conn))
        self.assertIs(result, conn)
        self.assertTrue(conn.readonly)

    def test_connect_readwrite_sets_readonly_false(self):
        conn = FakeConnection()
        connect_readwrite(connector=_connector_returning(conn))
        self.assertFalse(conn.readonly)

    def test_psycopg3_style_uses_set_characteristics(self):
        conn = FakeConnectionPsycopg3()
        connect_readonly(connector=_connector_returning(conn))
        self.assertEqual(
            conn.executed, ["SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"]
        )


class ConfigurationTests(unittest.TestCase):
    def test_missing_env_raises_before_connecting(self):
        sentinel = FakeConnection()
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(DatabaseConfigurationError):
                connect_readonly(connector=_connector_returning(sentinel))
        # connector must not have been called when config is missing
        self.assertIsNone(sentinel.kwargs)


if __name__ == "__main__":
    unittest.main()
