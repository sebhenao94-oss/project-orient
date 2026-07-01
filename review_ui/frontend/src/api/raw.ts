// Loose, tolerant types for the raw JSON the backend returns.
//
// These intentionally mark most fields optional/unknown: the contract
// (`review_api/contracts.py`) is being reconciled in the A->B merge, so the
// adapter must not assume exact presence. Tighten these once the merge lands.

export interface RawEquipment {
  canonical_name?: string;
  canonical_key?: string;
  equipment_type?: string;
  raw_equipment_type?: string | null;
  floor?: string;
  confidence?: number | null;
  review_required?: boolean;
  review_reason?: string | null;
  status?: string;
  discrepancy_category?: string;
  in_topics?: boolean;
  in_drawings?: boolean;
}

export interface RawZone {
  zone_id?: string;
  floor?: string;
  orientation?: string | null;
  confidence?: number | null;
  review_required?: boolean;
}

export interface RawDiscrepancy {
  building?: string;
  floor?: string;
  equipment_type?: string;
  equipment_id?: string;
  in_points?: boolean;
  in_drawings?: boolean;
  status?: string;
  severity_hint?: string;
  evidence_point?: string | null;
  evidence_drawing?: string | null;
  resolved_floor?: string | null;
}

export interface RawGraphFinding {
  check_id?: string;
  severity?: string;
  message?: string;
  nodes?: string[];
}

export interface RawRelationshipEdge {
  child?: string;
  parent?: string;
  ref_type?: string;
  confidence?: number | null;
  conflict?: boolean;
  conflict_reason?: string | null;
  source_drawing?: string | null;
}

export interface RawRelationshipView {
  edges?: RawRelationshipEdge[];
  orphans?: RawGraphFinding[];
  errors?: RawGraphFinding[];
  review_items?: RawGraphFinding[];
  passed?: boolean;
}

export interface RawSession {
  session_id?: string;
  property_id?: string;
  floor?: string;
  status?: string;
  n_pending?: number;
  n_approved?: number;
  n_rejected?: number;
}
