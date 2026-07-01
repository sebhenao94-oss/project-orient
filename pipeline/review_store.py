"""W5 review-agent store and schema management (Track A).

For now this module owns the review-side schema (``review_session``,
``review_action``, ``correction_log``) and a ``--create-tables`` entry point
that applies it idempotently:

    py -m pipeline.review_store --create-tables

``PostgresReviewStore`` loads the immutable W4 review inbox and implements the
DB-backed session/action portion of the shared ``ReviewStore`` interface. The
atomic production commit is the remaining A4 slice.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID, uuid4

if __package__:
    from . import db
    from .equipment_vocab import map_equipment_type
    from .normalization import canonical_key
else:
    import db
    from equipment_vocab import map_equipment_type
    from normalization import canonical_key

try:
    from review_api.contracts import (
        ActionRequest,
        ActionResult,
        ActionType,
        CommitResult,
        DiscrepancyGroupBy,
        DiscrepancyQuery,
        DiscrepancyReviewItem,
        DiscrepancyStatus,
        DiscrepancyView,
        EquipmentEvidence,
        EquipmentQuery,
        EquipmentReviewItem,
        EquipmentSort,
        EvidenceSource,
        GraphFinding,
        ItemType,
        RelationshipQuery,
        RelationshipReviewItem,
        RelationshipRefType,
        RelationshipView,
        SessionState,
        SessionStatus,
        ZoneQuery,
        ZoneReviewItem,
    )
except ModuleNotFoundError:  # pragma: no cover - add project root for the bare-import layout
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from review_api.contracts import (
        ActionRequest,
        ActionResult,
        ActionType,
        CommitResult,
        DiscrepancyGroupBy,
        DiscrepancyQuery,
        DiscrepancyReviewItem,
        DiscrepancyStatus,
        DiscrepancyView,
        EquipmentEvidence,
        EquipmentQuery,
        EquipmentReviewItem,
        EquipmentSort,
        EvidenceSource,
        GraphFinding,
        ItemType,
        RelationshipQuery,
        RelationshipReviewItem,
        RelationshipRefType,
        RelationshipView,
        SessionState,
        SessionStatus,
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


def _optional_float(value: Optional[str]) -> Optional[float]:
    return float(value) if value not in (None, "") else None


def _optional_int(value: Optional[str]) -> Optional[int]:
    return int(value) if value not in (None, "") else None


def load_equipment_evidence(snapshot_dir: Path) -> Dict[str, List[EquipmentEvidence]]:
    """Aggregate W3 source occurrences under the W4 canonical equipment key.

    Evidence remains source-specific and never creates another review item. The
    drawing confidence values are retained as provenance only; they are not
    promoted to the canonical item's confidence because W3 found them to be
    uncalibrated.
    """
    evidence: Dict[str, List[EquipmentEvidence]] = defaultdict(list)
    w3_dir = snapshot_dir.parent / "w03"

    topics_path = w3_dir / "topics_equipment_floor_02.csv"
    if topics_path.exists():
        for row in _csv_rows(topics_path):
            raw_label = row.get("raw_label") or row.get("raw_equipment_context") or ""
            if not raw_label:
                continue
            evidence[canonical_key(raw_label)].append(
                EquipmentEvidence(
                    source=EvidenceSource.TOPICS,
                    raw_label=raw_label,
                    evidence_strength=_blank_to_none(row.get("evidence_strength")),
                    topic_count=_optional_int(row.get("topic_count")),
                )
            )

    drawing_path = w3_dir / "drawing_equipment_floor_02.csv"
    if drawing_path.exists():
        for row in _csv_rows(drawing_path):
            raw_label = row.get("raw_label") or ""
            if not raw_label:
                continue
            match_label = row.get("llm_proposed_canonical_name") or raw_label
            evidence[canonical_key(match_label)].append(
                EquipmentEvidence(
                    source=EvidenceSource.DRAWING,
                    raw_label=raw_label,
                    source_filename=_blank_to_none(row.get("source_filename")),
                    source_relative_path=_blank_to_none(row.get("source_relative_path")),
                    source_sha256=_blank_to_none(row.get("source_sha256")),
                    confidence=_optional_float(row.get("confidence")),
                )
            )

    return dict(evidence)


def load_equipment(snapshot_dir: Path) -> List[EquipmentReviewItem]:
    items: List[EquipmentReviewItem] = []
    evidence_by_key = load_equipment_evidence(snapshot_dir)
    for row in _csv_rows(snapshot_dir / "canonical_equipment_floor_02.csv"):
        key = row["canonical_key"]
        items.append(
            EquipmentReviewItem(
                property_id=_blank_to_none(row.get("property_id")),
                floor=row["floor"],
                canonical_name=row["canonical_name"],
                canonical_key=key,
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
                evidence=evidence_by_key.get(key, []),
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


class ReviewSessionNotFoundError(KeyError):
    """Raised when a requested review session does not exist."""


class ReviewSessionStateError(RuntimeError):
    """Raised when an operation is invalid for the session's current state."""


