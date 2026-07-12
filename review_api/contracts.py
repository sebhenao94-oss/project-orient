"""W5 review-agent contracts (PROVISIONAL — Track A draft).

This is the co-owned seam between Track A (PostgresReviewStore on Postgres) and
Track B (FastAPI endpoints + FakeReviewStore). It defines the ``ReviewStore``
Protocol plus the request/response DTOs and query objects.

PROVISIONAL: drafted by Track A so A3/A4 can proceed before the Monday contracts
handshake. It must be reconciled with the teammate's B1 contracts PR via a single
``contract``-labelled PR; treat any change here as a contract change needing both
sign-offs. The equipment/relationship/discrepancy enums are reused from
``pipeline/models.py`` rather than redefined.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

try:  # works whether imported as review_api.contracts or with pipeline/ on sys.path
    from pipeline.models import (
        DiscrepancyCategory,
        NormalizationStatus,
        RelationshipRefType,
    )
except ModuleNotFoundError:  # pragma: no cover - bare-import fallback (tests)
    from models import (  # type: ignore
        DiscrepancyCategory,
        NormalizationStatus,
        RelationshipRefType,
    )

__all__ = [
    "ItemType",
    "ActionType",
    "SessionStatus",
    "EquipmentSort",
    "DiscrepancyGroupBy",
    "SeverityHint",
    "DiscrepancyStatus",
    "EvidenceSource",
    "EquipmentEvidence",
    "GraphFinding",
    "EquipmentReviewItem",
    "RelationshipReviewItem",
    "RelationshipView",
    "DiscrepancyReviewItem",
    "DiscrepancyView",
    "ZoneReviewItem",
    "SessionState",
    "ActionRequest",
    "ActionResult",
    "CommitResult",
    "EquipmentQuery",
    "RelationshipQuery",
    "DiscrepancyQuery",
    "ZoneQuery",
    "ReviewStore",
    "DiscrepancyCategory",
    "NormalizationStatus",
    "RelationshipRefType",
]


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class ItemType(str, Enum):
    EQUIPMENT = "equipment"
    RELATIONSHIP = "relationship"
    DISCREPANCY = "discrepancy"
    ZONE = "zone"
    POINT = "point"


class ActionType(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class SessionStatus(str, Enum):
    OPEN = "open"
    COMMITTED = "committed"
    ABANDONED = "abandoned"


class EquipmentSort(str, Enum):
    # Default is confidence-ascending so low-confidence items sort to the top.
    CONFIDENCE_ASC = "confidence_asc"
    CONFIDENCE_DESC = "confidence_desc"
    NAME = "name"


class DiscrepancyGroupBy(str, Enum):
    FLOOR = "floor"
    EQUIPMENT_TYPE = "equipment_type"
    SEVERITY_HINT = "severity_hint"


class SeverityHint(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DiscrepancyStatus(str, Enum):
    """Status values in the W4 discrepancy report, plus the Floor-1 resolution.

    ``resolved_out_of_scope`` carries the supervisor's June-22 ruling that the 7
    ``_1_`` ventilation units are Floor 1 logged under the Floor_02 path as a
    deliberate trap: they are pre-resolved, not pending review.
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
    TOPICS = "topics"
    DRAWING = "drawing"


# --------------------------------------------------------------------------- #
# Read-side DTOs
# --------------------------------------------------------------------------- #
class EquipmentEvidence(BaseModel):
    """One source occurrence supporting a canonical equipment review item."""

    source: EvidenceSource
    raw_label: str
    source_filename: Optional[str] = None
    source_relative_path: Optional[str] = None
    source_sha256: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_strength: Optional[str] = None
    topic_count: Optional[int] = Field(default=None, ge=0)


class EquipmentReviewItem(BaseModel):
    property_id: Optional[str] = None
    floor: str
    canonical_name: str  # single public identity (Sourav #1); dedup key kept internal
    equipment_type: str
    raw_equipment_type: Optional[str] = None
    discrepancy_category: DiscrepancyCategory
    status: NormalizationStatus
    in_topics: bool
    in_drawings: bool
    topics_raw_label: Optional[str] = None
    drawing_raw_label: Optional[str] = None
    confidence: Optional[float] = None
    review_required: bool
    review_reason: Optional[str] = None
    evidence: List[EquipmentEvidence] = Field(default_factory=list)

    @property
    def evidence_count(self) -> int:
        return len(self.evidence)


class RelationshipReviewItem(BaseModel):
    child: str
    parent: str
    ref_type: RelationshipRefType
    confidence: Optional[float] = None
    conflict: bool = False
    conflict_reason: Optional[str] = None
    source_drawing: Optional[str] = None
    source_sha256: Optional[str] = None
    review_required: bool = False
    review_reason: Optional[str] = None


class GraphFinding(BaseModel):
    """One graph-validator finding (orphan / error / review item)."""

    check_id: str
    severity: str
    message: str
    nodes: List[str] = Field(default_factory=list)


