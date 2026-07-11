"""W4 Track B: reconcile the W3 topics- and drawing-derived equipment snapshots.

The two immutable W3 snapshots describe Floor-02 equipment from different
vantage points:

* ``topics_equipment_floor_02.csv`` is derived from the BMS topic tree (the
  database's own record of what equipment exists), and
* ``drawing_equipment_floor_02.csv`` is the model's reading of the BMS graphics
  drawings.

Normalization matches them on a separator- and zero-padding-insensitive
canonical key, then classifies each canonical unit as agreement
(``matched`` / ``type_mismatch``) or a gap (``topics_only`` / ``drawing_only``).
The gap report is the primary W4 deliverable.

The seven contested-floor ventilation contexts handed off in
``data/snapshots/w04/floor_ambiguous_contexts.csv`` get special treatment: per
the W4 handoff, they must be carried as ``status=floor_ambiguous`` and routed to
review rather than silently dropped or silently kept as settled Floor-2
equipment. A supervisor clarification is pending. See
``data/snapshots/w04/README.md``.

This module is read-only with respect to its inputs; it never mutates the W3
snapshots. Like the W3 topics exporter, it does not call any model endpoint.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from pydantic import ValidationError

if __package__:
    from .models import (
        DiscrepancyCategory,
        NormalizationStatus,
        NormalizationSummary,
        NormalizedEquipmentRecord,
    )
else:
    from models import (
        DiscrepancyCategory,
        NormalizationStatus,
        NormalizationSummary,
        NormalizedEquipmentRecord,
    )

DEFAULT_TOPICS_SNAPSHOT = Path("data/snapshots/w03/topics_equipment_floor_02.csv")
DEFAULT_DRAWING_SNAPSHOT = Path("data/snapshots/w03/drawing_equipment_floor_02.csv")
DEFAULT_FLOOR_AMBIGUOUS = Path("data/snapshots/w04/floor_ambiguous_contexts.csv")
DEFAULT_NORMALIZED_SNAPSHOT = Path("data/snapshots/w04/normalized_equipment_floor_02.csv")

TOPICS_SNAPSHOT_HEADERS = [
    "snapshot_version",
    "property_id",
    "property_name",
    "floor",
    "raw_equipment_context",
    "raw_label",
    "inferred_raw_type",
    "topic_count",
    "evidence_strength",
    "source_type",
    "review_required",
    "review_reason",
]

DRAWING_SNAPSHOT_HEADERS = [
    "snapshot_version",
    "property_name",
    "property_id",
    "floor",
    "source_filename",
    "source_relative_path",
    "source_sha256",
    "pdf_page_number",
    "prompt_version",
    "model_id",
    "raw_label",
    "llm_proposed_canonical_name",
    "equipment_type",
    "confidence",
    "run_status",
    "review_required",
    "review_reason",
]

FLOOR_AMBIGUOUS_HEADERS = [
    "property_id",
    "floor_path",
    "raw_equipment_context",
    "raw_label",
    "inferred_raw_type",
    "topic_count",
    "path_floor",
    "name_token_floor",
    "status",
    "review_reason",
]

NORMALIZED_SNAPSHOT_HEADERS = [
    "snapshot_version",
    "property_id",
    "property_name",
    "floor",
    "canonical_name",
    "canonical_key",
    "equipment_type",
    "discrepancy_category",
    "status",
    "in_topics",
    "in_drawings",
    "topics_raw_label",
    "topics_inferred_type",
    "drawing_raw_label",
    "drawing_equipment_type",
    "source_files",
    "review_required",
    "review_reason",
]

_DEVICE_PREFIX = re.compile(r"^DEV\d+_", re.IGNORECASE)
_SEPARATOR_RUN = re.compile(r"[^0-9A-Za-z]+")
_NUMERIC_TOKEN = re.compile(r"^\d+$")


class NormalizationInputError(ValueError):
    """Raised when a normalization input snapshot fails read-only validation."""


class NormalizationArtifactError(ValueError):
    """Raised when a normalization artifact cannot be written safely."""


def strip_device_prefix(raw_label: str) -> str:
    """Remove a leading ``DEV<digits>_`` provenance prefix, if present."""
    return _DEVICE_PREFIX.sub("", raw_label.strip())


def canonical_key(raw_label: str) -> str:
    """Return a separator- and zero-padding-insensitive match key for a label.

    The two W3 sources spell the same unit differently: ``AHU-02A`` vs
    ``AHU_02A``, ``OAVAV_2_01`` vs ``OAVAV_02_01``, ``VAVRH_2_01`` vs
    ``VAVRH_2_1``. To match them we uppercase, drop any device prefix, split on
    runs of non-alphanumeric characters, and strip leading zeros from purely
    numeric tokens (``02`` -> ``2``, ``01`` -> ``1``). Mixed alphanumeric tokens
    such as ``02A`` are left intact apart from the split.

    This deliberately does NOT collapse the floor-distinguishing digit: a
    ``_1_`` token and a ``_2_`` token produce different keys. That distinction is
    exactly the contested-floor question the floor-ambiguity handoff is about, so
    it must survive normalization rather than be silently merged away.
    """
    without_prefix = strip_device_prefix(raw_label).upper()
    tokens = [token for token in _SEPARATOR_RUN.split(without_prefix) if token]
    normalized_tokens = [
        str(int(token)) if _NUMERIC_TOKEN.match(token) else token for token in tokens
    ]
    if not normalized_tokens:
        raise NormalizationInputError(f"label {raw_label!r} has no canonical content")
    return "_".join(normalized_tokens)


def _validate_headers(
    fieldnames: Optional[Sequence[str]],
    expected: Sequence[str],
    csv_path: Path,
) -> None:
    if not fieldnames:
        raise NormalizationInputError(f"{csv_path}: missing CSV header row")
    expected_set = set(expected)
    actual_set = set(fieldnames)
    missing = sorted(expected_set - actual_set)
    unexpected = sorted(actual_set - expected_set)
    if not missing and not unexpected:
        return
    details = []
    if missing:
        details.append(f"missing required header(s): {', '.join(missing)}")
    if unexpected:
        details.append(f"unexpected header(s): {', '.join(unexpected)}")
    raise NormalizationInputError(f"{csv_path}: invalid CSV headers; {'; '.join(details)}")


def _read_rows(csv_path: Path, expected_headers: Sequence[str]) -> List[Dict[str, str]]:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise NormalizationInputError(f"{csv_path}: snapshot not found")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        _validate_headers(reader.fieldnames, expected_headers, csv_path)
        return [dict(row) for row in reader]


def load_floor_ambiguous_keys(
    csv_path: Path = DEFAULT_FLOOR_AMBIGUOUS,
) -> Dict[str, Dict[str, str]]:
    """Load the W4 floor-ambiguity handoff, keyed by canonical key.

    Returns a mapping from canonical key to the handoff row, so the reconciler
    can override the disposition of any unit whose floor is contested.
    """
    rows = _read_rows(csv_path, FLOOR_AMBIGUOUS_HEADERS)
    ambiguous: Dict[str, Dict[str, str]] = {}
    for row in rows:
        key = canonical_key(row["raw_label"])
        ambiguous[key] = row
    return ambiguous


def reconcile_floor_02(
    topics_rows: List[Dict[str, str]],
    drawing_rows: List[Dict[str, str]],
    ambiguous_keys: Dict[str, Dict[str, str]],
    *,
    snapshot_version: str = "w04",
) -> List[NormalizedEquipmentRecord]:
    """Reconcile the two W3 source row sets into canonical normalized records.

    Topics rows are one-per-unit; drawing rows repeat a unit once per source
    image, so drawings are collapsed to one entry per canonical key (first seen
    wins for the human-facing label, matching the topics ordering downstream).
    """
    topics_by_key: Dict[str, Dict[str, str]] = {}
    property_id = ""
    property_name = ""
    for row in topics_rows:
        property_id = property_id or row["property_id"]
        property_name = property_name or row["property_name"]
        topics_by_key.setdefault(canonical_key(row["raw_label"]), row)

    drawing_by_key: Dict[str, Dict[str, str]] = {}
    drawing_sources_by_key: Dict[str, set] = {}
    for row in drawing_rows:
        if row.get("run_status") and row["run_status"] != "succeeded":
            continue
        property_id = property_id or row["property_id"]
        property_name = property_name or row["property_name"]
        # Match on the cleaned canonical name, not the raw OCR label: the topics
        # side stores tidy labels (``AHU-02A``) while the drawing raw label is the
        # model's literal reading (``AHU 02 A``). The canonical name is the
        # normalised form intended to line up across sources.
        drawing_match_label = row["llm_proposed_canonical_name"] or row["raw_label"]
        key = canonical_key(drawing_match_label)
        drawing_by_key.setdefault(key, row)
        # The same unit is usually extracted from several drawings; keep every
        # contributing source file for row-level provenance (lead 3b).
        source_filename = (row.get("source_filename") or "").strip()
        if source_filename:
            drawing_sources_by_key.setdefault(key, set()).add(source_filename)

    records: List[NormalizedEquipmentRecord] = []
    for key in sorted(set(topics_by_key) | set(drawing_by_key)):
        topic = topics_by_key.get(key)
        drawing = drawing_by_key.get(key)
        in_topics = topic is not None
        in_drawings = drawing is not None

        topics_raw_label = topic["raw_label"] if topic else ""
        topics_type = topic["inferred_raw_type"] if topic else ""
        drawing_raw_label = drawing["raw_label"] if drawing else ""
        drawing_type = drawing["equipment_type"] if drawing else ""

        canonical_name = (
            (drawing["llm_proposed_canonical_name"] if drawing else "")
            or strip_device_prefix(topics_raw_label)
            or strip_device_prefix(drawing_raw_label)
        )
        equipment_type = topics_type or drawing_type or "unknown"

        ambiguous = ambiguous_keys.get(key)
        if ambiguous:
            category = DiscrepancyCategory.FLOOR_AMBIGUOUS
            status = NormalizationStatus.FLOOR_AMBIGUOUS
            review_required = True
            review_reason = ambiguous.get("review_reason", "").strip() or (
                "floor contested between topic path and unit-name token; "
                "supervisor clarification pending"
            )
        elif in_topics and in_drawings:
            if topics_type and drawing_type and topics_type != drawing_type:
                category = DiscrepancyCategory.TYPE_MISMATCH
                status = NormalizationStatus.REVIEW_REQUIRED
                review_required = True
                review_reason = (
                    f"type mismatch: topics={topics_type} drawings={drawing_type}"
                )
            else:
                category = DiscrepancyCategory.MATCHED
                status = NormalizationStatus.SETTLED
                review_required = False
                review_reason = ""
        elif in_topics:
            category = DiscrepancyCategory.TOPICS_ONLY
            status = NormalizationStatus.REVIEW_REQUIRED
            review_required = True
            review_reason = "present in BMS topics but absent from drawing evidence"
        else:
            category = DiscrepancyCategory.DRAWING_ONLY
            status = NormalizationStatus.REVIEW_REQUIRED
            review_required = True
            review_reason = "extracted from drawings but absent from BMS topics"

        try:
            records.append(
                NormalizedEquipmentRecord(
                    snapshot_version=snapshot_version,
                    property_id=property_id,
                    property_name=property_name,
                    floor="Floor_02",
                    canonical_name=canonical_name,
                    canonical_key=key,
                    equipment_type=equipment_type,
                    discrepancy_category=category,
                    status=status,
                    in_topics=in_topics,
                    in_drawings=in_drawings,
                    topics_raw_label=topics_raw_label,
                    topics_inferred_type=topics_type,
                    drawing_raw_label=drawing_raw_label,
                    drawing_equipment_type=drawing_type,
                    source_files=";".join(sorted(drawing_sources_by_key.get(key, ()))),
                    review_required=review_required,
                    review_reason=review_reason,
                )
            )
        except ValidationError as exc:
            raise NormalizationArtifactError(
                f"failed to build normalized record for key {key!r}: {exc}"
            ) from exc

    return records


def summarize(
    records: List[NormalizedEquipmentRecord],
    *,
    snapshot_version: str = "w04",
) -> NormalizationSummary:
    """Aggregate normalized records into the W4 gap-report summary."""
    property_id = records[0].property_id if records else "unknown"
    property_name = records[0].property_name if records else "unknown"

    def count(category: DiscrepancyCategory) -> int:
        return sum(1 for record in records if record.discrepancy_category == category)

    return NormalizationSummary(
        snapshot_version=snapshot_version,
        property_id=property_id,
        property_name=property_name,
        floor="Floor_02",
        total_units=len(records),
        matched_count=count(DiscrepancyCategory.MATCHED),
        type_mismatch_count=count(DiscrepancyCategory.TYPE_MISMATCH),
        topics_only_count=count(DiscrepancyCategory.TOPICS_ONLY),
        drawing_only_count=count(DiscrepancyCategory.DRAWING_ONLY),
        floor_ambiguous_count=count(DiscrepancyCategory.FLOOR_AMBIGUOUS),
        review_required_count=sum(1 for record in records if record.review_required),
    )


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _ensure_output_path_available(output_path: Path, overwrite: bool) -> None:
    if output_path.exists() and not overwrite:
        raise NormalizationArtifactError(
            f"{output_path}: artifact already exists; pass --overwrite to replace"
        )


def write_normalized_snapshot(
    records: List[NormalizedEquipmentRecord],
    output_path: Path = DEFAULT_NORMALIZED_SNAPSHOT,
    *,
    overwrite: bool = False,
) -> None:
    """Write the reconciled canonical equipment list to a CSV snapshot."""
    output_path = Path(output_path)
    _ensure_output_path_available(output_path, overwrite)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=NORMALIZED_SNAPSHOT_HEADERS)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "snapshot_version": record.snapshot_version,
                    "property_id": record.property_id,
                    "property_name": record.property_name,
                    "floor": record.floor,
                    "canonical_name": record.canonical_name,
                    "canonical_key": record.canonical_key,
                    "equipment_type": record.equipment_type,
                    "discrepancy_category": record.discrepancy_category.value,
                    "status": record.status.value,
                    "in_topics": _bool_text(record.in_topics),
                    "in_drawings": _bool_text(record.in_drawings),
                    "topics_raw_label": record.topics_raw_label,
                    "topics_inferred_type": record.topics_inferred_type,
                    "drawing_raw_label": record.drawing_raw_label,
                    "drawing_equipment_type": record.drawing_equipment_type,
                    "source_files": record.source_files,
                    "review_required": _bool_text(record.review_required),
                    "review_reason": record.review_reason,
                }
            )


def normalize_floor_02(
    *,
    topics_path: Path = DEFAULT_TOPICS_SNAPSHOT,
    drawing_path: Path = DEFAULT_DRAWING_SNAPSHOT,
    floor_ambiguous_path: Path = DEFAULT_FLOOR_AMBIGUOUS,
    snapshot_version: str = "w04",
) -> List[NormalizedEquipmentRecord]:
    """Load the three input snapshots and reconcile them. Read-only on inputs."""
    topics_rows = _read_rows(topics_path, TOPICS_SNAPSHOT_HEADERS)
    drawing_rows = _read_rows(drawing_path, DRAWING_SNAPSHOT_HEADERS)
    ambiguous_keys = load_floor_ambiguous_keys(floor_ambiguous_path)
    return reconcile_floor_02(
        topics_rows,
        drawing_rows,
        ambiguous_keys,
        snapshot_version=snapshot_version,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="W4 Track B: reconcile W3 topics- and drawing-derived snapshots."
    )
    parser.add_argument("--topics-path", default=str(DEFAULT_TOPICS_SNAPSHOT))
    parser.add_argument("--drawing-path", default=str(DEFAULT_DRAWING_SNAPSHOT))
    parser.add_argument("--floor-ambiguous-path", default=str(DEFAULT_FLOOR_AMBIGUOUS))
    parser.add_argument("--output-path", default=str(DEFAULT_NORMALIZED_SNAPSHOT))
    parser.add_argument("--snapshot-version", default="w04")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        records = normalize_floor_02(
            topics_path=Path(args.topics_path),
            drawing_path=Path(args.drawing_path),
            floor_ambiguous_path=Path(args.floor_ambiguous_path),
            snapshot_version=args.snapshot_version,
        )
        write_normalized_snapshot(
            records,
            Path(args.output_path),
            overwrite=args.overwrite,
        )
    except (NormalizationInputError, NormalizationArtifactError) as exc:
        print(f"Normalization failed: {exc}")
        return 1

    summary = summarize(records, snapshot_version=args.snapshot_version)
    print(
        "Normalized {total} units -> {output}\n"
        "  matched={matched} type_mismatch={mismatch} "
        "topics_only={topics} drawing_only={drawing} "
        "floor_ambiguous={ambiguous} review_required={review}".format(
            total=summary.total_units,
            output=args.output_path,
            matched=summary.matched_count,
            mismatch=summary.type_mismatch_count,
            topics=summary.topics_only_count,
            drawing=summary.drawing_only_count,
            ambiguous=summary.floor_ambiguous_count,
            review=summary.review_required_count,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