class ReviewItemNotFoundError(KeyError):
    """Raised when an action does not identify one reviewable source item."""


class ReviewPayloadError(ValueError):
    """Raised when edited fields cannot be mapped safely to production."""


class ProductionIdentityConflictError(RuntimeError):
    """Raised when a canonical identity maps to multiple production rows."""


_SESSION_COLUMNS = (
    "session_id, property_id, floor, status, created_by, created_at, "
    "committed_at, n_pending, n_approved, n_rejected"
)


def _session_from_row(row: Any) -> SessionState:
    if row is None:
        raise ReviewSessionNotFoundError("review session not found")
    values = dict(zip(
        (
            "session_id",
            "property_id",
            "floor",
            "status",
            "created_by",
            "created_at",
            "committed_at",
            "n_pending",
            "n_approved",
            "n_rejected",
        ),
        row,
    ))
    return SessionState(**values)


def _relationship_item_key(item: RelationshipReviewItem) -> str:
    return f"{item.child}|{item.ref_type.value}|{item.parent}"


def _production_identity(name: str) -> str:
    """Return an alias-aware physical identity for an equipment name."""
    equipment_type, separator, remainder = (name or "").partition("_")
    if not separator:
        return canonical_key(name)
    mapped_type = map_equipment_type(equipment_type).mapped_type
    normalized_tail = canonical_key(f"EQUIP_{remainder}").partition("_")[2]
    return f"{mapped_type}|{normalized_tail}"


def _floor_ref(floor: str, equipment_type: str) -> Optional[str]:
    if equipment_type.upper().endswith("-PLANT"):
        return None
    digits = "".join(character for character in floor if character.isdigit())
    if not digits:
        raise ReviewPayloadError(f"cannot map floor {floor!r} to equipment_details.floorRef")
    return str(int(digits))


