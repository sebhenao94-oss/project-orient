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
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import BaseModel, Field, field_validator

if __package__:
    from .equipment_vocab import PLANT_CONTAINER_KEYS, canonical_name, map_equipment_type
    from .models import RelationshipRefType
    from .normalization import NormalizationInputError, canonical_key as normalized_key
else:
    from equipment_vocab import PLANT_CONTAINER_KEYS, canonical_name, map_equipment_type
    from models import RelationshipRefType
    from normalization import NormalizationInputError, canonical_key as normalized_key


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
DEFAULT_RELATIONSHIPS_JSON = (
    PROJECT_ROOT / "data" / "snapshots" / "w06" / "relationships_floor_02.json"
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
    "source_files",
    "airRef",
    "chilledWaterRef",
    "hotWaterRef",
    "condenserWaterRef",
    "spaceRef",
    "review_required",
    "review_reason",
)

# Haystack ref columns the relationship join may fill (lead 3c).
_REF_COLUMNS = (
    "airRef",
    "chilledWaterRef",
    "hotWaterRef",
    "condenserWaterRef",
    "spaceRef",
)
_VALID_REF_TYPES = {ref_type.value for ref_type in RelationshipRefType}


@dataclass
class RelationshipRefJoinStats:
    """Run-level counters for relationship edges considered by the ref join."""

    joined_edges: int = 0
    valid_uncolumned_edges: int = 0

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


def build_canonical_rows(
    normalized_rows: Sequence[Dict[str, str]],
    relationships_doc: Optional[Mapping[str, Any]] = None,
    relationship_stats: Optional[RelationshipRefJoinStats] = None,
) -> List[Dict[str, str]]:
    """Apply naming convention + type mapping to each normalized row.

    ``relationships_doc`` optionally carries an inferred-relationships snapshot
    (see ``graphics_relationships.py`` / ``relationship_tiling.py``); its edges
    fill the equipment-serving Haystack ref columns, with conflicting or
    unconfirmed edges routed to review instead of silently accepted. Callers
    that need a run summary may pass ``relationship_stats`` for in-place
    counters without changing the returned row shape.
    """
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
                "source_files": row.get("source_files", ""),
                "airRef": "",
                "chilledWaterRef": "",
                "hotWaterRef": "",
                "condenserWaterRef": "",
                "spaceRef": "",
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

    if relationships_doc:
        _apply_relationship_refs(canonical_rows, relationships_doc, relationship_stats)

    # canonical_key stays internal (dedup + collision fallback above); the public
    # output carries only canonical_name (Sourav #1).
    for row in canonical_rows:
        row.pop("canonical_key", None)
    return canonical_rows


def _flag_for_review(row: Dict[str, str], reason: str) -> None:
    row["review_required"] = "true"
    row["review_reason"] = f"{row['review_reason']}; {reason}" if row.get("review_reason") else reason


def _apply_relationship_refs(
    canonical_rows: Sequence[Dict[str, str]],
    relationships_doc: Mapping[str, Any],
    stats: Optional[RelationshipRefJoinStats] = None,
) -> RelationshipRefJoinStats:
    """Fill equipment-serving ref columns from inferred relationship edges.

    A trusted edge fills the column; an edge the relationship extractor itself
    flagged fills the column but routes the row to review; a conflicting edge
    never fills the column — the conflict is surfaced as a review reason.
    Valid Haystack refs without canonical-equipment columns (``systemRef`` and
    ``floorRef``) are counted so the CLI never drops them silently.
    """
    if stats is None:
        stats = RelationshipRefJoinStats()

    rows_by_key: Dict[str, Dict[str, str]] = {}
    for row in canonical_rows:
        for alias in (row.get("canonical_key", ""), row.get("canonical_name", "")):
            if not alias:
                continue
            try:
                rows_by_key.setdefault(normalized_key(alias), row)
            except NormalizationInputError:
                continue

    def find_row(label: str, raw_alias: str = "") -> Optional[Dict[str, str]]:
        for alias in (label, raw_alias):
            if not alias:
                continue
            try:
                row = rows_by_key.get(normalized_key(alias))
            except NormalizationInputError:
                continue
            if row is not None:
                return row
        return None

    def display_name(label: str, raw_alias: str = "") -> str:
        target = find_row(label, raw_alias)
        return target["canonical_name"] if target else label

    for edge in relationships_doc.get("relationships", []):
        ref_type = str(edge.get("ref_type", ""))
        child = str(edge.get("child", "") or "")
        parent = str(edge.get("parent", "") or "")
        if ref_type not in _REF_COLUMNS:
            if ref_type in _VALID_REF_TYPES:
                stats.valid_uncolumned_edges += 1
            continue
        if not child or not parent:
            continue
        row = find_row(child, str(edge.get("child_raw", "") or ""))
        if row is None:
            continue

        if edge.get("conflict"):
            reason = str(edge.get("conflict_reason") or "").strip() or f"evidence points to {parent}"
            _flag_for_review(row, f"{ref_type} conflict: {reason}")
            continue

        parent_name = display_name(parent, str(edge.get("parent_raw", "") or ""))
        existing = row.get(ref_type, "")
        if existing and existing != parent_name:
            row[ref_type] = f"{existing};{parent_name}"
            _flag_for_review(row, f"multiple {ref_type} parents inferred: {row[ref_type]}")
            stats.joined_edges += 1
            continue
        row[ref_type] = parent_name
        stats.joined_edges += 1
        if edge.get("review_required"):
            note = str(edge.get("review_reason") or "").strip() or "flagged by relationship extraction"
            _flag_for_review(row, f"{ref_type} {parent_name} inferred but unconfirmed: {note}")
    return stats


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
    parser.add_argument(
        "--relationships-json",
        default=str(DEFAULT_RELATIONSHIPS_JSON),
        help="Inferred-relationships snapshot used to fill the equipment-serving ref "
        "columns (skipped with a note when the default file is absent).",
    )
    parser.add_argument(
        "--no-relationships",
        action="store_true",
        help="Do not fill ref columns from a relationships snapshot.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    normalized_rows = load_normalized_rows(args.normalized_csv)

    relationships_doc = None
    if not args.no_relationships:
        relationships_path = Path(args.relationships_json)
        if relationships_path.exists():
            relationships_doc = json.loads(relationships_path.read_text(encoding="utf-8"))
        elif args.relationships_json != str(DEFAULT_RELATIONSHIPS_JSON):
            print(f"relationships snapshot not found: {relationships_path}")
            return 1
        else:
            print(f"note: no relationships snapshot at {relationships_path}; ref columns left empty")

    relationship_stats = RelationshipRefJoinStats()
    canonical_rows = build_canonical_rows(
        normalized_rows,
        relationships_doc,
        relationship_stats=relationship_stats,
    )
    records = build_discrepancy_records(canonical_rows)

    canonical_path = write_canonical_equipment(canonical_rows, args.canonical_out, overwrite=args.overwrite)
    report_path = write_discrepancy_report(records, args.discrepancy_out, overwrite=args.overwrite)

    summary = summarize(records)
    refs_filled = sum(1 for row in canonical_rows if any(row.get(ref) for ref in _REF_COLUMNS))
    print(f"Canonical equipment written: {canonical_path} ({len(canonical_rows)} units)")
    print(f"Discrepancy report written:  {report_path} ({len(records)} rows)")
    print(f"Ref columns filled on {refs_filled} unit(s)")
    print(
        "Relationship ref edges: "
        f"joined={relationship_stats.joined_edges}, "
        f"valid-but-uncolumned={relationship_stats.valid_uncolumned_edges}"
    )
    print("Status distribution: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
