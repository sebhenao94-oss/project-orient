"""Shared contract for the W5 Review Agent — the seam between Track A and Track B.

This module is *interface only*: enums, Pydantic DTOs, query objects, and the
``ReviewStore`` Protocol. It contains no logic, no SQL, and no FastAPI routing.

Two stores implement ``ReviewStore`` against the same DTOs:

* ``review_api.fake_store.FakeReviewStore`` (Track B) — in-memory, seeded from the
  committed ``data/snapshots/w04/`` files; the dev backend and test backbone.
* ``pipeline.review_store.PostgresReviewStore`` (Track A) — the live-DB twin.

Because both satisfy this contract, the FastAPI app is written once against
``ReviewStore`` and the concrete store is swapped by configuration. The contract
is frozen after the Monday handshake; changes require a ``contract``-labelled PR
with both tracks' sign-off.

DTO field names map directly onto the W4 snapshot columns (see
``data/snapshots/w04/README.md``). Existing pipeline enums are reused rather than
redefined: ``DiscrepancyCategory``, ``NormalizationStatus``,
``RelationshipRefType``, and ``EquipmentType`` come from ``pipeline.models``.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, model_validator

from pipeline.models import (
    DiscrepancyCategory,
    NormalizationStatus,
    RelationshipRefType,
)

__all__ = [
    # enums
    "ItemType",
    "ActionType",
    "SessionStatus",
    "EquipmentSort",
    "DiscrepancyGroupBy",
    "SeverityHint",
    "DiscrepancyStatus",
    "EvidenceSource",
    # equipment DTOs
    "EquipmentEvidence",
    "EquipmentReviewItem",
    # relationship DTOs
    "GraphFinding",
    "RelationshipReviewItem",
    "RelationshipView",
    # discrepancy DTOs
    "DiscrepancyReviewItem",
    "DiscrepancyView",
    # zone DTO
    "ZoneReviewItem",
    # session / action DTOs
    "SessionState",
    "ActionRequest",
    "ActionResult",
    "CommitResult",
    # query objects
    "EquipmentQuery",
    "RelationshipQuery",
    "DiscrepancyQuery",
    "ZoneQuery",
    # protocol
    "ReviewStore",
]


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class ItemType(str, Enum):
    """The kind of review item an action targets."""

    EQUIPMENT = "equipment"
    RELATIONSHIP = "relationship"
    DISCREPANCY = "discrepancy"
    ZONE = "zone"
    POINT = "point"


class ActionType(str, Enum):
    """Reviewer decision on a single item."""

    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class SessionStatus(str, Enum):
    """Lifecycle of a review sitting."""

    OPEN = "open"
    COMMITTED = "committed"
    ABANDONED = "abandoned"


class EquipmentSort(str, Enum):
    """Server-side sort orders for the equipment list.

    ``confidence_asc`` is the default: lowest-confidence (and unscored) items
    surface first so the reviewer triages the riskiest extractions before the
    settled ones.
    """

    CONFIDENCE_ASC = "confidence_asc"
    CONFIDENCE_DESC = "confidence_desc"
    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"


class DiscrepancyGroupBy(str, Enum):
    """Server-side grouping dimensions for the discrepancy view."""

    FLOOR = "floor"
    EQUIPMENT_TYPE = "equipment_type"
    SEVERITY_HINT = "severity_hint"


class SeverityHint(str, Enum):
    """Review-sort hint, not a final ranking. AHU/plant = high; terminal = medium."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DiscrepancyStatus(str, Enum):
    """Status values emitted by ``pipeline/discrepancy.py``, plus review states.

    The first eight mirror the committed ``discrepancy_report_floor_02.csv``.
    ``resolved_out_of_scope`` is the review-side disposition for the seven
    floor-ambiguous ``_1_`` units: the supervisor ruled (2026-06-22) they are
    Floor 1, logged under the Floor_02 path as a deliberate trap, so they are
    seeded pre-resolved rather than pending.
    """

    MATCHED = "matched"
    MISSING_FROM_DRAWINGS = "missing_from_drawings"
    MISSING_FROM_POINTS = "missing_from_points"
    PARTIAL_COVERAGE = "partial_coverage"
    IDENTIFIER_MISMATCH = "identifier_mismatch"
    TYPE_MISMATCH = "type_mismatch"
    RELATIONSHIP_GAP = "relationship_gap"
    FLOOR_AMBIGUOUS = "floor_ambiguous"
    RESOLVED_OUT_OF_SCOPE = "resolved_out_of_scope"


