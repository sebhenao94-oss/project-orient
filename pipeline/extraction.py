"""Raw equipment extraction for Project ORIENT Week 3.

This module will process prepared BMS screenshots and mechanical-drawing
images using a vision-capable LLM.

Week 3 responsibilities:
- Extract equipment labels visible in each source image.
- Identify the source floor and retain Floor 02 equipment only.
- Classify raw equipment types such as AHU, FCU, VAV, VAVRH, FPTU,
  OAVAV, and unresolved project-specific types.
- Preserve source filename, source type, evidence detail, and confidence.
- Write versioned raw extraction snapshots under data/snapshots/w03/.

This module must not:
- Write equipment directly to the production database.
- Resolve discrepancies between drawings and database topics.
- Deduplicate or finalize canonical equipment names.
- Infer AHU-to-terminal relationships.

Normalization, deduplication, discrepancy analysis, and relationship mapping
belong to the Week 4 pipeline stages.
"""

import csv
from pathlib import Path
from typing import List, Sequence

from pydantic import ValidationError

from models import RawDrawingEquipmentRecord


RAW_DRAWING_EQUIPMENT_HEADERS = (
    "property_id",
    "floor",
    "source_file",
    "source_type",
    "raw_equipment_label",
    "raw_equipment_type",
    "evidence_detail",
    "confidence",
)

DEFAULT_RAW_DRAWING_EQUIPMENT_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "snapshots"
    / "w03"
    / "equipment_from_drawings_raw.csv"
)


class RawSnapshotValidationError(ValueError):
    """Raised when a raw Week 3 snapshot fails read-only validation."""


def _validate_headers(fieldnames: Sequence[str], csv_path: Path) -> None:
    if not fieldnames:
        raise RawSnapshotValidationError(f"{csv_path}: missing CSV header row")

    expected_headers = set(RAW_DRAWING_EQUIPMENT_HEADERS)
    actual_headers = set(fieldnames)
    missing_headers = sorted(expected_headers - actual_headers)
    unexpected_headers = sorted(actual_headers - expected_headers)

    if not missing_headers and not unexpected_headers:
        return

    details = []
    if missing_headers:
        details.append(f"missing required header(s): {', '.join(missing_headers)}")
    if unexpected_headers:
        details.append(f"unexpected header(s): {', '.join(unexpected_headers)}")

    raise RawSnapshotValidationError(f"{csv_path}: invalid CSV headers; {'; '.join(details)}")


def load_raw_drawing_equipment_snapshot(
    csv_path=DEFAULT_RAW_DRAWING_EQUIPMENT_SNAPSHOT,
) -> List[RawDrawingEquipmentRecord]:
    """Load raw drawing equipment records from a snapshot without modifying it."""
    csv_path = Path(csv_path)
    records: List[RawDrawingEquipmentRecord] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        _validate_headers(reader.fieldnames, csv_path)

        for row_number, row in enumerate(reader, start=2):
            try:
                records.append(RawDrawingEquipmentRecord(**row))
            except ValidationError as exc:
                raise RawSnapshotValidationError(
                    f"{csv_path}: CSV row {row_number} failed validation: {exc}"
                ) from exc

    return records
