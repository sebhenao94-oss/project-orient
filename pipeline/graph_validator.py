"""W4 relationship graph validator (B5) for Project ORIENT.

Pure validation of a list of relationship edges against the equipment list they
should reference. The core ``validate`` function does no I/O; a thin CLI wrapper
reads the relationships JSON and the canonical equipment CSV and writes a report.

Checks (each finding carries a machine-readable ``check_id`` and offending ids):

* ``unknown_node``        — an edge endpoint not present in the equipment list.
* ``multiple_air_parents``— a terminal unit with more than one ``airRef`` parent.
* ``cycle``               — a cycle in the airRef/systemRef parent graph.
* ``ref_type_sanity``     — ``airRef`` child must be a terminal and parent an air
                            source (AHU/DOAS/MAU); water refs must point to a plant.

Non-error findings:

* ``orphan_terminal``     — a terminal with no ``airRef`` (listed separately; not
                            an error, since with zero extracted edges every
                            terminal is trivially an orphan).
* ``review_item``         — an edge with confidence < 0.75 or ``conflict=true``.

The report ``passed`` flag is true when there are no error-level findings.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Set


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELATIONSHIPS = (
    PROJECT_ROOT / "data" / "snapshots" / "w04" / "relationships_floor_02.json"
)
DEFAULT_CANONICAL_EQUIPMENT = (
    PROJECT_ROOT / "data" / "snapshots" / "w04" / "canonical_equipment_floor_02.csv"
)
DEFAULT_REPORT_OUT = (
    PROJECT_ROOT / "data" / "snapshots" / "w04" / "graph_validation_floor_02.json"
)

LOW_CONFIDENCE_THRESHOLD = 0.75

AIR_SOURCE_TYPES = {"AHU", "DOAS", "MAU"}
PLANT_TYPES = {
    "CHW-PLANT",
    "HW-PLANT",
    "COND-PLANT",
    "CHILLER",
    "BOILER",
    "COOLING-TOWER",
    "CHW-PUMP",
    "COND-PUMP",
    "HW-PUMP",
}
WATER_REF_TYPES = {"chilledWaterRef", "hotWaterRef", "condenserWaterRef"}


def is_air_source(equipment_type: str) -> bool:
    return (equipment_type or "").upper() in AIR_SOURCE_TYPES


def is_plant(equipment_type: str) -> bool:
    return (equipment_type or "").upper() in PLANT_TYPES


def is_terminal(equipment_type: str) -> bool:
    value = (equipment_type or "").upper()
    if value in {"VAV", "FCU", "OAVAV", "EAVAV", "FPTU"}:
        return True
    return value.startswith("VAV-RH") or value.startswith("FPTU") or value.startswith("OAVAV")


@dataclass(frozen=True)
class Finding:
    check_id: str
    severity: str  # "error" | "orphan" | "review"
    message: str
    nodes: Sequence[str] = field(default_factory=tuple)


@dataclass
class GraphValidationReport:
    edge_count: int
    equipment_count: int
    errors: List[Finding] = field(default_factory=list)
    orphans: List[Finding] = field(default_factory=list)
    review_items: List[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> Dict[str, object]:
        def dump(findings: Sequence[Finding]):
            return [
                {
                    "check_id": finding.check_id,
                    "severity": finding.severity,
                    "message": finding.message,
                    "nodes": list(finding.nodes),
                }
                for finding in findings
            ]

        return {
            "edge_count": self.edge_count,
            "equipment_count": self.equipment_count,
            "passed": self.passed,
            "error_count": len(self.errors),
            "orphan_count": len(self.orphans),
            "review_item_count": len(self.review_items),
            "errors": dump(self.errors),
            "orphans": dump(self.orphans),
            "review_items": dump(self.review_items),
        }


def validate(
    edges: Sequence[Mapping[str, object]],
    equipment: Mapping[str, str],
) -> GraphValidationReport:
    """Validate relationship edges against an equipment name -> type mapping."""
    report = GraphValidationReport(edge_count=len(edges), equipment_count=len(equipment))

    air_parents: Dict[str, List[str]] = {}
    parent_of: Dict[str, Set[str]] = {}

    for edge in edges:
        child = str(edge.get("child", "")).strip()
        parent = str(edge.get("parent", "")).strip()
        ref_type = str(edge.get("ref_type", "")).strip()

        # unknown_node
        unknown = [node for node in (child, parent) if node and node not in equipment]
        if unknown:
            report.errors.append(
                Finding("unknown_node", "error", f"edge endpoint(s) not in equipment list: {unknown}", unknown)
            )

        # ref_type sanity
        child_type = equipment.get(child, "")
        parent_type = equipment.get(parent, "")
        if ref_type == "airRef":
            if child in equipment and not is_terminal(child_type):
                report.errors.append(
                    Finding("ref_type_sanity", "error", f"airRef child '{child}' is not a terminal ({child_type})", [child])
                )
            if parent in equipment and not is_air_source(parent_type):
                report.errors.append(
                    Finding("ref_type_sanity", "error", f"airRef parent '{parent}' is not an air source ({parent_type})", [parent])
                )
            air_parents.setdefault(child, []).append(parent)
        elif ref_type in WATER_REF_TYPES:
            if parent in equipment and not is_plant(parent_type):
                report.errors.append(
                    Finding("ref_type_sanity", "error", f"{ref_type} parent '{parent}' is not a plant ({parent_type})", [parent])
                )

        if child and parent:
            parent_of.setdefault(child, set()).add(parent)

        # review items: low confidence or conflict
        confidence = edge.get("confidence")
        conflict = bool(edge.get("conflict", False))
        try:
            low = confidence is not None and float(confidence) < LOW_CONFIDENCE_THRESHOLD
        except (TypeError, ValueError):
            low = False
        if low or conflict:
            reason = []
            if low:
                reason.append(f"confidence {confidence} < {LOW_CONFIDENCE_THRESHOLD}")
            if conflict:
                reason.append("conflict=true")
            report.review_items.append(
                Finding("review_item", "review", f"edge {child} -> {parent} ({ref_type}): {', '.join(reason)}", [child, parent])
            )

    # multiple_air_parents (count distinct parents; duplicate edges to the same
    # parent are not a conflict)
    for child, parents in air_parents.items():
        distinct_parents = sorted(set(parents))
        if len(distinct_parents) > 1:
            report.errors.append(
                Finding("multiple_air_parents", "error", f"terminal '{child}' has {len(distinct_parents)} airRef parents: {distinct_parents}", [child])
            )

    # cycles in the parent graph
    for node in _find_cycle_nodes(parent_of):
        report.errors.append(Finding("cycle", "error", f"node participates in a parent cycle: {node}", [node]))

    # orphan terminals (no airRef) — informational, not an error
    has_air_parent = set(air_parents.keys())
    for name, equipment_type in equipment.items():
        if is_terminal(equipment_type) and name not in has_air_parent:
            report.orphans.append(
                Finding("orphan_terminal", "orphan", f"terminal '{name}' ({equipment_type}) has no airRef parent", [name])
            )

    return report


def _find_cycle_nodes(parent_of: Mapping[str, Set[str]]) -> List[str]:
    color: Dict[str, int] = {}  # 0=white,1=gray,2=black
    cycle_nodes: Set[str] = set()

    def visit(node: str, stack: Set[str]) -> None:
        color[node] = 1
        stack.add(node)
        for parent in parent_of.get(node, ()):  # follow child -> parent
            if parent in stack:
                cycle_nodes.add(parent)
            elif color.get(parent, 0) == 0:
                visit(parent, stack)
        stack.discard(node)
        color[node] = 2

    for node in list(parent_of.keys()):
        if color.get(node, 0) == 0:
            visit(node, set())
    return sorted(cycle_nodes)


def load_edges(relationships_path) -> List[Mapping[str, object]]:
    path = Path(relationships_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(document, Mapping):
        return list(document.get("relationships", []))
    if isinstance(document, list):
        return list(document)
    raise ValueError(f"unrecognized relationships document shape: {path}")


def load_equipment(canonical_csv) -> Dict[str, str]:
    path = Path(canonical_csv)
    equipment: Dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        name_col = "canonical_name" if "canonical_name" in (reader.fieldnames or []) else None
        type_col = "equipment_type" if "equipment_type" in (reader.fieldnames or []) else None
        if not name_col or not type_col:
            raise ValueError(f"{path}: expected canonical_name + equipment_type columns")
        for row in reader:
            name = (row.get(name_col) or "").strip()
            if name:
                equipment[name] = (row.get(type_col) or "").strip()
    return equipment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the W4 relationship graph (no DB writes).")
    parser.add_argument("--relationships", default=str(DEFAULT_RELATIONSHIPS))
    parser.add_argument("--canonical-equipment", default=str(DEFAULT_CANONICAL_EQUIPMENT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    edges = load_edges(args.relationships)
    equipment = load_equipment(args.canonical_equipment)
    report = validate(edges, equipment)

    out_path = Path(args.report_out)
    if out_path.exists() and not args.overwrite:
        raise SystemExit(f"Output path already exists: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")

    print(f"Graph validation: {report.edge_count} edges over {report.equipment_count} equipment")
    print(f"  passed={report.passed} errors={len(report.errors)} orphans={len(report.orphans)} review_items={len(report.review_items)}")
    print(f"Report written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
