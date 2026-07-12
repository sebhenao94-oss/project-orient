// Raw-shaped fixture data for isolated frontend checks only.
//
// The acceptance path is the local API with REVIEW_STORE=fake or postgres. These
// fixtures intentionally stay small and must not be treated as W6 evidence.

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
    canonical_name: "AHU_2-A", equipment_type: "AHU",
    raw_equipment_type: "AHU", floor: FLOOR, confidence: 0.92, review_required: true,
    review_reason: "floor digit inferred from inline token '02A'",
    status: "settled", discrepancy_category: "matched", in_topics: true, in_drawings: true,
    source_files: ["AHU_02A.png", "VAV_2_05.png"],
  },
  {
    canonical_name: "AHU_2-B", equipment_type: "AHU",
    raw_equipment_type: "AHU", floor: FLOOR, confidence: 0.58, review_required: true,
    review_reason: "present in BMS topics but absent from drawing evidence",
    status: "review_required", discrepancy_category: "topics_only", in_topics: true, in_drawings: false,
  },
  {
    canonical_name: "AHU_2-C", equipment_type: "AHU",
    raw_equipment_type: "AHU", floor: FLOOR, confidence: 0.9, review_required: true,
    review_reason: "floor digit inferred from inline token '02C'",
    status: "settled", discrepancy_category: "matched", in_topics: true, in_drawings: true,
    source_files: ["ahu_02c.png", "ahu_02c_2.png"],
  },
  {
    canonical_name: "AHU_2-01", equipment_type: "AHU",
    raw_equipment_type: "AHU", floor: FLOOR, confidence: 0.71, review_required: true,
    review_reason: "present in BMS topics but absent from drawing evidence",
    status: "review_required", discrepancy_category: "topics_only", in_topics: true, in_drawings: false,
  },
  {
    canonical_name: "AHU_2-02", equipment_type: "AHU",
    raw_equipment_type: "AHU", floor: FLOOR, confidence: 0.69, review_required: true,
    review_reason: "present in BMS topics but absent from drawing evidence",
    status: "review_required", discrepancy_category: "topics_only", in_topics: true, in_drawings: false,
  },
  {
    canonical_name: "DAWNV_2_9", equipment_type: "VAV",
    raw_equipment_type: "DAWNV", floor: FLOOR, confidence: 0.63, review_required: true,
    review_reason: "present in drawing evidence but absent from BMS topics",
    status: "review_required", discrepancy_category: "drawings_only", in_topics: false, in_drawings: true,
  },
  {
    canonical_name: "VAV-RH-HW_2-01", equipment_type: "VAV",
    raw_equipment_type: "VAVRH", floor: FLOOR, confidence: 0.34, review_required: true,
    review_reason: "subtype (HW vs ELEC reheat) unresolved from catalog",
    status: "review_required", discrepancy_category: "topics_only", in_topics: true, in_drawings: false,
  },
  {
    canonical_name: "FCU_2-01", equipment_type: "FCU",
    raw_equipment_type: "FCU", floor: FLOOR, confidence: 0.81, review_required: false,
    review_reason: null, status: "settled", discrepancy_category: "matched",
    in_topics: true, in_drawings: true,
  },
];

export const mockDiscrepancies: RawDiscrepancy[] = [
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "AHU", equipment_id: "AHU_2-A", in_points: true, in_drawings: true, status: "matched", evidence_point: "AHU-02A", evidence_drawing: "AHU 02 A", severity_hint: "low" },
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "AHU", equipment_id: "AHU_2-B", in_points: true, in_drawings: false, status: "missing_from_drawings", evidence_point: "AHU-02B", evidence_drawing: null, severity_hint: "high" },
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "AHU", equipment_id: "AHU_2-01", in_points: true, in_drawings: false, status: "missing_from_drawings", evidence_point: "AHU_2-01", evidence_drawing: null, severity_hint: "high" },
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "AHU", equipment_id: "AHU_2-02", in_points: true, in_drawings: false, status: "missing_from_drawings", evidence_point: "AHU_2_02", evidence_drawing: null, severity_hint: "high" },
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "VAV", equipment_id: "DAWNV_2_9", in_points: false, in_drawings: true, status: "missing_from_points", evidence_point: null, evidence_drawing: "DAWNV_2_09", severity_hint: "medium" },
  { building: "msa_orient_building_1", floor: FLOOR, equipment_type: "EAVAV", equipment_id: "EAVAV_1_1", in_points: true, in_drawings: false, status: "floor_ambiguous", evidence_point: "EAVAV_1_01", evidence_drawing: null, severity_hint: "medium", resolved_floor: "1" },
];

// Small isolated fixture; the W6 acceptance relationship view comes from the API.
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

// No placeholder rows: the zone surface is explicitly empty for W0-W6.
export const mockZones: RawZone[] = [];