class RelationshipView(BaseModel):
    """Relationship review payload — renders the empty set AND populated edges."""

    edges: List[RelationshipReviewItem] = Field(default_factory=list)
    orphans: List[GraphFinding] = Field(default_factory=list)
    errors: List[GraphFinding] = Field(default_factory=list)
    review_items: List[GraphFinding] = Field(default_factory=list)
    passed: bool = True

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def orphan_count(self) -> int:
        return len(self.orphans)


class DiscrepancyReviewItem(BaseModel):
    building: str
    floor: str
    equipment_type: str
    equipment_id: str
    in_points: bool
    in_drawings: bool
    status: DiscrepancyStatus
    evidence_point: Optional[str] = None
    evidence_drawing: Optional[str] = None
    severity_hint: SeverityHint
    resolved_floor: Optional[str] = None  # e.g. "1" for the Floor-1 trap units


class DiscrepancyView(BaseModel):
    items: List[DiscrepancyReviewItem] = Field(default_factory=list)
    group_by: Optional[DiscrepancyGroupBy] = None
    groups: Optional[Dict[str, List[DiscrepancyReviewItem]]] = None
    counts: Dict[str, int] = Field(default_factory=dict)
    rollups: List[str] = Field(default_factory=list)  # e.g. "Floor 2: 4 AHUs missing from drawings"


class ZoneReviewItem(BaseModel):
    zone_id: str
    floor: str
    orientation: Optional[str] = None
    confidence: Optional[float] = None
    review_required: bool = True


# --------------------------------------------------------------------------- #
# Session / write-side DTOs
# --------------------------------------------------------------------------- #
class SessionState(BaseModel):
    session_id: UUID
    property_id: UUID
    floor: str
    status: SessionStatus = SessionStatus.OPEN
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    committed_at: Optional[datetime] = None
    n_pending: int = 0
    n_approved: int = 0
    n_rejected: int = 0


class ActionRequest(BaseModel):
    item_type: ItemType
    item_key: str
    action: ActionType
    payload: Optional[Dict[str, object]] = None
    confidence: Optional[float] = None
    reviewer: Optional[str] = None
    reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_action_payload(self):
        """Enforce the approved review semantics at the shared contract seam."""
        if self.reason is not None:
            self.reason = self.reason.strip() or None

        if self.action == ActionType.APPROVE:
            if self.payload is not None:
                raise ValueError("approve accepts the original item unchanged; payload must be null")
            return self

        if self.action == ActionType.EDIT:
            if not self.payload:
                raise ValueError("edit requires at least one changed field in payload")
            if self.reason is None:
                raise ValueError("edit requires a reason")
            return self

        if self.payload is not None:
            raise ValueError("reject has no corrected value; payload must be null")
        if self.reason is None:
            raise ValueError("reject requires a reason")
        return self


class ActionResult(BaseModel):
    action_id: UUID
    session_id: UUID
    item_type: ItemType
    item_key: str
    action: ActionType
    applied: bool = False
    session_state: SessionState


class CommitResult(BaseModel):
    session_id: UUID
    committed: bool
    n_committed: int = 0      # rows written to production tables
    n_corrections: int = 0    # rows written to correction_log
    committed_at: Optional[datetime] = None
    errors: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Query objects
# --------------------------------------------------------------------------- #
class EquipmentQuery(BaseModel):
    property_id: Optional[str] = None
    floor: Optional[str] = None
    sort: EquipmentSort = EquipmentSort.CONFIDENCE_ASC
    status: Optional[NormalizationStatus] = None
    min_confidence: Optional[float] = None
    review_required: Optional[bool] = None


class RelationshipQuery(BaseModel):
    property_id: Optional[str] = None
    floor: Optional[str] = None


class DiscrepancyQuery(BaseModel):
    property_id: Optional[str] = None
    floor: Optional[str] = None
    group_by: Optional[DiscrepancyGroupBy] = None
    severity: Optional[SeverityHint] = None
    status: Optional[DiscrepancyStatus] = None


class ZoneQuery(BaseModel):
    property_id: Optional[str] = None
    floor: Optional[str] = None


# --------------------------------------------------------------------------- #
# The store interface
# --------------------------------------------------------------------------- #
@runtime_checkable
class ReviewStore(Protocol):
    """Backend the review API runs on. Track A: Postgres; Track B: a fake store."""

    # ---- read path ----
    def list_equipment(self, query: EquipmentQuery) -> List[EquipmentReviewItem]: ...

    def list_relationships(self, query: RelationshipQuery) -> RelationshipView: ...

    def list_discrepancies(self, query: DiscrepancyQuery) -> DiscrepancyView: ...

    def list_zones(self, query: ZoneQuery) -> List[ZoneReviewItem]: ...

    def get_session(self, session_id: UUID) -> SessionState: ...

    # ---- write path (real impl is Track A's PostgresReviewStore) ----
    def open_session(
        self, property_id: UUID, floor: str, reviewer: Optional[str] = None
    ) -> SessionState: ...

    def record_action(self, session_id: UUID, request: ActionRequest) -> ActionResult: ...

    def clear_action(
        self, session_id: UUID, item_type: ItemType, item_key: str
    ) -> SessionState: ...

    def clear_all_actions(self, session_id: UUID) -> SessionState: ...

    def commit_session(self, session_id: UUID) -> CommitResult: ...