def _json_payload(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


class PostgresReviewStore:
    """ReviewStore implementation.

    The A3 read half loads immutable W4 snapshots into the shared DTOs. The A4
    write half persists review sessions/actions through ``db.transaction``; the
    final atomic production flush is implemented separately by ``commit_session``.
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
    def _reviewable_equipment(self, property_id: UUID, floor: str) -> List[EquipmentReviewItem]:
        items = self.list_equipment(
            EquipmentQuery(
                property_id=str(property_id),
                floor=floor,
                review_required=True,
            )
        )
        # The seven floor-ambiguous rows were resolved as Floor 1 and are not
        # pending Floor-02 decisions.
        return [item for item in items if item.status.value != _FLOOR_AMBIGUOUS]

    def _initial_pending_count(self, property_id: UUID, floor: str) -> int:
        equipment_keys = {
            item.canonical_key for item in self._reviewable_equipment(property_id, floor)
        }
        relationship_keys = {
            _relationship_item_key(item)
            for item in self.list_relationships(
                RelationshipQuery(property_id=str(property_id), floor=floor)
            ).edges
        }
        # Discrepancies are evidence on equipment items, not separate decisions.
        return len(equipment_keys) + len(relationship_keys)

    def _resolve_action_item_key(
        self, session: SessionState, request: ActionRequest
    ) -> str:
        requested_key = request.item_key.strip()
        if request.item_type == ItemType.EQUIPMENT:
            matches = [
                item
                for item in self._reviewable_equipment(session.property_id, session.floor)
                if requested_key in (item.canonical_key, item.canonical_name)
            ]
            if len(matches) == 1:
                return matches[0].canonical_key
        elif request.item_type == ItemType.RELATIONSHIP:
            matches = [
                item
                for item in self.list_relationships(
                    RelationshipQuery(
                        property_id=str(session.property_id), floor=session.floor
                    )
                ).edges
                if requested_key == _relationship_item_key(item)
            ]
            if len(matches) == 1:
                return requested_key
        elif request.item_type == ItemType.ZONE:
            matches = [
                item
                for item in self.list_zones(
                    ZoneQuery(property_id=str(session.property_id), floor=session.floor)
                )
                if requested_key == item.zone_id
            ]
            if len(matches) == 1:
                return requested_key
        elif request.item_type == ItemType.DISCREPANCY:
            raise ReviewItemNotFoundError(
                "discrepancies are equipment evidence; act on the equipment item"
            )

        raise ReviewItemNotFoundError(
            f"no unique reviewable {request.item_type.value} item matches {requested_key!r}"
        )

    def get_session(self, session_id: UUID) -> SessionState:
        with db.transaction(readonly=True, connector=self._connector) as connection:
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT {_SESSION_COLUMNS} FROM review_session WHERE session_id = %s",
                (session_id,),
            )
            return _session_from_row(cursor.fetchone())

    def open_session(
        self, property_id: UUID, floor: str, reviewer: Optional[str] = None
    ) -> SessionState:
        session_id = uuid4()
        n_pending = self._initial_pending_count(property_id, floor)
        with db.transaction(connector=self._connector) as connection:
            cursor = connection.cursor()
            cursor.execute(
                f"""
                INSERT INTO review_session
                    (session_id, property_id, floor, created_by, n_pending)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {_SESSION_COLUMNS}
                """,
                (session_id, property_id, floor, reviewer, n_pending),
            )
            return _session_from_row(cursor.fetchone())

    def record_action(
        self, session_id: UUID, request: ActionRequest
    ) -> ActionResult:
        with db.transaction(connector=self._connector) as connection:
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT {_SESSION_COLUMNS} FROM review_session "
                "WHERE session_id = %s FOR UPDATE",
                (session_id,),
            )
            session = _session_from_row(cursor.fetchone())
            if session.status != SessionStatus.OPEN:
                raise ReviewSessionStateError(
                    f"session {session_id} is {session.status.value}, not open"
                )

            item_key = self._resolve_action_item_key(session, request)
            action_id = uuid4()
            payload_json = json.dumps(request.payload) if request.payload is not None else None
            cursor.execute(
                """
                INSERT INTO review_action
                    (action_id, session_id, item_type, item_key, action, payload,
                     confidence, reviewer, reason)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                ON CONFLICT (session_id, item_type, item_key) DO UPDATE SET
                    action = EXCLUDED.action,
                    payload = EXCLUDED.payload,
                    confidence = EXCLUDED.confidence,
                    reviewer = EXCLUDED.reviewer,
                    reason = EXCLUDED.reason,
                    applied = false,
                    applied_at = NULL,
                    created_at = now()
                RETURNING action_id, applied
                """,
                (
                    action_id,
                    session_id,
                    request.item_type.value,
                    item_key,
                    request.action.value,
                    payload_json,
                    request.confidence,
                    request.reviewer,
                    request.reason,
                ),
            )
            stored_action_id, applied = cursor.fetchone()

            total_items = session.n_pending + session.n_approved + session.n_rejected
            cursor.execute(
                """
                SELECT
                    count(*) FILTER (WHERE action IN ('approve', 'edit')),
                    count(*) FILTER (WHERE action = 'reject')
                FROM review_action
                WHERE session_id = %s
                """,
                (session_id,),
            )
            n_approved, n_rejected = cursor.fetchone()
            n_pending = max(total_items - n_approved - n_rejected, 0)
            cursor.execute(
                f"""
                UPDATE review_session
                SET n_pending = %s, n_approved = %s, n_rejected = %s
                WHERE session_id = %s
                RETURNING {_SESSION_COLUMNS}
                """,
                (n_pending, n_approved, n_rejected, session_id),
            )
            updated_session = _session_from_row(cursor.fetchone())
            return ActionResult(
                action_id=stored_action_id,
                session_id=session_id,
                item_type=request.item_type,
                item_key=item_key,
                action=request.action,
                applied=applied,
                session_state=updated_session,
            )

    def _equipment_item_for_key(
        self, session: SessionState, item_key: str
    ) -> EquipmentReviewItem:
        matches = [
            item
            for item in self._reviewable_equipment(session.property_id, session.floor)
            if item.canonical_key == item_key
        ]
        if len(matches) != 1:
            raise ReviewItemNotFoundError(
                f"equipment action key {item_key!r} no longer resolves uniquely"
            )
        return matches[0]

    def _relationship_item_for_key(
        self, session: SessionState, item_key: str
    ) -> RelationshipReviewItem:
        matches = [
            item
            for item in self.list_relationships(
                RelationshipQuery(
                    property_id=str(session.property_id), floor=session.floor
                )
            ).edges
            if _relationship_item_key(item) == item_key
        ]
        if len(matches) != 1:
            raise ReviewItemNotFoundError(
                f"relationship action key {item_key!r} no longer resolves uniquely"
            )
        return matches[0]

    @staticmethod
    def _equipment_values(
        item: EquipmentReviewItem, payload: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        values = {
            "canonical_name": item.canonical_name,
            "equipment_type": item.equipment_type,
            "floor": item.floor,
            "zone": None,
            "space_ref": None,
        }
        changes = payload or {}
        unsupported = set(changes) - set(values)
        if unsupported:
            raise ReviewPayloadError(
                "unsupported equipment edit field(s): " + ", ".join(sorted(unsupported))
            )
        values.update(changes)
        for field in ("canonical_name", "equipment_type", "floor"):
            value = values[field]
            if not isinstance(value, str) or not value.strip():
                raise ReviewPayloadError(f"equipment {field} must be a non-empty string")
            values[field] = value.strip()
        return values

    @staticmethod
    def _relationship_values(
        item: RelationshipReviewItem, payload: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        values = {
            "child": item.child,
            "parent": item.parent,
            "ref_type": item.ref_type.value,
        }
        changes = payload or {}
        unsupported = set(changes) - set(values)
        if unsupported:
            raise ReviewPayloadError(
                "unsupported relationship edit field(s): " + ", ".join(sorted(unsupported))
            )
        values.update(changes)
        for field in ("child", "parent", "ref_type"):
            value = values[field]
            if not isinstance(value, str) or not value.strip():
                raise ReviewPayloadError(f"relationship {field} must be a non-empty string")
            values[field] = value.strip()
        try:
            values["ref_type"] = RelationshipRefType(values["ref_type"])
        except ValueError as exc:
            raise ReviewPayloadError(
                f"unsupported relationship ref_type {values['ref_type']!r}"
            ) from exc
        return values

    @staticmethod
    def _load_property_equipment(cursor: Any, property_id: UUID) -> List[Dict[str, Any]]:
        cursor.execute(
            "SELECT equipment_id, name FROM public.equipment_details "
            "WHERE property_id = %s FOR UPDATE",
            (property_id,),
        )
        return [
            {"equipment_id": row[0], "name": row[1]}
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _resolve_production_equipment(
        existing: List[Dict[str, Any]], name: str
    ) -> Optional[Dict[str, Any]]:
        identity = _production_identity(name)
        matches = [row for row in existing if _production_identity(row["name"]) == identity]
        if len(matches) > 1:
            raise ProductionIdentityConflictError(
                f"production identity {identity!r} matches multiple equipment rows"
            )
        return matches[0] if matches else None

    def _upsert_equipment(
        self,
        cursor: Any,
        property_id: UUID,
        values: Dict[str, Any],
        existing: List[Dict[str, Any]],
        original_name: Optional[str] = None,
    ) -> int:
        name = values["canonical_name"]
        equipment_type = values["equipment_type"]
        floor_ref = _floor_ref(values["floor"], equipment_type)
        current = self._resolve_production_equipment(existing, name)
        original = (
            self._resolve_production_equipment(existing, original_name)
            if original_name and original_name != name
            else None
        )
        if current and original and current["equipment_id"] != original["equipment_id"]:
            raise ProductionIdentityConflictError(
                f"edited identity {name!r} already belongs to another equipment row"
            )
        current = current or original
        if current is None:
            # equipment_details has no type column: the {Type}_{floor}-{unit} `name`
            # encodes it. systemRef_type describes a systemRef parent relationship,
            # not the equipment's own type, so it is left to relationship writes.
            cursor.execute(
                """
                INSERT INTO public.equipment_details
                    (name, property_id, "floorRef", zone, "spaceRef")
                VALUES (%s, %s, %s, %s, %s)
                RETURNING equipment_id
                """,
                (
                    name,
                    property_id,
                    floor_ref,
                    values["zone"],
                    values["space_ref"],
                ),
            )
            equipment_id = cursor.fetchone()[0]
            existing.append({"equipment_id": equipment_id, "name": name})
            return equipment_id

        cursor.execute(
            """
            UPDATE public.equipment_details
            SET name = %s, "floorRef" = %s, zone = %s, "spaceRef" = %s
            WHERE equipment_id = %s
            RETURNING equipment_id
            """,
            (
                name,
                floor_ref,
                values["zone"],
                values["space_ref"],
                current["equipment_id"],
            ),
        )
        equipment_id = cursor.fetchone()[0]
        current["name"] = name
        return equipment_id

    def _apply_relationship(
        self,
        cursor: Any,
        values: Dict[str, Any],
        existing: List[Dict[str, Any]],
    ) -> None:
        columns = {
            RelationshipRefType.AIR_REF: '"airRef"',
            RelationshipRefType.CHILLED_WATER_REF: '"chilledWaterRef"',
            RelationshipRefType.HOT_WATER_REF: '"hotWaterRef"',
            RelationshipRefType.CONDENSER_WATER_REF: '"condenserWaterRef"',
            RelationshipRefType.SYSTEM_REF: '"systemRef"',
        }
        ref_type = values["ref_type"]
        if ref_type not in columns:
            raise ReviewPayloadError(
                f"{ref_type.value} is not an equipment-to-equipment production reference"
            )
        child = self._resolve_production_equipment(existing, values["child"])
        parent = self._resolve_production_equipment(existing, values["parent"])
        if child is None or parent is None:
            missing = values["child"] if child is None else values["parent"]
            raise ReviewItemNotFoundError(
                f"relationship endpoint {missing!r} is absent from equipment_details"
            )
        cursor.execute(
            f"UPDATE public.equipment_details SET {columns[ref_type]} = %s "
            "WHERE equipment_id = %s",
            (parent["equipment_id"], child["equipment_id"]),
        )

    @staticmethod
    def _write_correction(
        cursor: Any,
        session: SessionState,
        action: Dict[str, Any],
        original: Dict[str, Any],
        corrected: Optional[Dict[str, Any]],
    ) -> None:
        reason = action["reason"]
        if not reason:
            raise ReviewPayloadError(
                f"{action['action']} action {action['item_key']!r} has no reason"
            )
        cursor.execute(
            """
            INSERT INTO correction_log
                (correction_id, session_id, item_type, item_key, original,
                 corrected, reason, reviewer)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            """,
            (
                uuid4(),
                session.session_id,
                action["item_type"],
                action["item_key"],
                json.dumps(original),
                json.dumps(corrected) if corrected is not None else None,
                reason,
                action["reviewer"] or session.created_by,
            ),
        )

    @staticmethod
    def _action_from_row(row: Any) -> Dict[str, Any]:
        return dict(
            zip(
                (
                    "action_id",
                    "item_type",
                    "item_key",
                    "action",
                    "payload",
                    "confidence",
                    "reviewer",
                    "reason",
                ),
                row,
            )
        )

    def commit_session(self, session_id: UUID) -> CommitResult:
        """Atomically apply one complete review session to production."""
        with db.transaction(connector=self._connector) as connection:
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT {_SESSION_COLUMNS} FROM review_session "
                "WHERE session_id = %s FOR UPDATE",
                (session_id,),
            )
            session = _session_from_row(cursor.fetchone())

            if session.status == SessionStatus.COMMITTED:
                cursor.execute(
                    """
                    SELECT
                        count(*) FILTER (
                            WHERE applied AND action IN ('approve', 'edit')
                        ),
                        (SELECT count(*) FROM correction_log WHERE session_id = %s)
                    FROM review_action
                    WHERE session_id = %s
                    """,
                    (session_id, session_id),
                )
                n_committed, n_corrections = cursor.fetchone()
                return CommitResult(
                    session_id=session_id,
                    committed=True,
                    n_committed=n_committed,
                    n_corrections=n_corrections,
                    committed_at=session.committed_at,
                )
            if session.status != SessionStatus.OPEN:
                raise ReviewSessionStateError(
                    f"session {session_id} is {session.status.value}, not open"
                )
            if session.n_pending:
                raise ReviewSessionStateError(
                    f"session {session_id} still has {session.n_pending} pending item(s)"
                )

            cursor.execute(
                """
                SELECT action_id, item_type, item_key, action, payload,
                       confidence, reviewer, reason
                FROM review_action
                WHERE session_id = %s AND applied = false
                ORDER BY created_at, action_id
                FOR UPDATE
                """,
                (session_id,),
            )
            actions = [self._action_from_row(row) for row in cursor.fetchall()]
            existing = self._load_property_equipment(cursor, session.property_id)
            claimed_equipment: Dict[int, str] = {}
            n_committed = 0
            n_corrections = 0

            # Equipment must land before relationships so same-session endpoints resolve.
            for action in actions:
                if action["item_type"] != ItemType.EQUIPMENT.value:
                    continue
                item = self._equipment_item_for_key(session, action["item_key"])
                original = item.model_dump(mode="json")
                payload = _json_payload(action["payload"])
                if action["action"] == ActionType.REJECT.value:
                    self._write_correction(cursor, session, action, original, None)
                    n_corrections += 1
                    continue
                values = self._equipment_values(item, payload)
                equipment_id = self._upsert_equipment(
                    cursor,
                    session.property_id,
                    values,
                    existing,
                    original_name=item.canonical_name,
                )
                previous_key = claimed_equipment.setdefault(
                    equipment_id, action["item_key"]
                )
                if previous_key != action["item_key"]:
                    raise ProductionIdentityConflictError(
                        f"review items {previous_key!r} and {action['item_key']!r} "
                        f"both map to equipment_id {equipment_id}"
                    )
                n_committed += 1
                if action["action"] == ActionType.EDIT.value:
                    self._write_correction(cursor, session, action, original, values)
                    n_corrections += 1

            for action in actions:
                if action["item_type"] != ItemType.RELATIONSHIP.value:
                    continue
                item = self._relationship_item_for_key(session, action["item_key"])
                original = item.model_dump(mode="json")
                payload = _json_payload(action["payload"])
                if action["action"] == ActionType.REJECT.value:
                    self._write_correction(cursor, session, action, original, None)
                    n_corrections += 1
                    continue
                values = self._relationship_values(item, payload)
                self._apply_relationship(cursor, values, existing)
                n_committed += 1
                if action["action"] == ActionType.EDIT.value:
                    corrected = dict(values)
                    corrected["ref_type"] = values["ref_type"].value
                    self._write_correction(
                        cursor, session, action, original, corrected
                    )
                    n_corrections += 1

            unsupported = [
                action["item_type"]
                for action in actions
                if action["item_type"]
                not in (ItemType.EQUIPMENT.value, ItemType.RELATIONSHIP.value)
            ]
            if unsupported:
                raise ReviewPayloadError(
                    "commit does not support item type(s): "
                    + ", ".join(sorted(set(unsupported)))
                )

            if actions:
                cursor.execute(
                    """
                    UPDATE review_action
                    SET applied = true, applied_at = now()
                    WHERE session_id = %s AND action_id = ANY(%s)
                    """,
                    (session_id, [action["action_id"] for action in actions]),
                )
            cursor.execute(
                f"""
                UPDATE review_session
                SET status = 'committed', committed_at = now()
                WHERE session_id = %s
                RETURNING {_SESSION_COLUMNS}
                """,
                (session_id,),
            )
            committed_session = _session_from_row(cursor.fetchone())
            return CommitResult(
                session_id=session_id,
                committed=True,
                n_committed=n_committed,
                n_corrections=n_corrections,
                committed_at=committed_session.committed_at,
            )


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
