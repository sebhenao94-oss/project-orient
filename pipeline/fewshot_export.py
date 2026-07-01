"""W5 A5 - correction -> few-shot data path (outbox-style exporter).

``commit_session`` writes engineer corrections to ``correction_log`` (on edit and
reject). This exporter is a SEPARATE step, deliberately NOT part of the production
commit transaction: a database transaction and a filesystem append cannot be made
atomic together, so we use an outbox pattern instead.

Flow: read unfed ``correction_log`` rows (``fed_to_fewshot = false``), append the
new ones to a few-shot pool JSONL, then mark them ``fed_to_fewshot = true``. The
append is idempotent via ``correction_id`` dedupe against the existing pool, so a
crash/retry between the append and the DB mark never double-writes the pool.

A5 only wires the data path; the few-shot loop itself is exercised in W8. Run:

    py -m pipeline.fewshot_export
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

if __package__:
    from . import db
else:
    import db

DEFAULT_POOL_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "extractions"
    / "w05"
    / "correction_fewshot_pool.jsonl"
)

_CORRECTION_COLUMNS = (
    "correction_id, session_id, item_type, item_key, original, corrected, "
    "reason, reviewer, created_at"
)


def _existing_correction_ids(pool_path: Path) -> Set[str]:
    if not pool_path.exists():
        return set()
    ids: Set[str] = set()
    with open(pool_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(json.loads(line).get("correction_id"))
            except json.JSONDecodeError:
                continue
    return ids


def _jsonish(value: Any) -> Any:
    """jsonb columns may arrive as dicts (psycopg) or strings; normalise to objects."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _record_from_row(row: Any) -> Dict[str, Any]:
    (
        correction_id,
        session_id,
        item_type,
        item_key,
        original,
        corrected,
        reason,
        reviewer,
        created_at,
    ) = row
    return {
        "correction_id": str(correction_id),
        "session_id": str(session_id),
        "item_type": item_type,
        "item_key": item_key,
        "original": _jsonish(original),
        "corrected": _jsonish(corrected),
        "reason": reason,
        "reviewer": reviewer,
        "created_at": created_at.isoformat()
        if hasattr(created_at, "isoformat")
        else created_at,
    }


def _append_jsonl(pool_path: Path, records: List[Dict[str, Any]]) -> None:
    pool_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pool_path, "a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def export_corrections_to_fewshot(
    *,
    pool_path: Optional[Path] = None,
    connector: Optional[Callable[..., Any]] = None,
) -> int:
    """Export unfed ``correction_log`` rows to the few-shot pool JSONL.

    Returns the number of newly appended records. Idempotent: rows already present
    in the pool (e.g. a prior crashed run) are not re-appended, but are still
    marked ``fed_to_fewshot = true``. A run with nothing unfed is a no-op.
    """
    pool_path = Path(pool_path) if pool_path is not None else DEFAULT_POOL_PATH
    already_exported = _existing_correction_ids(pool_path)
    with db.transaction(connector=connector) as connection:
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT {_CORRECTION_COLUMNS} FROM correction_log "
            "WHERE fed_to_fewshot = false ORDER BY created_at, correction_id FOR UPDATE"
        )
        rows = cursor.fetchall()
        if not rows:
            return 0
        selected_ids = [row[0] for row in rows]
        new_records = [
            _record_from_row(row)
            for row in rows
            if str(row[0]) not in already_exported
        ]
        if new_records:
            _append_jsonl(pool_path, new_records)
        cursor.execute(
            "UPDATE correction_log SET fed_to_fewshot = true "
            "WHERE correction_id = ANY(%s)",
            (selected_ids,),
        )
    return len(new_records)


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pipeline.fewshot_export",
        description="Export unfed review corrections to the W5 few-shot pool (A5).",
    )
    parser.add_argument(
        "--pool-path",
        default=None,
        help=f"Override the JSONL pool path (default: {DEFAULT_POOL_PATH}).",
    )
    args = parser.parse_args(argv)
    pool = Path(args.pool_path) if args.pool_path else DEFAULT_POOL_PATH
    count = export_corrections_to_fewshot(pool_path=pool)
    print(f"Exported {count} correction(s) to {pool}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
