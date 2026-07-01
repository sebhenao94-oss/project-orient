"""In-memory ``ReviewStore`` seeded from the committed W4 snapshots (Track B).

This is both the dev backend and the test backbone for the FastAPI app. It needs
no database driver and no credentials: the read side loads
``data/snapshots/w04/*`` directly, and the write side keeps sessions/actions in
memory. Track A's ``PostgresReviewStore`` implements the same contract for the
Friday convergence; the HTTP layer cannot tell them apart.

Faithful Floor-02 reproduction (property ``b470b97b-...``):
* ``list_equipment`` → 56 items (11 ``settled``).
* ``list_discrepancies`` → 56: 11 matched, 19 missing_from_drawings (4 high = AHUs),
  19 missing_from_points, 7 ``resolved_out_of_scope`` (the Floor-1 trap).
* ``list_relationships`` → 0 edges, 50 orphans, ``passed=true``.
* ``list_zones`` → ``[]``.

Session semantics here mirror the agreed action rules (handoff §4.2): ``approve``
→ production only; ``edit`` → production + correction_log; ``reject`` →
correction_log only. The fake store currently allows a *partial* commit (it does
not refuse while items are pending); that is Track A's open design point (§4.6)
and does not affect the HTTP layer, which only delegates to ``commit_session``.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from pipeline.models import (
    DiscrepancyCategory,
    NormalizationStatus,
    RelationshipRefType,
)
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
    RelationshipView,
    SessionState,
    SessionStatus,
    ZoneQuery,
    ZoneReviewItem,
)

# Repo-root-relative snapshot directory; no machine paths, no env required.
_SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "snapshots" / "w04"

_FLOOR_AMBIGUOUS_RESOLVED_FLOOR = "1"  # supervisor ruling, 2026-06-22


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


# --------------------------------------------------------------------------- #
# Pure, file-backed loaders (credential-free; reusable by Track A's PG store)
# --------------------------------------------------------------------------- #
def load_equipment(snapshot_dir: Path = _SNAPSHOT_DIR) -> List[EquipmentReviewItem]:
    """Load the canonical Floor-02 equipment list into review DTOs."""
    path = snapshot_dir / "canonical_equipment_floor_02.csv"
    items: List[EquipmentReviewItem] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            evidence: List[EquipmentEvidence] = []
            if _as_bool(row["in_topics"]) and row.get("topics_raw_label"):
                evidence.append(
                    EquipmentEvidence(
                        source=EvidenceSource.TOPICS,
                        raw_label=row["topics_raw_label"],
                    )
                )
            if _as_bool(row["in_drawings"]) and row.get("drawing_raw_label"):
                evidence.append(
                    EquipmentEvidence(
                        source=EvidenceSource.DRAWING,
                        raw_label=row["drawing_raw_label"],
                    )
                )
            items.append(
                EquipmentReviewItem(
                    property_id=row["property_id"],
                    floor=row["floor"],
                    canonical_name=row["canonical_name"],
                    equipment_type=row["equipment_type"],
                    raw_equipment_type=row.get("raw_equipment_type") or None,
                    discrepancy_category=DiscrepancyCategory(row["discrepancy_category"]),
                    status=NormalizationStatus(row["status"]),
                    in_topics=_as_bool(row["in_topics"]),
                    in_drawings=_as_bool(row["in_drawings"]),
                    topics_raw_label=row.get("topics_raw_label") or None,
                    drawing_raw_label=row.get("drawing_raw_label") or None,
                    review_required=_as_bool(row["review_required"]),
                    review_reason=row.get("review_reason") or None,
                    confidence=None,  # unscored — see contract note
                    evidence=evidence,
                )
            )
    return items


def load_discrepancies(snapshot_dir: Path = _SNAPSHOT_DIR) -> List[DiscrepancyReviewItem]:
    """Load the gap report; pre-resolve the floor-ambiguous (_1_) trap units."""
    path = snapshot_dir / "discrepancy_report_floor_02.csv"
    items: List[DiscrepancyReviewItem] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            raw_status = row["status"]
            resolved_floor: Optional[str] = None
            if raw_status == DiscrepancyCategory.FLOOR_AMBIGUOUS.value:
                status = DiscrepancyStatus.RESOLVED_OUT_OF_SCOPE
                resolved_floor = _FLOOR_AMBIGUOUS_RESOLVED_FLOOR
            else:
                status = DiscrepancyStatus(raw_status)
            items.append(
                DiscrepancyReviewItem(
                    building=row["building"],
                    floor=row["floor"],
                    equipment_type=row["equipment_type"],
                    equipment_id=row["equipment_id"],
                    in_points=_as_bool(row["in_points"]),
                    in_drawings=_as_bool(row["in_drawings"]),
                    status=status,
                    evidence_point=row.get("evidence_point") or None,
                    evidence_drawing=row.get("evidence_drawing") or None,
                    severity_hint=row["severity_hint"],
                    resolved_floor=resolved_floor,
                )
            )
    return items


def load_relationship_view(snapshot_dir: Path = _SNAPSHOT_DIR) -> RelationshipView:
    """Load relationships + graph-validation into the relationships view."""
    rel_path = snapshot_dir / "relationships_floor_02.json"
    graph_path = snapshot_dir / "graph_validation_floor_02.json"
    rel_doc = json.loads(rel_path.read_text(encoding="utf-8"))
    graph_doc = json.loads(graph_path.read_text(encoding="utf-8"))

    edges = [
        RelationshipReviewItem(
            child=edge["child"],
            parent=edge["parent"],
            ref_type=RelationshipRefType(edge["ref_type"]),
            confidence=edge.get("confidence", 0.0),
            conflict=edge.get("conflict", False),
            conflict_reason=edge.get("conflict_reason", "") or "",
            review_required=edge.get("review_required", False),
            source_drawing=edge.get("source_drawing"),
        )
        for edge in rel_doc.get("relationships", [])
    ]

    def _findings(key: str) -> List[GraphFinding]:
        return [
            GraphFinding(
                check_id=finding["check_id"],
                severity=finding["severity"],
                message=finding["message"],
                nodes=finding.get("nodes", []),
            )
            for finding in graph_doc.get(key, [])
        ]

    return RelationshipView(
        edges=edges,
        orphans=_findings("orphans"),
        errors=_findings("errors"),
        review_items=_findings("review_items"),
        passed=graph_doc.get("passed", True),
    )


# --------------------------------------------------------------------------- #
# Read-path filtering / grouping (server-side, per the brief)
# --------------------------------------------------------------------------- #
def _filter_equipment(
    items: List[EquipmentReviewItem], query: EquipmentQuery
) -> List[EquipmentReviewItem]:
    result = list(items)
    if query.status is not None:
        result = [it for it in result if it.status == query.status]
    if query.review_required is not None:
        result = [it for it in result if it.review_required == query.review_required]
    if query.min_confidence is not None:
        result = [
            it
            for it in result
            if it.confidence is not None and it.confidence >= query.min_confidence
        ]
    return _sort_equipment(result, query.sort)


def _sort_equipment(
    items: List[EquipmentReviewItem], sort: EquipmentSort
) -> List[EquipmentReviewItem]:
    if sort == EquipmentSort.NAME:
        return sorted(items, key=lambda it: it.canonical_name)
    # Confidence sorts: scored items first (by confidence), unscored last
    # (deterministically by name), per handoff §4.3.
    scored = [it for it in items if it.confidence is not None]
    unscored = [it for it in items if it.confidence is None]
    scored.sort(
        key=lambda it: it.confidence,
        reverse=(sort == EquipmentSort.CONFIDENCE_DESC),
    )
    unscored.sort(key=lambda it: it.canonical_name)
    return scored + unscored


def _build_discrepancy_view(
    items: List[DiscrepancyReviewItem], query: DiscrepancyQuery
) -> DiscrepancyView:
    filtered = list(items)
    if query.status is not None:
        filtered = [it for it in filtered if it.status == query.status]
    if query.severity is not None:
        filtered = [it for it in filtered if it.severity_hint == query.severity]

    counts: Dict[str, int] = {}
    for item in filtered:
        counts[item.status.value] = counts.get(item.status.value, 0) + 1

    groups: Dict[str, List[DiscrepancyReviewItem]] = {}
    if query.group_by is not None:
        for item in filtered:
            key = _group_key(item, query.group_by)
            groups.setdefault(key, []).append(item)

    return DiscrepancyView(
        items=filtered,
        group_by=query.group_by,
        groups=groups,
        counts=counts,
        rollups=_build_rollups(filtered),
    )


def _group_key(item: DiscrepancyReviewItem, group_by: DiscrepancyGroupBy) -> str:
    if group_by == DiscrepancyGroupBy.FLOOR:
        return item.floor
    if group_by == DiscrepancyGroupBy.EQUIPMENT_TYPE:
        return item.equipment_type
    return item.severity_hint.value


def _build_rollups(items: List[DiscrepancyReviewItem]) -> List[str]:
    """Engineer-facing headline lines, e.g. 'Floor_02: 4 AHU missing from drawings'."""
    rollups: List[str] = []
    # High-severity breakdown by (status, equipment_type) — the riskiest gaps.
    high_breakdown: Dict[Tuple[str, str, str], int] = {}
    for item in items:
        if item.severity_hint.value == "high":
            key = (item.floor, item.status.value, item.equipment_type)
            high_breakdown[key] = high_breakdown.get(key, 0) + 1
    for (floor, status, equip_type), n in sorted(high_breakdown.items()):
        human = status.replace("_", " ")
        rollups.append(f"{floor}: {n} {equip_type} {human} (high severity)")
    return rollups


# --------------------------------------------------------------------------- #
# In-memory session state
# --------------------------------------------------------------------------- #
class _SessionRecord:
    def __init__(self, state: SessionState, pending_keys: Set[Tuple[str, str]]):
        self.state = state
        self.pending_keys = pending_keys
        self.actions: Dict[Tuple[str, str], ActionRequest] = {}


class FakeReviewStore:
    """File-seeded, in-memory ``ReviewStore`` implementation (satisfies the Protocol)."""

    def __init__(self, snapshot_dir: Path = _SNAPSHOT_DIR):
        self._snapshot_dir = snapshot_dir
        self._equipment = load_equipment(snapshot_dir)
        self._discrepancies = load_discrepancies(snapshot_dir)
        self._relationships = load_relationship_view(snapshot_dir)
        self._sessions: Dict[UUID, _SessionRecord] = {}

    # ---- read path ----
    def list_equipment(self, query: EquipmentQuery) -> List[EquipmentReviewItem]:
        return _filter_equipment(self._equipment, query)

    def list_relationships(self, query: RelationshipQuery) -> RelationshipView:
        # The reconciled contract's RelationshipQuery scopes by property/floor
        # only; the view always carries edges + orphans + errors so the client
        # renders the empty set (and populated edges later) without extra knobs.
        return self._relationships

    def list_discrepancies(self, query: DiscrepancyQuery) -> DiscrepancyView:
        return _build_discrepancy_view(self._discrepancies, query)

    def list_zones(self, query: ZoneQuery) -> List[ZoneReviewItem]:
        return []  # zone/orientation data arrives in W7

    def get_session(self, session_id: UUID) -> SessionState:
        return self._require(session_id).state

    # ---- write path ----
    def open_session(
        self, property_id: UUID, floor: str, reviewer: Optional[str] = None
    ) -> SessionState:
        # Pending work = review-required equipment not already pre-resolved
        # (floor-ambiguous units are resolved out of scope) plus relationship
        # review items (currently none).
        pending_keys: Set[Tuple[str, str]] = {
            (ItemType.EQUIPMENT.value, it.canonical_name)
            for it in self._equipment
            if it.floor == floor
            and it.review_required
            and it.status != NormalizationStatus.FLOOR_AMBIGUOUS
        }
        now = datetime.now(timezone.utc)
        state = SessionState(
            session_id=uuid4(),
            property_id=property_id,
            floor=floor,
            status=SessionStatus.OPEN,
            created_by=reviewer,
            n_pending=len(pending_keys),
            n_approved=0,
            n_rejected=0,
            created_at=now,
        )
        self._sessions[state.session_id] = _SessionRecord(state, pending_keys)
        return state

    def record_action(self, session_id: UUID, request: ActionRequest) -> ActionResult:
        record = self._require(session_id)
        if record.state.status != SessionStatus.OPEN:
            raise ValueError("cannot record actions against a non-open session")
        record.actions[(request.item_type.value, request.item_key)] = request
        self._recount(record)
        return ActionResult(
            action_id=uuid4(),
            session_id=session_id,
            item_type=request.item_type,
            item_key=request.item_key,
            action=request.action,
            applied=False,  # decisions apply to production only at commit
            session_state=record.state,
        )

    def commit_session(self, session_id: UUID) -> CommitResult:
        record = self._require(session_id)
        if record.state.status == SessionStatus.COMMITTED:
            raise ValueError("session already committed")
        actions = list(record.actions.values())
        n_approve = sum(1 for a in actions if a.action == ActionType.APPROVE)
        n_edit = sum(1 for a in actions if a.action == ActionType.EDIT)
        n_reject = sum(1 for a in actions if a.action == ActionType.REJECT)
        now = datetime.now(timezone.utc)
        record.state.status = SessionStatus.COMMITTED
        record.state.committed_at = now
        record.state.n_pending = 0
        return CommitResult(
            session_id=session_id,
            committed=True,
            n_committed=n_approve + n_edit,    # approve + edit reach production
            n_corrections=n_edit + n_reject,   # edit + reject write correction_log
            committed_at=now,
            errors=[],
        )

    # ---- internals ----
    def _require(self, session_id: UUID) -> _SessionRecord:
        record = self._sessions.get(session_id)
        if record is None:
            raise KeyError(f"unknown session {session_id}")
        return record

    def _recount(self, record: _SessionRecord) -> None:
        actioned_keys = set(record.actions.keys())
        n_approved = sum(
            1
            for a in record.actions.values()
            if a.action in (ActionType.APPROVE, ActionType.EDIT)
        )
        n_rejected = sum(
            1 for a in record.actions.values() if a.action == ActionType.REJECT
        )
        record.state.n_approved = n_approved
        record.state.n_rejected = n_rejected
        record.state.n_pending = len(record.pending_keys - actioned_keys)
