// Controlled vocabularies for the structured edit fields.
//
// PROVISIONAL frontend copies so the edit dropdowns are usable in mock mode.
// The authoritative sources are backend-side (`equipments_point_types/` for
// types, the supervisor's essential tag list for points); swap these for a
// backend-served enum at contract convergence.

export const EQUIPMENT_TYPES = [
  "AHU",
  "DOAS",
  "MAU",
  "FCU",
  "VAV",
  "VAV-RH-HW",
  "VAV-RH-ELEC",
  "FPTU-HW",
  "FPTU-ELEC",
  "CHW-PLANT",
  "HW-PLANT",
  "COND-PLANT",
  "VENTILATION",
  "ERV",
] as const;

export const ORIENTATIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "unclassified"] as const;

export const REF_TYPES = [
  "airRef",
  "hotWaterRef",
  "chilledWaterRef",
  "condenserWaterRef",
  "spaceRef",
] as const;

export const DISCREPANCY_STATUSES = [
  "matched",
  "missing_from_drawings",
  "missing_from_points",
  "partial_coverage",
  "identifier_mismatch",
  "type_mismatch",
  "relationship_gap",
  "floor_ambiguous",
  "resolved_out_of_scope",
] as const;

export const SEVERITIES = ["high", "medium", "low"] as const;
