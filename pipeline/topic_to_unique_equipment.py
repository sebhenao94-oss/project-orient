"""Extract equipment names from BMS topic_name paths.

This module is deterministic and model-free. It reads CSVs that contain a
``topic_name`` column with paths like:

    Floor_02/DEV123_AHU_1_01/ACT_COOL_STPT

The second path segment is treated as the equipment context. A leading
``DEV<digits>_`` prefix is removed, then names are grouped by a separator- and
zero-padding-insensitive match key so labels like ``AHU_1_1`` and
``AHU_01_1`` are flagged as possible duplicates. The output ``canonical_name``
keeps the unit number padded, e.g. ``AHU_2_01``.
"""

from __future__ import annotations

import argparse
import csv
import re
from difflib import get_close_matches
from pathlib import Path
from typing import Optional


DEVICE_PREFIX = re.compile(r"^DEV\d+_", re.IGNORECASE)
SEPARATOR_RUN = re.compile(r"[^A-Z0-9]+")
NUMERIC_TOKEN = re.compile(r"^\d+$")

TYPE_PRECEDENCE = (
    "VAVRH",
    "EAVAV",
    "OAVAV",
    "FPTU",
    "FCU",
    "AHU",
    "VAV",
)

OUTPUT_COLUMNS = (
    "canonical_name",
    "equipment_type",
    "in_topics",
    "in_drawings",
    "topics_raw_label",
    "raw_equipment_names",
    "equipment_contexts",
    "floors",
    "topic_count",
    "sample_topic_name",
    "review_required",
    "reason",
    "review_reason",
)


def strip_device_prefix(value: str) -> str:
    return DEVICE_PREFIX.sub("", value.strip())


def canonical_key(raw_label: str) -> str:
    without_prefix = strip_device_prefix(raw_label).upper()
    tokens = [token for token in SEPARATOR_RUN.split(without_prefix) if token]
    normalized_tokens = [
        str(int(token)) if NUMERIC_TOKEN.match(token) else token for token in tokens
    ]
    if not normalized_tokens:
        raise ValueError(f"label {raw_label!r} has no canonical content")
    return "_".join(normalized_tokens)


def canonical_name_from_key(key: str) -> str:
    tokens = key.split("_")
    numeric_positions = [
        index for index, token in enumerate(tokens) if NUMERIC_TOKEN.match(token)
    ]
    if len(numeric_positions) >= 2:
        unit_index = numeric_positions[-1]
        tokens[unit_index] = tokens[unit_index].zfill(2)
    return "_".join(tokens)


def split_topic_path(topic_name: str) -> tuple[str, str, str]:
    parts = topic_name.split("/", 2)
    if len(parts) < 3 or not parts[0] or not parts[1]:
        raise ValueError(f"topic_name does not look like <floor>/<equipment>/<point>: {topic_name!r}")
    return parts[0], parts[1], parts[2]


def infer_type(raw_label: str) -> str:
    upper_label = raw_label.upper()
    for equipment_type in TYPE_PRECEDENCE:
        if equipment_type in upper_label:
            return equipment_type
    return "UNRESOLVED"


def type_token(raw_label: str) -> str:
    tokens = [token for token in SEPARATOR_RUN.split(raw_label.upper()) if token]
    return tokens[0] if tokens else ""


def type_issue_reason(raw_label: str, inferred_type: str) -> str:
    if inferred_type != "UNRESOLVED":
        return ""
    token = type_token(raw_label)
    if not token:
        return "missing equipment type token"
    close = get_close_matches(token, TYPE_PRECEDENCE, n=1, cutoff=0.6)
    if close:
        return f"unrecognized equipment type token {token!r}; possible intended type {close[0]!r}"
    return f"unrecognized equipment type token {token!r}"


def load_topic_names(input_path: Path, topic_column: str = "topic_name") -> list[str]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError(f"{input_path}: missing CSV header row")
        if topic_column not in reader.fieldnames:
            raise ValueError(f"{input_path}: missing required column {topic_column!r}")
        return [row[topic_column].strip() for row in reader if row.get(topic_column, "").strip()]


def build_unique_equipment_rows(
    topic_names: list[str],
    floor: Optional[str] = None,
) -> list[dict[str, str]]:
    groups: dict[str, dict[str, object]] = {}

    for topic_name in topic_names:
        path_floor, equipment_context, _point_name = split_topic_path(topic_name)
        if floor and path_floor != floor:
            continue

        raw_label = strip_device_prefix(equipment_context)
        key = canonical_key(raw_label)
        inferred_type = infer_type(raw_label)
        group = groups.setdefault(
            key,
            {
                "types": set(),
                "raw_names": set(),
                "contexts": set(),
                "floors": set(),
                "topic_count": 0,
                "sample_topic_name": topic_name,
                "type_issue_reasons": set(),
            },
        )
        group["types"].add(inferred_type)
        group["raw_names"].add(raw_label)
        group["contexts"].add(equipment_context)
        group["floors"].add(path_floor)
        group["topic_count"] += 1
        reason = type_issue_reason(raw_label, inferred_type)
        if reason:
            group["type_issue_reasons"].add(reason)

    output_rows = []
    for key in sorted(groups, key=lambda value: (value.lower(), value)):
        group = groups[key]
        raw_names = sorted(group["raw_names"], key=lambda value: (value.lower(), value))
        contexts = sorted(group["contexts"], key=lambda value: (value.lower(), value))
        floors = sorted(group["floors"], key=lambda value: (value.lower(), value))
        types = sorted(group["types"], key=lambda value: (value.lower(), value))

        review_reasons = []
        if len(raw_names) > 1:
            review_reasons.append("possible duplicate labels collapsed to same canonical_name")
        review_reasons.extend(sorted(group["type_issue_reasons"]))
        if len(types) > 1:
            review_reasons.append("multiple inferred equipment types in same canonical_name group")

        output_rows.append(
            {
                "canonical_name": canonical_name_from_key(key),
                "equipment_type": types[0] if len(types) == 1 else ";".join(types),
                "in_topics": "true",
                "in_drawings": "false",
                "topics_raw_label": ";".join(raw_names),
                "raw_equipment_names": ";".join(raw_names),
                "equipment_contexts": ";".join(contexts),
                "floors": ";".join(floors),
                "topic_count": str(group["topic_count"]),
                "sample_topic_name": str(group["sample_topic_name"]),
                "review_required": "true" if review_reasons else "false",
                "reason": "; ".join(review_reasons),
                "review_reason": "; ".join(review_reasons),
            }
        )

    return output_rows


def write_rows(rows: list[dict[str, str]], output_path: Path, overwrite: bool = False) -> None:
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {output_path}; rerun with --overwrite")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Extract unique equipment names from topic paths.")
    parser.add_argument("--input", required=True, help="Input CSV containing a topic_name column.")
    parser.add_argument("--output", required=True, help="Output review CSV path.")
    parser.add_argument("--topic-column", default="topic_name")
    parser.add_argument("--floor", default=None, help="Optional floor filter, e.g. Floor_02.")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    topic_names = load_topic_names(Path(args.input), args.topic_column)
    rows = build_unique_equipment_rows(topic_names, args.floor)
    write_rows(rows, Path(args.output), overwrite=args.overwrite)

    review_count = sum(1 for row in rows if row["review_required"] == "true")
    print(f"Unique equipment groups written: {len(rows)}")
    print(f"Review-required groups: {review_count}")
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
