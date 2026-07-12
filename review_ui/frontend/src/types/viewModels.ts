// View models OWNED by the frontend.
//
// These describe what each W6 review view needs to display and deliberately do
// not mirror the live backend DTOs. `src/api/adapter.ts` is the single seam
// that translates `review_api/contracts.py`; everything else in the UI speaks
// these view types.

/** Client-side decision state for an item within the current review session. */
export type ReviewDecision = "pending" | "approved" | "edited" | "rejected";

export type Severity = "high" | "medium" | "low";

export interface EquipmentVM {
  /** Stable natural key used as the action item_key (the canonical_name). */
  key: string;
  name: string; // canonical_name, e.g. "AHU_2-A"
  equipmentType: string; // "AHU" | "VAV" | "FCU" | ...
  floor: string; // e.g. "Floor_02"
  confidence: number | null; // 0..1, null when the pipeline emitted none
  reviewRequired: boolean;
  reviewReason: string | null;
  status: string; // backend normalization status, e.g. "settled" | "review_required"
  discrepancyCategory: string; // "matched" | "topics_only" | ...
  inTopics: boolean;
  inDrawings: boolean;
  topicsRawLabel: string | null; // raw label as seen in BMS topics, e.g. "AHU-02A"
  drawingRawLabel: string | null; // raw label as read from drawings, e.g. "AHU 02 A"
  sourceFiles: string[];
}

export interface ZoneVM {
  key: string; // zone_id
  floor: string;
  orientation: string | null; // N/E/S/W/...; null when no classification exists
  confidence: number | null;
  reviewRequired: boolean;
}

export interface DiscrepancyVM {
  key: string; // building|floor|type|id
  building: string;
  floor: string;
  equipmentType: string;
  equipmentId: string;
  inPoints: boolean;
  inDrawings: boolean;
  status: string; // matched | missing_from_drawings | ...
  severity: Severity;
  evidencePoint: string | null;
  evidenceDrawing: string | null;
  resolvedFloor: string | null; // e.g. "1" for the floor-ambiguous trap units
}

export interface RelationshipEdgeVM {
  key: string; // child|refType|parent
  child: string;
  parent: string;
  refType: string; // airRef | hotWaterRef | ...
  confidence: number | null;
  conflict: boolean;
  conflictReason: string | null;
  reviewRequired: boolean;
  reviewReason: string | null;
  sourceDrawing: string | null;
}

/** Durable source value for an engineer-drawn relationship action. */
export interface RelationshipProposalInput {
  child: string;
  parent: string;
  ref_type: string;
}

export interface GraphFindingVM {
  checkId: string;
  severity: string;
  message: string;
  nodes: string[];
}

export interface RelationshipsVM {
  edges: RelationshipEdgeVM[];
  orphans: GraphFindingVM[];
  errors: GraphFindingVM[];
  reviewItems: GraphFindingVM[];
  passed: boolean;
}

export interface SessionVM {
  sessionId: string;
  propertyId: string;
  floor: string;
  status: "open" | "committed" | "abandoned";
  nPending: number;
  nApproved: number;
  nRejected: number;
}

/** The four review surfaces, used for tab routing and action item_type. */
export type ItemType = "equipment" | "relationship" | "discrepancy" | "zone";
