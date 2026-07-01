// View models OWNED by the frontend.
//
// These describe what each W6 review view needs to *display* — deliberately NOT
// a mirror of the backend `review_api/contracts.py` DTOs (which are still being
// reconciled in the A->B merge). The single seam that knows about the backend
// shape is `src/api/adapter.ts`; everything else in the UI speaks these types.
// When the contract lands, only the adapter changes.

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
}

export interface ZoneVM {
  key: string; // zone_id
  floor: string;
  orientation: string | null; // N/E/S/W/... null until classified (W7 fills these)
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
  sourceDrawing: string | null;
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