class EvidenceSource(str, Enum):
    """Which W3 snapshot an evidence occurrence came from."""

    TOPICS = "topics"
    DRAWING = "drawing"


# --------------------------------------------------------------------------- #
# Equipment DTOs
# --------------------------------------------------------------------------- #
class EquipmentEvidence(BaseModel):
    """One source occurrence backing an equipment review item.

    Multiple occurrences (a topics row and a drawing row) strengthen context for
    one physical unit; they never create a second pending item.
    """

    source: EvidenceSource
    raw_label: str
    source_filename: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    topic_count: Optional[int] = Field(default=None, ge=0)


class EquipmentReviewItem(BaseModel):
    """One canonical Floor-02 equipment unit, keyed by canonical identity.

    ``confidence`` is intentionally ``None`` ("Unscored"): the only confidence in
    the W4 data is the drawing extraction's (uncalibrated ~0.99), which we do not
    promote. Prioritisation is via ``review_required`` plus the discrepancy
    ``severity_hint``; a calibrated confidence stage arrives later.
    """

    property_id: str
    floor: str
    canonical_name: str
    canonical_key: str
    # Plain str, not the EquipmentType enum: the W4 data carries variant/misread
    # types (EAVAV, VAV-RH-HW, DAWNV) that the enum deliberately does not cover —
    # collapsing them would hide exactly the extraction errors review must catch.
    equipment_type: str
    discrepancy_category: DiscrepancyCategory
    status: NormalizationStatus
    in_topics: bool
    in_drawings: bool
    review_required: bool
    review_reason: str = ""
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence: List[EquipmentEvidence] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def evidence_count(self) -> int:
        return len(self.evidence)


# --------------------------------------------------------------------------- #
# Relationship DTOs
# --------------------------------------------------------------------------- #
class GraphFinding(BaseModel):
    """A graph-validator finding: an error, an orphan, or a review item."""

    check_id: str
    severity: str
    message: str
    nodes: List[str] = Field(default_factory=list)


class RelationshipReviewItem(BaseModel):
    """One inferred equipment-to-equipment edge (``child`` served by ``parent``)."""

    child: str
    parent: str
    ref_type: RelationshipRefType
    confidence: float = Field(..., ge=0.0, le=1.0)
    conflict: bool = False
    conflict_reason: str = ""
    review_required: bool = False
    source_drawing: Optional[str] = None


class RelationshipView(BaseModel):
    """The relationships review view.

    Must render the *current* empty edge set correctly (0 edges / 50 orphans /
    passed=true) and fill in automatically once the deferred tiling pass produces
    edges — no contract change needed.
    """

    edges: List[RelationshipReviewItem] = Field(default_factory=list)
    orphans: List[GraphFinding] = Field(default_factory=list)
    errors: List[GraphFinding] = Field(default_factory=list)
    review_items: List[GraphFinding] = Field(default_factory=list)
    passed: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def orphan_count(self) -> int:
        return len(self.orphans)


# --------------------------------------------------------------------------- #
# Discrepancy DTOs
# --------------------------------------------------------------------------- #
class DiscrepancyReviewItem(BaseModel):
    """One row of the brief-mandated gap report.

    Keyed by ``(building, floor, equipment_type, equipment_id)``. ``resolved_floor``
    is populated only for the pre-resolved floor-ambiguous units (``"1"``).
    """

    building: str
    floor: str
    equipment_type: str
    equipment_id: str
    in_points: bool
    in_drawings: bool
    status: DiscrepancyStatus
    evidence_point: str = ""
    evidence_drawing: str = ""
    severity_hint: SeverityHint
    resolved_floor: Optional[str] = None


class DiscrepancyView(BaseModel):
    """Server-side grouped/rolled-up discrepancy view (frontend stays thin in W6)."""

    items: List[DiscrepancyReviewItem] = Field(default_factory=list)
    group_by: Optional[DiscrepancyGroupBy] = None
    groups: Dict[str, List[DiscrepancyReviewItem]] = Field(default_factory=dict)
    counts: Dict[str, int] = Field(default_factory=dict)
    rollups: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Zone DTO (empty until W7)
# --------------------------------------------------------------------------- #
class ZoneReviewItem(BaseModel):
    """Placeholder zone review item; zone/orientation data arrives in W7."""

    zone_id: str
    floor: str
    orientation: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    review_required: bool = False


