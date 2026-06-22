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
import csv
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

if __package__:
    from . import db
else:
    import db

try:
    from review_api.contracts import (
        DiscrepancyGroupBy,
        DiscrepancyQuery,
        DiscrepancyReviewItem,
        DiscrepancyStatus,
        DiscrepancyView,
        EquipmentQuery,
        EquipmentReviewItem,
        EquipmentSort,
        GraphFinding,
        RelationshipQuery,
        RelationshipReviewItem,
        RelationshipView,
        ZoneQuery,
        ZoneReviewItem,
    )
except ModuleNotFoundError:  # pragma: no cover - add project root for the bare-import layout
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from review_api.contracts import (
        DiscrepancyGroupBy,
        DiscrepancyQuery,
        DiscrepancyReviewItem,
        DiscrepancyStatus,
        DiscrepancyView,
        EquipmentQuery,
        EquipmentReviewItem,
        EquipmentSort,
        GraphFinding,
        RelationshipQuery,
        RelationshipReviewItem,
        RelationshipView,
        ZoneQuery,
        ZoneReviewItem,
    )

SCHEMA_FILE = Path(__file__).resolve().parent / "review_schema.sql"
W4_SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "snapshots" / "w04"


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


# --------------------------------------------------------------------------- #
# Read-half store (A3): load the committed W4 snapshots into the contract DTOs.
# These files are immutable evidence; this is the production-faithful twin of
# Track B's FakeReviewStore. The session/commit write path and the Postgres
# reference reads (topics, Floor-1 equipment_details) land in A4.
# --------------------------------------------------------------------------- #
def _csv_rows(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    return value if value not in (None, "") else None


def load_equipment(snapshot_dir: Path) -> List[EquipmentReviewItem]:
    items: List[EquipmentReviewItem] = []
    for row in _csv_rows(snapshot_dir / "canonical_equipment_floor_02.csv"):
        items.append(
            EquipmentReviewItem(
                property_id=_blank_to_none(row.get("property_id")),
                floor=row["floor"],
                canonical_name=row["canonical_name"],
                canonical_key=row["canonical_key"],
                equipment_type=row["equipment_type"],
                raw_equipment_type=_blank_to_none(row.get("raw_equipment_type")),
                discrepancy_category=row["discrepancy_category"],
                status=row["status"],
                in_topics=_as_bool(row["in_topics"]),
                in_drawings=_as_bool(row["in_drawings"]),
                topics_raw_label=_blank_to_none(row.get("topics_raw_label")),
                drawing_raw_label=_blank_to_none(row.get("drawing_raw_label")),
                confidence=None,  # W4 confidence is uncalibrated; not carried in canonical CSV
                review_required=_as_bool(row["review_required"]),
                review_reason=_blank_to_none(row.get("review_reason")),
            )
        )
    return items


def _sort_equipment(items, sort):
    if sort == EquipmentSort.NAME:
        return sorted(items, key=lambda i: i.canonical_name)
    if sort == EquipmentSort.CONFIDENCE_DESC:
        return sorted(
            items,
            key=lambda i: (-(i.confidence if i.confidence is not None else -1e9), i.canonical_name),
        )
    # CONFIDENCE_ASC (default): low confidence first; None sorts last.
    return sorted(
        items,
        key=lambda i: (i.confidence if i.confidence is not None else 1e9, i.canonical_name),
    )


def _filter_equipment(items, query):
    result = list(items)
    if query.property_id:
        result = [i for i in result if i.property_id == query.property_id]
    if query.floor:
        result = [i for i in result if i.floor == query.floor]
    if query.status is not None:
        result = [i for i in result if i.status == query.status]
    if query.review_required is not None:
        result = [i for i in result if i.review_required == query.review_required]
    if query.min_confidence is not None:
        result = [
            i for i in result if i.confidence is not None and i.confidence >= query.min_confidence
        ]
    return _sort_equipment(result, query.sort)


def load_relationship_view(snapshot_dir: Path) -> RelationshipView:
    rel = json.loads((snapshot_dir / "relationships_floor_02.json").read_text(encoding="utf-8"))
    val = json.loads((snapshot_dir / "graph_validation_floor_02.json").read_text(encoding="utf-8"))
    edges = [RelationshipReviewItem(**edge) for edge in rel.get("relationships", [])]

    def findings(key: str) -> List[GraphFinding]:
        return [
            GraphFinding(
                check_id=f["check_id"],
                severity=f["severity"],
                message=f["message"],
                nodes=list(f.get("nodes", [])),
            )
            for f in val.get(key, [])
        ]

    return RelationshipView(
        edges=edges,
        orphans=findings("orphans"),
        errors=findings("errors"),
        review_items=findings("review_items"),
        passed=bool(val.get("passed", True)),
    )


_FLOOR_AMBIGUOUS = "floor_ambiguous"


def load_discrepancies(snapshot_dir: Path) -> List[DiscrepancyReviewItem]:
    items: List[DiscrepancyReviewItem] = []
    for row in _csv_rows(snapshot_dir / "discrepancy_report_floor_02.csv"):
        status = row["status"]
        resolved_floor: Optional[str] = None
        if status == _FLOOR_AMBIGUOUS:
            # Supervisor ruling (June 22): the 7 _1_ units are Floor 1, logged under
            # the Floor_02 path as a deliberate trap -> pre-resolved, out of scope.
            status = DiscrepancyStatus.RESOLVED_OUT_OF_SCOPE.value
            resolved_floor = "1"
        items.append(
            DiscrepancyReviewItem(
                building=row["building"],
                floor=row["floor"],
                equipment_type=row["equipment_type"],
                equipment_id=row["equipment_id"],
                in_points=_as_bool(row["in_points"]),
                in_drawings=_as_bool(row["in_drawings"]),
                status=status,
                evidence_point=_blank_to_none(row.get("evidence_point")),
                evidence_drawing=_blank_to_none(row.get("evidence_drawing")),
                severity_hint=row["severity_hint"],
                resolved_floor=resolved_floor,
            )
        )
    return items


def _group_key(item, group_by) -> str:
    if group_by == DiscrepancyGroupBy.FLOOR:
        return item.floor
    if group_by == DiscrepancyGroupBy.EQUIPMENT_TYPE:
        return item.equipment_type
    return item.severity_hint.value


def _build_rollups(items) -> List[str]:
    phrases = {
        "missing_from_drawings": "missing from drawings",
        "missing_from_points": "missing from points",
    }
    counts: Dict[Any, int] = {}
    for item in items:
        sval = item.status.value
        if sval in phrases:
            key = (item.floor, item.equipment_type, sval)
            counts[key] = counts.get(key, 0) + 1
    rollups: List[str] = []
    for (floor, etype, sval), n in sorted(counts.items()):
        floor_label = floor.replace("Floor_0", "Floor ").replace("Floor_", "Floor ")
        plural = "s" if n != 1 else ""
        rollups.append(f"{floor_label}: {n} {etype}{plural} {phrases[sval]}")
    return rollups


def _build_discrepancy_view(items, query) -> DiscrepancyView:
    result = list(items)
    if query.floor:
        result = [i for i in result if i.floor == query.floor]
    if query.status is not None:
        result = [i for i in result if i.status == query.status]
    if query.severity is not None:
        result = [i for i in result if i.severity_hint == query.severity]
    counts: Dict[str, int] = {}
    for item in result:
        counts[item.status.value] = counts.get(item.status.value, 0) + 1
    groups = None
    if query.group_by is not None:
        groups = {}
        for item in result:
            groups.setdefault(_group_key(item, query.group_by), []).append(item)
    return DiscrepancyView(
        items=result,
        group_by=query.group_by,
        groups=groups,
        counts=counts,
        rollups=_build_rollups(result),
    )


class PostgresReviewStore:
    """ReviewStore implementation.

    Read half (A3): loads the immutable committed W4 snapshots into the contract
    DTOs (the production-faithful twin of Track B's FakeReviewStore). The session
    / commit write half and the Postgres reference reads (topics, Floor-1
    equipment_details) land in A4 via ``db.transaction`` / ``db.connect_readonly``.
    """

    def __init__(
        self,
        snapshot_dir: Optional[Path] = None,
        *,
        connector: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir is not None else W4_SNAPSHOT_DIR
        self._connector = connector  # reserved for the A4 write path

    # ---- read path (A3) ----
    def list_equipment(self, query: EquipmentQuery) -> List[EquipmentReviewItem]:
        return _filter_equipment(load_equipment(self.snapshot_dir), query)

    def list_relationships(self, query: RelationshipQuery) -> RelationshipView:
        return load_relationship_view(self.snapshot_dir)

    def list_discrepancies(self, query: DiscrepancyQuery) -> DiscrepancyView:
        return _build_discrepancy_view(load_discrepancies(self.snapshot_dir), query)

    def list_zones(self, query: ZoneQuery) -> List[ZoneReviewItem]:
        return []  # zones arrive in W7

    # ---- write path (A4) ----
    def get_session(self, session_id):  # pragma: no cover - lands in A4
        raise NotImplementedError("get_session lands in A4 (DB-backed session state).")

    def open_session(self, property_id, floor, reviewer=None):  # pragma: no cover - A4
        raise NotImplementedError("open_session lands in A4.")

    def record_action(self, session_id, request):  # pragma: no cover - A4
        raise NotImplementedError("record_action lands in A4.")

    def commit_session(self, session_id):  # pragma: no cover - A4
        raise NotImplementedError("commit_session lands in A4.")


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
