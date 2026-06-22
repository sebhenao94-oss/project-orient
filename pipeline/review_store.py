"""W5 review-agent store and schema management (Track A).

For now this module owns the review-side schema (``review_session``,
``review_action``, ``correction_log``) and a ``--create-tables`` entry point
that applies it idempotently:

    py -m pipeline.review_store --create-tables

The ``PostgresReviewStore`` implementation of the ``ReviewStore`` interface
lands in A3, once the Monday contracts PR is frozen.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable, List, Optional

if __package__:
    from . import db
else:
    import db

SCHEMA_FILE = Path(__file__).resolve().parent / "review_schema.sql"


def load_schema_sql() -> str:
    """Return the review-table DDL script."""
    return SCHEMA_FILE.read_text(encoding="utf-8")


def iter_statements(sql: str) -> List[str]:
    """Split a DDL script into individual statements.

    The schema contains no function bodies or string literals with semicolons,
    so a simple semicolon split is safe and keeps the applier driver-agnostic
    (psycopg vs psycopg2).
    """
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def create_tables(*, connector: Optional[Callable[..., Any]] = None) -> int:
    """Create the review tables idempotently and return the statement count.

    All statements run in a single read-write transaction (commit on success,
    rollback on error). Re-running is a no-op thanks to ``CREATE TABLE IF NOT
    EXISTS``. ``connector`` injects a connection for tests.
    """
    statements = iter_statements(load_schema_sql())
    with db.transaction(connector=connector) as connection:
        cursor = connection.cursor()
        for statement in statements:
            cursor.execute(statement)
    return len(statements)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.review_store",
        description="Project ORIENT W5 review-agent store / schema management.",
    )
    parser.add_argument(
        "--create-tables",
        action="store_true",
        help=(
            "Create the review tables (review_session, review_action, "
            "correction_log) idempotently, then exit."
        ),
    )
    return parser


def _main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.create_tables:
        count = create_tables()
        print(f"Applied {count} statement(s) from {SCHEMA_FILE.name}.")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