# --------------------------------------------------------------------------- #
# Session / action DTOs
# --------------------------------------------------------------------------- #
class SessionState(BaseModel):
    """State of one engineer review sitting."""

    session_id: UUID
    property_id: UUID
    floor: str
    status: SessionStatus = SessionStatus.OPEN
    reviewer: Optional[str] = None
    n_pending: int = Field(default=0, ge=0)
    n_approved: int = Field(default=0, ge=0)
    n_rejected: int = Field(default=0, ge=0)
    created_at: datetime
    committed_at: Optional[datetime] = None


class ActionRequest(BaseModel):
    """A single approve/edit/reject decision.

    Enforces the agreed semantics so endpoints can rely on validation:
    ``approve`` carries no payload and no reason; ``edit`` carries the changed
    fields as ``payload`` plus a ``reason``; ``reject`` carries a ``reason`` and
    no payload.
    """

    item_type: ItemType
    item_key: str
    action: ActionType
    payload: Optional[Dict[str, object]] = None
    reason: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def action_semantics_must_hold(self) -> "ActionRequest":
        if not self.item_key or not self.item_key.strip():
            raise ValueError("item_key must not be blank")
        if self.action == ActionType.APPROVE:
            if self.payload is not None:
                raise ValueError("approve must not carry a payload")
        elif self.action == ActionType.EDIT:
            if not self.payload:
                raise ValueError("edit requires a non-empty payload of changed fields")
            if not self.reason or not self.reason.strip():
                raise ValueError("edit requires a reason")
        elif self.action == ActionType.REJECT:
            if self.payload is not None:
                raise ValueError("reject must not carry a payload")
            if not self.reason or not self.reason.strip():
                raise ValueError("reject requires a reason")
        return self


class ActionResult(BaseModel):
    """Acknowledgement that a decision was recorded against a session."""

    action_id: UUID
    session_id: UUID
    item_type: ItemType
    item_key: str
    action: ActionType
    accepted: bool = True


class CommitResult(BaseModel):
    """Outcome of an atomic session commit.

    ``n_production_rows`` approve/edit actions flushed to production tables;
    ``n_correction_rows`` reject/edit actions written to ``correction_log``.
    """

    session_id: UUID
    status: SessionStatus
    n_approved: int = Field(default=0, ge=0)
    n_rejected: int = Field(default=0, ge=0)
    n_production_rows: int = Field(default=0, ge=0)
    n_correction_rows: int = Field(default=0, ge=0)
    committed_at: Optional[datetime] = None


# --------------------------------------------------------------------------- #
# Query objects
# --------------------------------------------------------------------------- #
class EquipmentQuery(BaseModel):
    """Filters/sort for ``list_equipment`` (default: lowest-confidence first)."""

    sort: EquipmentSort = EquipmentSort.CONFIDENCE_ASC
    status: Optional[NormalizationStatus] = None
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    review_required: Optional[bool] = None


class RelationshipQuery(BaseModel):
    """Filters for ``list_relationships``."""

    include_orphans: bool = True
    include_errors: bool = True
    ref_type: Optional[RelationshipRefType] = None


class DiscrepancyQuery(BaseModel):
    """Grouping/filters for ``list_discrepancies`` (computed server-side)."""

    group_by: Optional[DiscrepancyGroupBy] = None
    severity: Optional[SeverityHint] = None
    status: Optional[DiscrepancyStatus] = None


class ZoneQuery(BaseModel):
    """Filters for ``list_zones`` (returns ``[]`` until W7)."""

    floor: Optional[str] = None


# --------------------------------------------------------------------------- #
# The seam
# --------------------------------------------------------------------------- #
@runtime_checkable
class ReviewStore(Protocol):
    """Storage interface the FastAPI app is written against.

    Read methods load the W4 review inbox; write methods drive the session
    lifecycle. ``commit_session`` is the only path to production tables and is
    atomic in the Postgres implementation.
    """

    # ---- read path (Track B builds endpoints on these) ----
    def list_equipment(self, query: EquipmentQuery) -> List[EquipmentReviewItem]: ...

    def list_relationships(self, query: RelationshipQuery) -> RelationshipView: ...

    def list_discrepancies(self, query: DiscrepancyQuery) -> DiscrepancyView: ...

    def list_zones(self, query: ZoneQuery) -> List[ZoneReviewItem]: ...

    def get_session(self, session_id: UUID) -> SessionState: ...

    # ---- write path (Track A owns the real impl; Track B calls via HTTP) ----
    def open_session(
        self, property_id: UUID, floor: str, reviewer: Optional[str] = None
    ) -> SessionState: ...

    def record_action(self, session_id: UUID, request: ActionRequest) -> ActionResult: ...

    def commit_session(self, session_id: UUID) -> CommitResult: ...
