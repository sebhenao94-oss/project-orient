"""Relationship graph validator for the current Project ORIENT artifacts.

Pure validation of a list of relationship edges against the equipment list they
should reference. The core ``validate`` function does no I/O; a thin CLI wrapper
reads the relationships JSON and the canonical equipment CSV and writes a report.

Checks (each finding carries a machine-readable ``check_id`` and offending ids):

* ``unknown_node``        — an edge endpoint not present in the equipment list
                            (aggregated by unresolved endpoint).
* ``ambiguous_node``      — canonical/raw aliases resolve to different units.
* ``multiple_air_parents``— a terminal unit with more than one ``airRef`` parent.
* ``cycle``               — a cycle in the airRef/systemRef parent graph.
* ``ref_type_sanity``     — ``airRef`` child must be a terminal and parent an air
                            source (AHU/DOAS/MAU); water refs must point to a plant.

Non-error findings:

* ``orphan_terminal``     — a terminal with no accepted ``airRef``.
* ``review_item``         — an edge with confidence < 0.75, ``conflict=true``,
                            or an upstream ``review_required=true`` flag.
* ``unresolved_endpoint`` — a review item for a missing/candidate endpoint.

Canonical, topic-raw, and drawing-raw labels share the same separator- and
zero-padding-insensitive match key used by normalization/discrepancy joining.
An edge is accepted into topology checks only when both endpoints resolve
unambiguously and ``conflict`` is false. The report ``passed`` flag is true only
when there are no errors and no orphan terminals; review items remain visible
without by themselves failing an otherwise complete graph.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

if __package__:
    from .normalization import NormalizationInputError, canonical_key as normalized_key
else:
    from normalization import NormalizationInputError, canonical_key as normalized_key


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELATIONSHIPS = (
    PROJECT_ROOT / "data" / "snapshots" / "w06" / "relationships_floor_02.json"
)
DEFAULT_CANONICAL_EQUIPMENT = (
    PROJECT_ROOT / "data" / "snapshots" / "w06" / "canonical_equipment_floor_02.csv"
)
DEFAULT_REPORT_OUT = (
    PROJECT_ROOT / "data" / "snapshots" / "w06" / "graph_validation_floor_02.json"
)

LOW_CONFIDENCE_THRESHOLD = 0.75

# OAVAV included: on this site the outside-air VAVs serve ventilation air
# downstream to the FCUs (each FCU graphic carries its upstream OAVAV linked
# widget; see docs/relationship_graphics_findings.md). A plain VAV still
# cannot be an air parent.
AIR_SOURCE_TYPES = {"AHU", "DOAS", "MAU", "OAVAV"}
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


@dataclass(frozen=True)
class EquipmentCatalog:
    """Canonical equipment plus safe normalized aliases from source evidence."""

    equipment: Dict[str, str]
    alias_to_canonical: Dict[str, str]
    ambiguous_aliases: Dict[str, Tuple[str, ...]]


@dataclass(frozen=True)
class EndpointResolution:
    status: str  # "resolved" | "unresolved" | "ambiguous"
    canonical_name: str = ""
    labels: Tuple[str, ...] = field(default_factory=tuple)
    candidates: Tuple[str, ...] = field(default_factory=tuple)
    declared_candidate: bool = False
    used_alias: bool = False


@dataclass
class EndpointIssue:
    labels: Set[str] = field(default_factory=set)
    edges: Set[str] = field(default_factory=set)
    candidates: Set[str] = field(default_factory=set)
    declared_candidate: bool = False


@dataclass
class GraphValidationReport:
    edge_count: int
    equipment_count: int
    accepted_edge_count: int = 0
    alias_resolution_count: int = 0
    unresolved_endpoint_count: int = 0
    ambiguous_endpoint_count: int = 0
    errors: List[Finding] = field(default_factory=list)
    orphans: List[Finding] = field(default_factory=list)
    review_items: List[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors and not self.orphans

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
            "accepted_edge_count": self.accepted_edge_count,
            "equipment_count": self.equipment_count,
            "alias_resolution_count": self.alias_resolution_count,
            "unresolved_endpoint_count": self.unresolved_endpoint_count,
            "ambiguous_endpoint_count": self.ambiguous_endpoint_count,
            "passed": self.passed,
            "error_count": len(self.errors),
            "orphan_count": len(self.orphans),
            "review_item_count": len(self.review_items),
            "errors": dump(self.errors),
            "orphans": dump(self.orphans),
            "review_items": dump(self.review_items),
        }


def _match_key(label: str) -> str:
    try:
        return normalized_key(label)
    except (NormalizationInputError, TypeError, AttributeError):
        return ""


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _alias_targets(
    equipment: Mapping[str, str],
    aliases: Optional[Mapping[str, str]],
    ambiguous_aliases: Optional[Mapping[str, Sequence[str]]],
) -> Dict[str, Set[str]]:
    """Build normalized alias -> canonical target sets without choosing a collision."""
    targets: Dict[str, Set[str]] = {}
    for canonical_name in equipment:
        key = _match_key(canonical_name)
        if key:
            targets.setdefault(key, set()).add(canonical_name)
    for alias, canonical_name in (aliases or {}).items():
        key = _match_key(alias)
        if key and canonical_name in equipment:
            targets.setdefault(key, set()).add(canonical_name)
    for alias, canonical_names in (ambiguous_aliases or {}).items():
        key = _match_key(alias)
        if not key:
            continue
        targets.setdefault(key, set()).update(
            canonical_name for canonical_name in canonical_names if canonical_name in equipment
        )
    return targets


def _resolve_endpoint(
    label: str,
    raw_label: str,
    equipment: Mapping[str, str],
    alias_targets: Mapping[str, Set[str]],
    candidate_keys: Set[str],
) -> EndpointResolution:
    labels = tuple(dict.fromkeys(value for value in (label, raw_label) if value))
    targets: Set[str] = set()
    for value in labels:
        if value in equipment:
            targets.add(value)
        key = _match_key(value)
        if key:
            targets.update(alias_targets.get(key, set()))

    declared_candidate = any(_match_key(value) in candidate_keys for value in labels)
    if len(targets) == 1:
        canonical_name = next(iter(targets))
        return EndpointResolution(
            status="resolved",
            canonical_name=canonical_name,
            labels=labels,
            candidates=(canonical_name,),
            declared_candidate=declared_candidate,
            used_alias=(not label or label != canonical_name),
        )
    if len(targets) > 1:
        return EndpointResolution(
            status="ambiguous",
            labels=labels,
            candidates=tuple(sorted(targets)),
            declared_candidate=declared_candidate,
        )
    return EndpointResolution(
        status="unresolved",
        labels=labels,
        declared_candidate=declared_candidate,
    )


def validate(
    edges: Sequence[Mapping[str, object]],
    equipment: Mapping[str, str],
    aliases: Optional[Mapping[str, str]] = None,
    ambiguous_aliases: Optional[Mapping[str, Sequence[str]]] = None,
    equipment_candidates: Iterable[str] = (),
) -> GraphValidationReport:
    """Validate edges against canonical equipment and its raw-label aliases.

    Alias collisions and disagreements between an edge's canonical and raw
    endpoint labels remain blockers; the validator never picks one target from
    multiple possible canonical units. Declared ``equipment_candidates`` remain
    unresolved until they are present in the canonical equipment artifact.
    """
    report = GraphValidationReport(edge_count=len(edges), equipment_count=len(equipment))

    targets_by_alias = _alias_targets(equipment, aliases, ambiguous_aliases)
    candidate_keys = {_match_key(value) for value in equipment_candidates if _match_key(value)}
    air_parents: Dict[str, List[str]] = {}
    parent_of: Dict[str, Set[str]] = {}
    unresolved: Dict[str, EndpointIssue] = {}
    ambiguous: Dict[str, EndpointIssue] = {}

    def record_issue(
        bucket: Dict[str, EndpointIssue],
        resolution: EndpointResolution,
        role: str,
        edge_label: str,
    ) -> None:
        labels = resolution.labels or (f"<blank {role}>",)
        identity = _match_key(labels[0]) or labels[0].upper()
        issue = bucket.setdefault(identity, EndpointIssue())
        issue.labels.update(labels)
        issue.edges.add(edge_label)
        issue.candidates.update(resolution.candidates)
        issue.declared_candidate = issue.declared_candidate or resolution.declared_candidate

    for edge in edges:
        child = str(edge.get("child", "")).strip()
        parent = str(edge.get("parent", "")).strip()
        child_raw = str(edge.get("child_raw", "") or "").strip()
        parent_raw = str(edge.get("parent_raw", "") or "").strip()
        ref_type = str(edge.get("ref_type", "")).strip()
        edge_label = f"{child or '<blank>'} -> {parent or '<blank>'} ({ref_type or '<blank>'})"

        child_resolution = _resolve_endpoint(
            child, child_raw, equipment, targets_by_alias, candidate_keys
        )
        parent_resolution = _resolve_endpoint(
            parent, parent_raw, equipment, targets_by_alias, candidate_keys
        )
        for role, resolution in (("child", child_resolution), ("parent", parent_resolution)):
            if resolution.status == "unresolved":
                record_issue(unresolved, resolution, role, edge_label)
            elif resolution.status == "ambiguous":
                record_issue(ambiguous, resolution, role, edge_label)
            elif resolution.used_alias:
                report.alias_resolution_count += 1

        resolved_child = child_resolution.canonical_name
        resolved_parent = parent_resolution.canonical_name

        # Type sanity is still checked for each endpoint that resolved; a missing
        # opposite endpoint does not suppress a useful local type finding.
        child_type = equipment.get(resolved_child, "")
        parent_type = equipment.get(resolved_parent, "")
        if ref_type == "airRef":
            if resolved_child and not is_terminal(child_type):
                report.errors.append(
                    Finding("ref_type_sanity", "error", f"airRef child '{resolved_child}' is not a terminal ({child_type})", [resolved_child])
                )
            if resolved_parent and not is_air_source(parent_type):
                report.errors.append(
                    Finding("ref_type_sanity", "error", f"airRef parent '{resolved_parent}' is not an air source ({parent_type})", [resolved_parent])
                )
        elif ref_type in WATER_REF_TYPES:
            if resolved_parent and not is_plant(parent_type):
                report.errors.append(
                    Finding("ref_type_sanity", "error", f"{ref_type} parent '{resolved_parent}' is not a plant ({parent_type})", [resolved_parent])
                )

        # Preserve every upstream reason for human review, not only the numeric
        # threshold subset. A conflict is never accepted into graph topology.
        confidence = edge.get("confidence")
        conflict = _to_bool(edge.get("conflict", False))
        review_required = _to_bool(edge.get("review_required", False))
        try:
            low = confidence is not None and float(confidence) < LOW_CONFIDENCE_THRESHOLD
        except (TypeError, ValueError):
            low = False
        if low or conflict or review_required:
            reason = []
            if low:
                reason.append(f"confidence {confidence} < {LOW_CONFIDENCE_THRESHOLD}")
            if conflict:
                reason.append("conflict=true")
            if review_required and not (low or conflict):
                reason.append("review_required=true")
            upstream_reason = str(edge.get("review_reason", "") or "").strip()
            if upstream_reason:
                reason.append(upstream_reason)
            report.review_items.append(
                Finding("review_item", "review", f"edge {child} -> {parent} ({ref_type}): {', '.join(reason)}", [child, parent])
            )

        if (
            child_resolution.status == "resolved"
            and parent_resolution.status == "resolved"
            and not conflict
        ):
            report.accepted_edge_count += 1
            if ref_type == "airRef":
                air_parents.setdefault(resolved_child, []).append(resolved_parent)
            if resolved_child and resolved_parent:
                parent_of.setdefault(resolved_child, set()).add(resolved_parent)

    # Aggregate repeated references to the same absent endpoint. Candidate nodes
    # remain errors until approved into canonical equipment, and also become
    # explicit review work instead of 31 indistinguishable per-edge failures.
    report.unresolved_endpoint_count = len(unresolved)
    for identity in sorted(unresolved):
        issue = unresolved[identity]
        labels = sorted(issue.labels)
        candidate_note = (
            "declared in equipment_candidates but not approved into canonical equipment"
            if issue.declared_candidate
            else "not present in canonical equipment or its source-label aliases"
        )
        message = (
            f"unresolved endpoint {labels}: {candidate_note}; "
            f"referenced by {len(issue.edges)} edge(s)"
        )
        report.errors.append(Finding("unknown_node", "error", message, labels))
        report.review_items.append(Finding("unresolved_endpoint", "review", message, labels))

    report.ambiguous_endpoint_count = len(ambiguous)
    for identity in sorted(ambiguous):
        issue = ambiguous[identity]
        labels = sorted(issue.labels)
        targets = sorted(issue.candidates)
        message = (
            f"endpoint labels {labels} resolve to multiple canonical units {targets}; "
            f"referenced by {len(issue.edges)} edge(s)"
        )
        report.errors.append(Finding("ambiguous_node", "error", message, labels + targets))
        report.review_items.append(
            Finding("endpoint_resolution_conflict", "review", message, labels + targets)
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

    # Orphans are reported separately from structural errors, but they are graph
    # completion blockers and therefore keep ``passed`` false.
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


def load_relationship_document(relationships_path) -> Mapping[str, Any]:
    path = Path(relationships_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(document, Mapping):
        relationships = document.get("relationships", [])
        if not isinstance(relationships, list):
            raise ValueError(f"{path}: relationships must be a list")
        return document
    if isinstance(document, list):
        return {"relationships": document, "equipment_candidates": []}
    raise ValueError(f"unrecognized relationships document shape: {path}")


def load_edges(relationships_path) -> List[Mapping[str, object]]:
    return list(load_relationship_document(relationships_path).get("relationships", []))


def load_equipment_catalog(canonical_csv) -> EquipmentCatalog:
    path = Path(canonical_csv)
    equipment: Dict[str, str] = {}
    alias_targets: Dict[str, Set[str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        name_col = "canonical_name" if "canonical_name" in (reader.fieldnames or []) else None
        type_col = "equipment_type" if "equipment_type" in (reader.fieldnames or []) else None
        if not name_col or not type_col:
            raise ValueError(f"{path}: expected canonical_name + equipment_type columns")
        for row in reader:
            name = (row.get(name_col) or "").strip()
            if name:
                equipment_type = (row.get(type_col) or "").strip()
                existing_type = equipment.get(name)
                if existing_type is not None and existing_type != equipment_type:
                    raise ValueError(
                        f"{path}: canonical equipment {name!r} has conflicting types "
                        f"{existing_type!r} and {equipment_type!r}"
                    )
                equipment[name] = equipment_type
                for alias in (
                    name,
                    (row.get("topics_raw_label") or "").strip(),
                    (row.get("drawing_raw_label") or "").strip(),
                ):
                    key = _match_key(alias)
                    if key:
                        alias_targets.setdefault(key, set()).add(name)

    alias_to_canonical: Dict[str, str] = {}
    ambiguous_aliases: Dict[str, Tuple[str, ...]] = {}
    for key, targets in alias_targets.items():
        if len(targets) == 1:
            alias_to_canonical[key] = next(iter(targets))
        else:
            ambiguous_aliases[key] = tuple(sorted(targets))
    return EquipmentCatalog(equipment, alias_to_canonical, ambiguous_aliases)


def load_equipment(canonical_csv) -> Dict[str, str]:
    """Backward-compatible canonical-name -> type loader."""
    return load_equipment_catalog(canonical_csv).equipment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the current relationship graph (read-only inputs; no DB writes)."
    )
    parser.add_argument("--relationships", default=str(DEFAULT_RELATIONSHIPS))
    parser.add_argument("--canonical-equipment", default=str(DEFAULT_CANONICAL_EQUIPMENT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    relationships_document = load_relationship_document(args.relationships)
    edges = list(relationships_document.get("relationships", []))
    candidates = relationships_document.get("equipment_candidates", [])
    if not isinstance(candidates, list):
        raise ValueError(f"{args.relationships}: equipment_candidates must be a list")
    catalog = load_equipment_catalog(args.canonical_equipment)
    report = validate(
        edges,
        catalog.equipment,
        aliases=catalog.alias_to_canonical,
        ambiguous_aliases=catalog.ambiguous_aliases,
        equipment_candidates=candidates,
    )

    out_path = Path(args.report_out)
    if out_path.exists() and not args.overwrite:
        raise SystemExit(f"Output path already exists: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")

    print(f"Graph validation: {report.edge_count} edges over {report.equipment_count} equipment")
    print(
        f"  accepted_edges={report.accepted_edge_count} "
        f"alias_resolutions={report.alias_resolution_count} "
        f"unresolved_endpoints={report.unresolved_endpoint_count}"
    )
    print(f"  passed={report.passed} errors={len(report.errors)} orphans={len(report.orphans)} review_items={len(report.review_items)}")
    print(f"Report written: {out_path}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
