"""Database connection helpers for Project ORIENT.

Read-only is the default access mode (mirroring the W3/W4 topics export in
``extraction.py``). The W5 review-agent commit step needs a *read-write* path,
so this module adds :func:`connect_readwrite` and a :func:`transaction` context
manager that commits on success and rolls back on any error.

Connection parameters come from the environment (``DB_HOST`` / ``DB_NAME`` /
``DB_USER`` / ``DB_PASSWORD`` / ``DB_PORT``), loaded from the repo ``.env``.
No credentials live in code, and importing this module opens no connection.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional

if __package__:
    from .config import PROJECT_ROOT
else:
    from config import PROJECT_ROOT

try:  # loading .env is side-effect-free and never opens a connection
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except Exception:  # pragma: no cover - dotenv optional / .env absent
    pass


DEFAULT_DB_PORT = 5432


class DatabaseConfigurationError(RuntimeError):
    """Raised when required database configuration is missing or invalid."""


def _connection_kwargs() -> Dict[str, Any]:
    host = os.getenv("DB_HOST")
    name = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    missing = [
        env_name
        for env_name, value in (("DB_HOST", host), ("DB_NAME", name), ("DB_USER", user))
        if not value
    ]
    if missing:
        raise DatabaseConfigurationError(
            "Missing required database environment variable(s): " + ", ".join(missing)
        )
    return {
        "host": host,
        "dbname": name,
        "user": user,
        "password": os.getenv("DB_PASSWORD"),
        "port": os.getenv("DB_PORT") or DEFAULT_DB_PORT,
    }


def _driver_connect(kwargs: Dict[str, Any]) -> Any:
    """Open a real connection, preferring psycopg2 then psycopg (as in extraction.py)."""
    try:
        import psycopg2  # type: ignore

        return psycopg2.connect(**kwargs)
    except ImportError:
        pass
    try:
        import psycopg  # type: ignore

        return psycopg.connect(**kwargs)
    except ImportError as exc:
        raise DatabaseConfigurationError(
            "No PostgreSQL driver is installed. Install psycopg or psycopg2."
        ) from exc


def _apply_readonly(connection: Any, readonly: bool) -> None:
    """Set the session read/write mode across both drivers (and test fakes)."""
    set_session = getattr(connection, "set_session", None)
    if callable(set_session):  # psycopg2 style
        set_session(readonly=readonly)
        return
    # psycopg (v3) style
    mode = "READ ONLY" if readonly else "READ WRITE"
    connection.execute(f"SET SESSION CHARACTERISTICS AS TRANSACTION {mode}")


def _open_connection(
    *, readonly: bool, connector: Optional[Callable[..., Any]] = None
) -> Any:
    kwargs = _connection_kwargs()
    connection = connector(**kwargs) if connector is not None else _driver_connect(kwargs)
    _apply_readonly(connection, readonly)
    return connection


def connect_readonly(*, connector: Optional[Callable[..., Any]] = None) -> Any:
    """Open a new read-only connection (the default access mode)."""
    return _open_connection(readonly=True, connector=connector)


def connect_readwrite(*, connector: Optional[Callable[..., Any]] = None) -> Any:
    """Open a new read-write connection (for the review-agent commit path)."""
    return _open_connection(readonly=False, connector=connector)


@contextmanager
def transaction(
    *,
    readonly: bool = False,
    connection: Optional[Any] = None,
    connector: Optional[Callable[..., Any]] = None,
) -> Iterator[Any]:
    """Run a block inside one transaction: commit on success, rollback on error.

    By default opens a fresh read-write connection (the W5 commit path) and closes
    it on exit. Pass an existing ``connection`` to reuse it (it is left open). Pass
    a ``connector`` factory to inject a connection in tests. For read-only work
    prefer :func:`connect_readonly`; ``readonly=True`` gives a read-only transaction.
    """
    owns_connection = connection is None
    if connection is None:
        connection = _open_connection(readonly=readonly, connector=connector)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()
