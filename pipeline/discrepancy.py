"""W4 discrepancy report (gap report) for Project ORIENT — the primary W4 deliverable.

This is an additive downstream stage over the Track B normalization output. It
reads the committed ``normalized_equipment_floor_02.csv`` (produced by
``pipeline/normalization.py``) and emits two artifacts:

1. ``canonical_equipment_floor_02.csv`` — the normalised equipment list with the
   team-lead naming convention ``{Type}_{floor}-{unit}`` applied and the type
   mapped onto the current vocabulary (see ``pipeline/equipment_vocab.py``).
   This closes the "naming convention not applied" gap without editing the
   normalization module.
2. ``discrepancy_report_floor_02.csv`` — the brief-mandated gap report, keyed by
   ``(building, floor, equipment_type, equipment_id)`` with the columns
   ``in_points, in_drawings, status, evidence_point, evidence_drawing,
   severity_hint``.

The module is read-only on its inputs, calls no model endpoint, and writes no
database rows. The mandated ``discrepancy_report`` model is defined here (not in
the shared ``pipeline/models.py``) so this layer stays purely additive.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List, Sequence

from pydantic import BaseModel, Field, field_validator

if __package__:
    from .equipment_vocab import PLANT_CONTAINER_KEYS, canonical_name, map_equipment_type
else:
    from equipment_vocab import PLANT_CONTAINER_KEYS, canonical_name, map_equipment_type


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NORMALIZED_SNAPSHOT = (
    PROJECT_ROOT / "data" / "snapshots" / "w04" / "normalized_equipment_floor_02.csv"
)
DEFAULT_CANONICAL_SNAPSHOT = (
    PROJECT_ROOT / "data" / "snapshots" / "w04" / "canonical_equipment_floor_02.csv"
)
DEFAULT_DISCREPANCY_REPORT = (
    PROJECT_ROOT / "data" / "snapshots" / "w04" / "discrepancy_report_floor_02.csv"
)

CANONICAL_EQUIPMENT_HEADERS = (
    "snapshot_version",
    "property_id",
    "property_name",
    "floor",
    "canonical_name",
    "equipment_type",
    "raw_equipment_type",
    "discrepancy_category",
    "status",
    "in_topics",
    "in_drawings",
    "topics_raw_label",
    "drawing_raw_label",
    "review_required",
    "review_reason",
)

DISCREPANCY_REPORT_HEADERS = (
    "building",
    "floor",
    "equipment_type",
    "equipment_id",
    "in_points",
    "in_drawings",
    "status",
    "evidence_point",
    "evidence_drawing",
    "severity_hint",
)

# Track B discrepancy_category -> brief discrepancy_report status.
_CATEGORY_TO_STATUS = {
    "matched": "matched",
    "topics_only": "missing_from_drawings",
    "drawing_only": "missing_from_points",
    "type_mismatch": "type_mismatch",
    "floor_ambiguous": "floor_ambiguous",
}

_HIGH_SEVERITY_TYPES = (
    {"AHU", "DOAS", "MAU"}
    | set(PLANT_CONTAINER_KEYS)
    | {"CHILLER", "BOILER", "COOLING-TOWER", "CHW-PUMP", "COND-PUMP", "HW-PUMP"}
)


class DiscrepancyInputError(ValueError):
    """Raised when the normalized snapshot is missing or malformed."""


class DiscrepancyReportRecord(BaseModel):
    """One brief-mandated discrepancy-report row (kept local to this module)."""

    building: str
    floor: str
    equipment_type: str
    equipment_id: str
    in_points: bool
    in_drawings: bool
    status: str
    evidence_point: str = ""
    evidence_drawing: str = ""
    severity_hint: str

    @field_validator("building", "floor", "equipment_type", "equipment_id", "status", "severity_hint")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("required text fields must not be blank")
        return value

    @field_validator("status")
    @classmethod
    def status_must_be_known(cls, value: str) -> str:
        allowed = {
            "matched",
            "missing_from_drawings",
            "missing_from_points",
            "partial_coverage",
            "identifier_mismatch",
            "type_mismatch",
            "relationship_gap",
            "floor_ambiguous",
        }
        if value not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return value

    @field_validator("severity_hint")
    @classmethod
    def severity_must_be_known(cls, value: str) -> str:
        if value not in {"high", "medium", "low"}:
            raise ValueError("severity_hint must be high, medium, or low")
        return value


def _to_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _severity_for(status: str, mapped_type: str) -> str:
    if status == "matched":
        return "low"
    if status in {"type_mismatch", "identifier_mismatch"}:
        return "low"
    if status == "floor_ambiguous":
        return "medium"
    # Gap cases (missing from one side).
    if mapped_type in _HIGH_SEVERITY_TYPES:
        return "high"
    return "medium"


def load_normalized_rows(csv_path) -> List[Dict[str, str]]:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise DiscrepancyInputError(f"normalized snapshot not found: {csv_path}")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"canonical_key", "equipment_type", "discrepancy_category"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise DiscrepancyInputError(
                f"{csv_path}: missing required column(s): {', '.join(sorted(missing))}"
            )
        return list(reader)


def _canonical_name_for_row(canonical_key: str, raw_type: str, category: str):
    """Best-guess canonical name with safe handling of misreads and contested floors.

    Returns (name, review_required, review_reason). The team-lead convention is
    only asserted when the label clearly matches its inferred type and floor;
    otherwise the unique canonical key is preserved so a misread (e.g. ``DAWNV``,
    ``EVAV``) is never silently renamed to a clean unit and a contested-floor
    unit is never given a confident Floor-2 name.
    """
    type_mapping = map_equipment_type(raw_type)
    mapped_type = type_mapping.mapped_type
    reasons = [type_mapping.review_reason] if type_mapping.review_reason else []

    key_prefix = canonical_key.split("_")[0].upper() if canonical_key else ""
    raw_prefix = (raw_type or "").upper()

    if category == "floor_ambiguous":
        return canonical_key, True, "; ".join(reasons + ["floor contested; canonical name preserved as key pending floor ruling"])
    if key_prefix != raw_prefix:
        return canonical_key, True, "; ".join(
            reasons + [f"label prefix '{key_prefix}' does not match inferred type '{raw_prefix}' (possible misread); preserved as key"]
        )

    result = canonical_name(canonical_key, mapped_type)
    if result.review_reason:
        reasons.append(result.review_reason)
    return result.canonical_name, (type_mapping.review_required or result.review_required), "; ".join(reasons)


def build_canonical_rows(normalized_rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """Apply naming convention + type mapping to each normalized row."""
    canonical_rows: List[Dict[str, str]] = []
    for row in normalized_rows:
        key = row.get("canonical_key", "")
        raw_type = row.get("equipment_type", "")
        category = row.get("discrepancy_category", "")
        mapped_type = map_equipment_type(raw_type).mapped_type
        name, review_required, review_reason = _canonical_name_for_row(key, raw_type, category)

        upstream_reason = (row.get("review_reason") or "").strip()
        merged_reason = "; ".join(reason for reason in (upstream_reason, review_reason) if reason)
        merged_review = _to_bool(row.get("review_required", "false")) or review_required
        canonical_rows.append(
            {
                "snapshot_version": row.get("snapshot_version", "w04"),
                "property_id": row.get("property_id", ""),
                "property_name": row.get("property_name", ""),
                "floor": row.get("floor", "Floor_02"),
                "canonical_name": name,
                "canonical_key": key,
                "equipment_type": mapped_type,
                "raw_equipment_type": raw_type,
                "discrepancy_category": category,
                "status": row.get("status", ""),
                "in_topics": row.get("in_topics", "false"),
                "in_drawings": row.get("in_drawings", "false"),
                "topics_raw_label": row.get("topics_raw_label", ""),
                "drawing_raw_label": row.get("drawing_raw_label", ""),
                "review_required": "true" if merged_review else "false",
                "review_reason": merged_reason,
            }
        )

    # Collision safety: canonical_name is the equipment_id downstream and must be
    # unique. Any residual collision falls back to the (unique) canonical key.
    by_name: Dict[str, List[Dict[str, str]]] = {}
    for row in canonical_rows:
        by_name.setdefault(row["canonical_name"], []).append(row)
    for name, group in by_name.items():
        if len(group) > 1:
            for row in group:
                row["canonical_name"] = row["canonical_key"]
                row["review_required"] = "true"
                extra = "canonical name collision; using canonical key"
                row["review_reason"] = f"{row['review_reason']}; {extra}" if row["review_reason"] else extra

    # canonical_key stays internal (dedup + collision fallback above); the public
    # output carries only canonical_name (Sourav #1).
    for row in canonical_rows:
        row.pop("canonical_key", None)
    return canonical_rows


def build_discrepancy_records(
    canonical_rows: Sequence[Dict[str, str]],
) -> List[DiscrepancyReportRecord]:
    records: List[DiscrepancyReportRecord] = []
    for row in canonical_rows:
        category = row.get("discrepancy_category", "")
        status = _CATEGORY_TO_STATUS.get(category, category or "matched")
        mapped_type = row.get("equipment_type", "")
        records.append(
            DiscrepancyReportRecord(
                building=row.get("property_name", "") or "unknown",
                floor=row.get("floor", "Floor_02"),
                equipment_type=mapped_type or "UNRESOLVED",
                equipment_id=row.get("canonical_name", "") or row.get("canonical_key", ""),
                in_points=_to_bool(row.get("in_topics", "false")),
                in_drawings=_to_bool(row.get("in_drawings", "false")),
                status=status,
                evidence_point=row.get("topics_raw_label", ""),
                evidence_drawing=row.get("drawing_raw_label", ""),
                severity_hint=_severity_for(status, mapped_type),
            )
        )
    return records


def _ensure_output_path_available(output_path: Path, overwrite: bool) -> None:
    if output_path.exists() and not overwrite:
        raise DiscrepancyInputError(f"Output path already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)


def write_canonical_equipment(canonical_rows, output_path, overwrite: bool = False) -> Path:
    output_path = Path(output_path)
    _ensure_output_path_available(output_path, overwrite)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CANONICAL_EQUIPMENT_HEADERS)
        writer.writeheader()
        for row in canonical_rows:
            writer.writerow({key: row.get(key, "") for key in CANONICAL_EQUIPMENT_HEADERS})
    return output_path


def write_discrepancy_report(records, output_path, overwrite: bool = False) -> Path:
    output_path = Path(output_path)
    _ensure_output_path_available(output_path, overwrite)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=DISCREPANCY_REPORT_HEADERS)
        writer.writeheader()
        for record in records:
            payload = record.model_dump()
            payload["in_points"] = "true" if record.in_points else "false"
            payload["in_drawings"] = "true" if record.in_drawings else "false"
            writer.writerow({key: payload.get(key, "") for key in DISCREPANCY_REPORT_HEADERS})
    return output_path


def summarize(records: Sequence[DiscrepancyReportRecord]) -> Dict[str, int]:
    summary: Dict[str, int] = {}
    for record in records:
        summary[record.status] = summary.get(record.status, 0) + 1
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit the W4 canonical equipment list + brief discrepancy report (no DB writes)."
    )
    parser.add_argument("--normalized-csv", default=str(DEFAULT_NORMALIZED_SNAPSHOT))
    parser.add_argument("--canonical-out", default=str(DEFAULT_CANONICAL_SNAPSHOT))
    parser.add_argument("--discrepancy-out", default=str(DEFAULT_DISCREPANCY_REPORT))
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    normalized_rows = load_normalized_rows(args.normalized_csv)
    canonical_rows = build_canonical_rows(normalized_rows)
    records = build_discrepancy_records(canonical_rows)

    canonical_path = write_canonical_equipment(canonical_rows, args.canonical_out, overwrite=args.overwrite)
    report_path = write_discrepancy_report(records, args.discrepancy_out, overwrite=args.overwrite)

    summary = summarize(records)
    print(f"Canonical equipment written: {canonical_path} ({len(canonical_rows)} units)")
    print(f"Discrepancy report written:  {report_path} ({len(records)} rows)")
    print("Status distribution: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
