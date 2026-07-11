"""Push reviewed/approved entries from the human review board into the database.

Lead final-checklist item 5b: validated equipment must flow back into the
pipeline rather than staying in the review layer. The review board records
decisions per session; this script is the operational wrapper around that
write path:

  check           connectivity + review-table existence (friendly diagnostics)
  create-tables   apply pipeline/review_schema.sql idempotently
  list            review sessions with status and progress counts
  commit ID       atomically apply one session: approvals/edits -> production
                  tables, rejections -> correction_log; --export-fewshot then
                  feeds new corrections to the few-shot pool
  export-fewshot  run the correction -> few-shot outbox on its own

Usage:
    py scripts/upload_reviewed.py check
    py scripts/upload_reviewed.py list
    py scripts/upload_reviewed.py commit <session-id> --export-fewshot
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import db  # noqa: E402
from pipeline.fewshot_export import DEFAULT_POOL_PATH, export_corrections_to_fewshot  # noqa: E402
from pipeline.review_store import PostgresReviewStore, create_tables  # noqa: E402

REVIEW_TABLES = ("review_session", "review_action", "correction_log")

# The Postgres store reads review items from the committed canonical snapshot;
# w06 is the current-naming dataset the review UI shows.
DEFAULT_SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots" / "w06"
if not DEFAULT_SNAPSHOT_DIR.exists():  # pragma: no cover - w06 is committed
    DEFAULT_SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots" / "w04"


def run_check(*, connector: Optional[Callable[..., Any]] = None) -> int:
    """Verify DB reachability and review-table existence; exit 0 when ready."""
    try:
        with db.transaction(readonly=True, connector=connector) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY(%s)",
                (list(REVIEW_TABLES) + ["equipment_details"],),
            )
            found = {row[0] for row in cursor.fetchall()}
    except db.DatabaseConfigurationError as exc:
        print(f"NOT READY - configuration: {exc}")
        print("hint: set DB_HOST/DB_NAME/DB_USER/DB_PASSWORD/DB_PORT in .env; "
              "install a driver with: py -m pip install --cert <ca-bundle> \"psycopg[binary]\"")
        return 1
    except Exception as exc:  # noqa: BLE001 - operational diagnostics
        print(f"NOT READY - connection failed: {type(exc).__name__}: {exc}")
        print("hint: check DB_HOST in .env and that the SSH tunnel to the "
              "database (if required) is running.")
        return 1

    print(f"connected. equipment_details present: {'equipment_details' in found}")
    missing = [table for table in REVIEW_TABLES if table not in found]
    for table in REVIEW_TABLES:
        print(f"  {table}: {'ok' if table in found else 'MISSING'}")
    if missing:
        print("run: py scripts/upload_reviewed.py create-tables "
              "(requires CREATE on schema public — see docs/w5_database_admin_request.md)")
        return 1
    print("READY - review write path available.")
    return 0


def run_create_tables(*, connector: Optional[Callable[..., Any]] = None) -> int:
    count = create_tables(connector=connector)
    print(f"Applied {count} statement(s) from pipeline/review_schema.sql.")
    return 0


def run_list(*, connector: Optional[Callable[..., Any]] = None) -> int:
    with db.transaction(readonly=True, connector=connector) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT session_id, floor, status, created_by, created_at, "
            "n_pending, n_approved, n_rejected "
            "FROM review_session ORDER BY created_at"
        )
        rows = cursor.fetchall()
    if not rows:
        print("no review sessions found.")
        return 0
    print(f"{'session_id':38} {'floor':10} {'status':10} {'reviewer':12} "
          f"{'pending':>7} {'approved':>8} {'rejected':>8}")
    for row in rows:
        session_id, floor, status, created_by, _created, pending, approved, rejected = row
        print(f"{str(session_id):38} {floor:10} {status:10} {str(created_by or '-'):12} "
              f"{pending:>7} {approved:>8} {rejected:>8}")
    return 0


def run_commit(
    session_id: str,
    *,
    snapshot_dir: Path,
    export_fewshot: bool = False,
    pool_path: Optional[Path] = None,
    store: Optional[Any] = None,
    export_fn: Optional[Callable[..., int]] = None,
    connector: Optional[Callable[..., Any]] = None,
) -> int:
    """Commit one session's decisions to production, then optionally run the outbox."""
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        print(f"invalid session id: {session_id}")
        return 2

    active_store = store or PostgresReviewStore(snapshot_dir, connector=connector)
    result = active_store.commit_session(session_uuid)
    print(
        f"session {result.session_id}: committed={result.committed} "
        f"applied_to_production={result.n_committed} corrections={result.n_corrections} "
        f"at {result.committed_at}"
    )

    if export_fewshot:
        exporter = export_fn or export_corrections_to_fewshot
        exported = exporter(pool_path=pool_path, connector=connector)
        print(f"few-shot outbox: {exported} new correction(s) appended to "
              f"{pool_path or DEFAULT_POOL_PATH}")
    return 0


def run_export(
    *,
    pool_path: Optional[Path] = None,
    export_fn: Optional[Callable[..., int]] = None,
    connector: Optional[Callable[..., Any]] = None,
) -> int:
    exporter = export_fn or export_corrections_to_fewshot
    exported = exporter(pool_path=pool_path, connector=connector)
    print(f"few-shot outbox: {exported} new correction(s) appended to "
          f"{pool_path or DEFAULT_POOL_PATH}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review-board upload: push reviewed entries into the database."
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="Verify DB connectivity and review tables.")
    sub.add_parser("create-tables", help="Apply the review-table DDL idempotently.")
    sub.add_parser("list", help="List review sessions and their progress.")

    commit = sub.add_parser("commit", help="Atomically apply one session to production.")
    commit.add_argument("session_id", help="review_session UUID (see 'list')")
    commit.add_argument(
        "--snapshot-dir",
        type=Path,
        default=DEFAULT_SNAPSHOT_DIR,
        help="Canonical snapshot dir backing the review items (default: w06).",
    )
    commit.add_argument(
        "--export-fewshot",
        action="store_true",
        help="After the commit, feed new correction_log rows to the few-shot pool.",
    )
    commit.add_argument("--pool-path", type=Path, default=None)

    export = sub.add_parser("export-fewshot", help="Run the correction outbox alone.")
    export.add_argument("--pool-path", type=Path, default=None)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return run_check()
    if args.command == "create-tables":
        return run_create_tables()
    if args.command == "list":
        return run_list()
    if args.command == "commit":
        return run_commit(
            args.session_id,
            snapshot_dir=args.snapshot_dir,
            export_fewshot=args.export_fewshot,
            pool_path=args.pool_path,
        )
    if args.command == "export-fewshot":
        return run_export(pool_path=args.pool_path)
    build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
