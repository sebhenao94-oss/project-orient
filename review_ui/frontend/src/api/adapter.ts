// The ONLY backend-aware module in the UI.
//
// Maps raw `review_api` JSON -> frontend view models. When the A->B contract
// merge lands, reconcile field names here and nowhere else.

import type {
  RawDiscrepancy,
  RawEquipment,
  RawGraphFinding,
  RawRelationshipEdge,
  RawRelationshipView,
  RawSession,
  RawZone,
} from "./raw";
import type {
  DiscrepancyVM,
  EquipmentVM,
  GraphFindingVM,
  RelationshipEdgeVM,
  RelationshipsVM,
  SessionVM,
  Severity,
  ZoneVM,
} from "../types/viewModels";

function asSeverity(value: string | undefined): Severity {
  return value === "high" || value === "medium" || value === "low" ? value : "low";
}

export function toEquipmentVM(r: RawEquipment): EquipmentVM {
  const key = r.canonical_name ?? "";
  return {
    key,
    name: r.canonical_name ?? key,
    equipmentType: r.equipment_type ?? "UNKNOWN",
    floor: r.floor ?? "",
    confidence: r.confidence ?? null,
    reviewRequired: r.review_required ?? false,
    reviewReason: r.review_reason ?? null,
    status: r.status ?? "",
    discrepancyCategory: r.discrepancy_category ?? "",
    inTopics: r.in_topics ?? false,
    inDrawings: r.in_drawings ?? false,
  };
}

export function toZoneVM(r: RawZone): ZoneVM {
  return {
    key: r.zone_id ?? "",
    floor: r.floor ?? "",
    orientation: r.orientation ?? null,
    confidence: r.confidence ?? null,
    reviewRequired: r.review_required ?? true,
  };
}

export function toDiscrepancyVM(r: RawDiscrepancy): DiscrepancyVM {
  const building = r.building ?? "";
  const floor = r.floor ?? "";
  const equipmentType = r.equipment_type ?? "";
  const equipmentId = r.equipment_id ?? "";
  return {
    key: `${building}|${floor}|${equipmentType}|${equipmentId}`,
    building,
    floor,
    equipmentType,
    equipmentId,
    inPoints: r.in_points ?? false,
    inDrawings: r.in_drawings ?? false,
    status: r.status ?? "",
    severity: asSeverity(r.severity_hint),
    evidencePoint: r.evidence_point ?? null,
    evidenceDrawing: r.evidence_drawing ?? null,
    resolvedFloor: r.resolved_floor ?? null,
  };
}

function toFindingVM(r: RawGraphFinding): GraphFindingVM {
  return {
    checkId: r.check_id ?? "",
    severity: r.severity ?? "",
    message: r.message ?? "",
    nodes: r.nodes ?? [],
  };
}

export function toRelationshipEdgeVM(r: RawRelationshipEdge): RelationshipEdgeVM {
  const child = r.child ?? "";
  const parent = r.parent ?? "";
  const refType = r.ref_type ?? "";
  return {
    key: `${child}|${refType}|${parent}`,
    child,
    parent,
    refType,
    confidence: r.confidence ?? null,
    conflict: r.conflict ?? false,
    conflictReason: r.conflict_reason ?? null,
    sourceDrawing: r.source_drawing ?? null,
  };
}

export function toRelationshipsVM(r: RawRelationshipView): RelationshipsVM {
  return {
    edges: (r.edges ?? []).map(toRelationshipEdgeVM),
    orphans: (r.orphans ?? []).map(toFindingVM),
    errors: (r.errors ?? []).map(toFindingVM),
    reviewItems: (r.review_items ?? []).map(toFindingVM),
    passed: r.passed ?? true,
  };
}

export function toSessionVM(r: RawSession): SessionVM {
  const status = r.status === "committed" || r.status === "abandoned" ? r.status : "open";
  return {
    sessionId: r.session_id ?? "",
    propertyId: r.property_id ?? "",
    floor: r.floor ?? "",
    status,
    nPending: r.n_pending ?? 0,
    nApproved: r.n_approved ?? 0,
    nRejected: r.n_rejected ?? 0,
  };
}
