// Raw-shaped mock data so the UI renders with no backend running.
//
// Mirrors the committed W4 snapshots (data/snapshots/w04/*) so the mock path and
// the real path exercise the same adapter. Two deliberate liberties, both for
// demo only and called out here:
//   * `confidence` values are synthesised (the W4 equipment CSV carries none yet)
//     so the confidence-ascending sort and low-confidence flag are visible.
//   * `zones` are illustrative — real zone data is produced in W7.

import type {
  RawDiscrepancy,
  RawEquipment,
  RawRelationshipView,
  RawZone,
} from "./raw";

export const FLOOR = "Floor_02";
export const PROPERTY_ID = "b470b97b-4ea7-481c-97b7-22a81a219587";

export const mockEquipment: RawEquipment[] = [
  {
    canonical_name: "AHU_2-A", canonical_key: "AHU_02A", equipment_type: "AHU",
    raw_equipment_type: "AHU", floor: FLOOR, confidence: 0.92, review_required: true,
    review_reason: "floor digit inferred from inline token '02A'",
    status: "settled", discrepancy_category: "matched", in_topics: true, in_drawings: true,
  },
  {
    canonical_name: "AHU_2-B", canonical_key: "AHU_02B", equipment_type: "AHU",
    raw_equipment_type: "AHU", floor: FLOOR, confidence: 0.58, review_required: true,
    review_reason: "present in BMS topics but absent from drawing evidence",
    status: "review_required", discrepancy_category: "topics_only", in_topics: true, in_drawings: false,
  },
  {
    canonical_name: "AHU_2-C", canonical_key: "AHU_02C", equipment_type: "AHU",
    raw_equipment_type: "AHU", floor: FLOOR, confidence: 0.9, review_required: true,
    review_reason: "floor digit inferred from inline token '02C'",
    status: "settled", discrepancy_category: "matched", in_topics: true, in_drawings: true,
  },
  {
    canonical_name: "AHU_2-1", canonical_key: "AHU_2_1", equipment_type: "AHU",
    raw_equipment_type: "AHU", floor: FLOOR, confidence: 0.71, review_required: true,
    review_reason: "present in BMS topics but absent from drawing evidence",
    status: "review_required", discrepancy_category: "topics_only", in_topics: true, in_drawings: false,
  },
  {
    canonical_name: "VAVRH_2-1", canonical_key: "VAVRH_2_1", equipment_type: "VAV",
    raw_equipment_type: "VAVRH", floor: FLOOR, confidence: 0.34, review_required: true,
    review_reason: "subtype (HW vs ELEC reheat) unresolved from catalog",
    status: "review_required", discrepancy_category: "topics_only", in_topics: true, in_drawings: false,
  },
  {
    canonical_name: "FCU_2-1", canonical_key: "FCU_2_1", equipment_type: "FCU",
    raw_equipment_type: "FCU", floor: FLOOR, confidence: 0.81, review_required: false,
    review_reason: null, status: "settled", discrepancy_category: "matched",
    in_topics: true, in_drawings: true,
  },
];

export const mockDiscrepancies: RawDiscrepancy[] = [
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "AHU", equipment_id: "AHU_2-A", in_points: true, in_drawings: true, status: "matched", evidence_point: "AHU-02A", evidence_drawing: "AHU 02 A", severity_hint: "low" },
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "AHU", equipment_id: "AHU_2-B", in_points: true, in_drawings: false, status: "missing_from_drawings", evidence_point: "AHU-02B", evidence_drawing: null, severity_hint: "high" },
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "AHU", equipment_id: "AHU_2-1", in_points: true, in_drawings: false, status: "missing_from_drawings", evidence_point: "AHU_2_01", evidence_drawing: null, severity_hint: "high" },
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "AHU", equipment_id: "AHU_2-2", in_points: true, in_drawings: false, status: "missing_from_drawings", evidence_point: "AHU_2_02", evidence_drawing: null, severity_hint: "high" },
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "VAV", equipment_id: "DAWNV_2_9", in_points: false, in_drawings: true, status: "missing_from_points", evidence_point: null, evidence_drawing: "DAWNV_2_09", severity_hint: "medium" },
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "EAVAV", equipment_id: "EAVAV_1_1", in_points: true, in_drawings: false, status: "floor_ambiguous", evidence_point: "EAVAV_1_01", evidence_drawing: null, severity_hint: "medium", resolved_floor: "1" },
];

// W4 documented 0 serving relationships; the value of this view at W4 is the
// orphan list (terminals with no airRef parent) the graph validator emits.
export const mockRelationships: RawRelationshipView = {
  edges: [],
  orphans: [
    { check_id: "orphan_terminal", severity: "orphan", message: "terminal 'DAWNV_2_9' (VAV) has no airRef parent", nodes: ["DAWNV_2_9"] },
    { check_id: "orphan_terminal", severity: "orphan", message: "terminal 'EAVAV_1_1' (EAVAV) has no airRef parent", nodes: ["EAVAV_1_1"] },
    { check_id: "orphan_terminal", severity: "orphan", message: "terminal 'VAVRH_2_1' (VAV) has no airRef parent", nodes: ["VAVRH_2_1"] },
  ],
  errors: [],
  review_items: [],
  passed: true,
};

// Illustrative only — real zone orientation is a W7 deliverable.
export const mockZones: RawZone[] = [
  { zone_id: "Z-2-01", floor: FLOOR, orientation: null, confidence: null, review_required: true },
  { zone_id: "Z-2-02", floor: FLOOR, orientation: "N", confidence: 0.44, review_required: true },
  { zone_id: "Z-2-03", floor: FLOOR, orientation: "SE", confidence: 0.86, review_required: false },
];
