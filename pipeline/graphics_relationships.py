"""Serving relationships from BMS graphic pages (linked-widget evidence).

The mechanical floor plans proved a weak serving source (W6 tiling over both
Floor-2 sheets: 1 conflict-flagged edge). The BMS graphic pages embed the
topology directly: each terminal's page carries linked equipment widgets naming
its upstream unit (VAV/FPTU pages -> "AHU 02 A"; FCU pages -> "OAVAV_02_xx";
OAVAV pages -> "DOAS_22_1"), and water valve points (CHW*/WW*) give the plant
references. This module has two halves:

1. EXTRACTION (vision, injectable): send each screenshot through the
   ``relationship_graphics`` prompt package and collect evidence rows. The LLM
   only *transcribes* what is on the page. The call is injectable via
   ``extract_fn`` so everything below is offline-testable; the live default uses
   the Anthropic SDK directly (``LLM_PROVIDER=anthropic`` lane).

2. FUSION (deterministic, no model): evidence rows -> candidate edges with a
   SOURCE-BASED confidence rubric (W4 showed model self-confidence is a flat
   uncalibrated 0.99):

      0.95 linked widget, values live-synced with the parent's own page
      0.85 linked widget present, unit offline (link is structural BMS config)
      0.55 pattern extrapolation to an uncaptured page (always review)
      0.90/0.85 water refs from valve points + the single-plant default
   Tiling edges merge in as an independent corroborating source at their own
   confidence. Everything below 0.75, conflicted, or vocabulary-flagged routes
   to review. No database writes; output is a versioned snapshot JSON in the
   same edge shape the review agent's stores load.

Validated 2026-07-02 by a dual pass (in-session read vs API run): 14/14 serving
links agreed; divergences (one O->Q title misread, one mis-attributed valve)
route to review. See docs/relationship_graphics_findings.md.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

if __package__:
    from .equipment_vocab import canonical_name, map_equipment_type
    from .normalization import canonical_key
else:  # pragma: no cover - bare-import fallback
    from equipment_vocab import canonical_name, map_equipment_type  # type: ignore
    from normalization import canonical_key  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPT_ROOT = PROJECT_ROOT / "prompts" / "relationship_graphics"
PROMPT_VERSION = "relationship_graphics_v1"
DEFAULT_MODEL = "claude-sonnet-4-6"

REVIEW_THRESHOLD = 0.75
CONF_LIVE = 0.95
CONF_OFFLINE = 0.85
CONF_EXTRAPOLATED = 0.55
CONF_VALVE_AHU = 0.90
CONF_VALVE_TERMINAL = 0.85

# Parents that are named verbatim rather than canonicalized through the floor
# naming convention: plants are building-level instances; the DOAS is a real
# unit outside the scored vocabulary that the graph still needs to connect to.
PASSTHROUGH_PARENTS = {"DOAS", "CHW-PLANT", "HW-PLANT", "COND-PLANT"}

SINGLE_PLANT_NOTE = (
    "single-plant default (Appendix A): one CHW/HW plant instance per building"
)

EVIDENCE_COLUMNS = (
    "source_image",
    "page_title",
    "evidence_kind",
    "subject_raw",
    "object_raw",
    "link_state",
    "detail",
)


@dataclass
class EvidenceRow:
    source_image: str
    page_title: str
    evidence_kind: str
    subject_raw: str
    object_raw: str
    link_state: str
    detail: str = ""


@dataclass
class GraphicsRelationshipResult:
    edges: List[Dict[str, Any]] = field(default_factory=list)
    review_notes: List[Dict[str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Evidence I/O
# --------------------------------------------------------------------------- #
def read_evidence_csv(path: Path) -> List[EvidenceRow]:
    with Path(path).open(encoding="utf-8") as handle:
        return [
            EvidenceRow(**{key: record.get(key, "") for key in EVIDENCE_COLUMNS})
            for record in csv.DictReader(handle)
        ]


def write_evidence_csv(path: Path, rows: Sequence[EvidenceRow]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(EVIDENCE_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: getattr(row, key) for key in EVIDENCE_COLUMNS})


def classify_widget_kind(widget_label: str) -> str:
    """Map a linked-widget label to an evidence kind by equipment prefix."""
    key = (widget_label or "").upper().replace(" ", "").replace("-", "_")
    if key.startswith("AHU"):
        return "linked_widget_ahu"
    if key.startswith("OAVAV"):
        return "linked_widget_oavav"
    if key.startswith("DOAS"):
        return "linked_widget_doas"
    return "linked_widget_other"


def evidence_rows_from_payload(source_image: str, payload: Dict[str, Any]) -> List[EvidenceRow]:
    """Flatten one page's extraction payload into evidence rows."""
    title = str(payload.get("page_title", "") or "")
    rows: List[EvidenceRow] = []
    widgets = payload.get("linked_widgets") or []
    for widget in widgets:
        label = str(widget.get("label", "") or "")
        rows.append(
            EvidenceRow(
                source_image=source_image,
                page_title=title,
                evidence_kind=classify_widget_kind(label),
                subject_raw=title,
                object_raw=label,
                link_state="live_synced" if widget.get("values_live") else "offline",
                detail="; ".join(widget.get("points_shown") or []),
            )
        )
    valves = payload.get("water_valves") or {}
    detail_upper = str(valves.get("detail", "") or "").upper()
    # WW/WWR/WWS = warm (hot) water; no chilled-water token contains a double W.
    chilled = bool(valves.get("chilled_water")) or "CHW" in detail_upper
    hot = bool(valves.get("hot_water")) or "WW" in detail_upper
    if chilled or hot:
        kinds = [kind for kind, present in (("CHW", chilled), ("WW", hot)) if present]
        rows.append(
            EvidenceRow(
                source_image=source_image,
                page_title=title,
                evidence_kind="valve_points",
                subject_raw=title,
                object_raw="+".join(kinds),
                link_state="n/a",
                detail=str(valves.get("detail", "") or ""),
            )
        )
    if not widgets:
        rows.append(
            EvidenceRow(
                source_image=source_image,
                page_title=title,
                evidence_kind="no_linked_widget",
                subject_raw=title,
                object_raw="",
                link_state="n/a",
                detail="no linked equipment widget found on page",
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Fusion: evidence -> edges
# --------------------------------------------------------------------------- #
def _infer_raw_type(label: str) -> str:
    key = (label or "").upper().replace(" ", "").replace("-", "_")
    for candidate in ("VAVRH", "EAVAV", "EVAV", "OAVAV", "FPTU", "FCU", "AHU", "VAV",
                      "DOAS", "IDU", "TF"):
        if key.startswith(candidate):
            return "EAVAV" if candidate == "EVAV" else candidate
    return "UNRESOLVED"


def _canonicalize(raw_label: str, floor_digit: str) -> tuple:
    """Raw BMS label -> ({Type}_{floor}-{unit} canonical, review flag, reason)."""
    label_key = (raw_label or "").strip().upper().replace(" ", "_").replace("-", "_")
    if any(label_key.startswith(prefix.replace("-", "_")) for prefix in PASSTHROUGH_PARENTS):
        return raw_label.strip().replace(" ", "_"), False, ""
    raw_type = _infer_raw_type(raw_label)
    # Same separator/zero-padding-insensitive key the W4 normalization layer
    # uses, so edges land on the committed canonical vocabulary (FCU_2-1, not
    # FCU_2-01).
    key = canonical_key(raw_label)
    mapping = map_equipment_type(raw_type)
    named = canonical_name(key, mapping.mapped_type, floor_digit=floor_digit)
    review = named.review_required or mapping.review_required
    reason = "; ".join(filter(None, (named.review_reason, mapping.review_reason)))
    return named.canonical_name, review, reason


def _edge(
    child_raw: str,
    parent_raw: str,
    ref_type: str,
    link_kind: str,
    confidence: float,
    source_drawing: str,
    evidence_kind: str,
    *,
    floor_digit: str,
    conflict: bool = False,
    conflict_reason: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    child, child_review, child_reason = _canonicalize(child_raw, floor_digit)
    parent, parent_review, parent_reason = _canonicalize(parent_raw, floor_digit)
    review = (
        confidence < REVIEW_THRESHOLD or conflict or child_review or parent_review
    )
    reason = "; ".join(filter(None, (child_reason, parent_reason, notes)))
    return {
        "child": child,
        "parent": parent,
        "ref_type": ref_type,
        "confidence": round(confidence, 2),
        "conflict": conflict,
        "conflict_reason": conflict_reason,
        "review_required": review,
        "review_reason": reason,
        "source_drawing": source_drawing,
        "child_raw": child_raw,
        "parent_raw": parent_raw,
        "link_kind": link_kind,
        "evidence_kind": evidence_kind,
    }


def fuse_evidence(
    rows: Sequence[EvidenceRow],
    *,
    floor_digit: str = "2",
    extrapolate_oavav_doas: bool = True,
) -> GraphicsRelationshipResult:
    """Deterministically fuse evidence rows into candidate relationship edges."""
    result = GraphicsRelationshipResult()
    linked_confidence = {"live_synced": CONF_LIVE, "live": CONF_LIVE, "offline": CONF_OFFLINE}

    doas_parent: Optional[str] = None
    observed_oavav_pages = set()
    oavav_labels_seen = set()

    for row in rows:
        if row.evidence_kind in ("linked_widget_oavav",):
            oavav_labels_seen.add(row.object_raw)
        if _infer_raw_type(row.page_title) == "OAVAV":
            oavav_labels_seen.add(row.page_title)

    for row in rows:
        confidence = linked_confidence.get(row.link_state, CONF_OFFLINE)
        if row.evidence_kind == "linked_widget_ahu":
            result.edges.append(_edge(
                row.page_title, row.object_raw, "airRef", "primary_air",
                confidence, row.source_image, row.evidence_kind,
                floor_digit=floor_digit, notes=row.detail))
        elif row.evidence_kind == "linked_widget_oavav":
            result.edges.append(_edge(
                row.page_title, row.object_raw, "airRef", "outside_air",
                confidence, row.source_image, row.evidence_kind,
                floor_digit=floor_digit,
                notes="OA/ventilation link: the OAVAV feeds this unit's mixed-air side"))
        elif row.evidence_kind == "linked_widget_doas":
            doas_parent = row.object_raw
            observed_oavav_pages.add(row.page_title)
            result.edges.append(_edge(
                row.page_title, row.object_raw, "airRef", "primary_air",
                confidence, row.source_image, row.evidence_kind,
                floor_digit=floor_digit,
                notes="DOAS is outside the scored vocabulary but is the real OA parent"))
        elif row.evidence_kind == "valve_points":
            is_ahu = _infer_raw_type(row.page_title) == "AHU"
            valve_confidence = CONF_VALVE_AHU if is_ahu else CONF_VALVE_TERMINAL
            if "CHW" in row.object_raw:
                result.edges.append(_edge(
                    row.page_title, "CHW-PLANT_1", "chilledWaterRef", "plant",
                    valve_confidence, row.source_image, row.evidence_kind,
                    floor_digit=floor_digit,
                    notes=f"CHW valve points on graphic; {SINGLE_PLANT_NOTE}"))
            if "WW" in row.object_raw:
                result.edges.append(_edge(
                    row.page_title, "HW-PLANT_1", "hotWaterRef", "plant",
                    valve_confidence, row.source_image, row.evidence_kind,
                    floor_digit=floor_digit,
                    notes=f"WW (hot water) valve points on graphic; {SINGLE_PLANT_NOTE}"))
        elif row.evidence_kind in ("no_oa_link", "no_ahu_link"):
            result.review_notes.append({
                "item": row.page_title,
                "question": row.detail or "no upstream linked widget on this page",
                "source": row.source_image,
            })

    if extrapolate_oavav_doas and doas_parent and len(observed_oavav_pages) >= 2:
        evidence_images = ", ".join(sorted(
            row.source_image for row in rows if row.evidence_kind == "linked_widget_doas"))
        for label in sorted(oavav_labels_seen):
            if label in observed_oavav_pages:
                continue
            result.edges.append(_edge(
                label, doas_parent, "airRef", "primary_air",
                CONF_EXTRAPOLATED, evidence_images, "pattern_extrapolation",
                floor_digit=floor_digit,
                notes="extrapolated: every observed OAVAV page links to this DOAS; "
                      "this page has not been captured — confirm before approval"))

    return result


def merge_tiling_edges(
    result: GraphicsRelationshipResult, tiling_doc: Dict[str, Any], *, floor_digit: str = "2"
) -> None:
    """Merge drawing-tiling edges as an independent corroborating source."""
    existing = {(edge["child"], edge["ref_type"]) for edge in result.edges}
    for edge in tiling_doc.get("relationships", []):
        candidate = _edge(
            edge["child"], edge["parent"], edge["ref_type"], "primary_air",
            float(edge.get("confidence", 0.0)),
            str(edge.get("source_drawing", "mechanical drawing (tiled)")),
            "drawing_tiling",
            floor_digit=floor_digit,
            conflict=bool(edge.get("conflict", False)),
            conflict_reason=str(edge.get("conflict_reason", "") or ""),
        )
        if (candidate["child"], candidate["ref_type"]) not in existing:
            result.edges.append(candidate)


def build_snapshot_document(
    result: GraphicsRelationshipResult,
    *,
    property_id: str,
    property_name: str,
    floor: str,
    snapshot_version: str,
    model_id: str,
) -> Dict[str, Any]:
    # Units the graphics pass references that are not in the extraction-derived
    # equipment list (the DOAS and the plants). Per Appendix A these are flagged
    # as candidate equipment for the reviewer to confirm — until then the graph
    # validator's unknown_node findings on them are the expected signal.
    known_children = {edge["child"] for edge in result.edges}
    candidates = sorted({
        edge["parent"] for edge in result.edges
        if edge["parent"] not in known_children and any(
            edge["parent"].upper().replace("-", "_").startswith(prefix.replace("-", "_"))
            for prefix in PASSTHROUGH_PARENTS)
    })
    return {
        "snapshot_version": snapshot_version,
        "property_id": property_id,
        "property_name": property_name,
        "floor": floor,
        "prompt_version": PROMPT_VERSION,
        "model_id": model_id,
        "method": "BMS-graphics linked-widget evidence (vision transcription) fused "
                  "deterministically with a source-based confidence rubric; drawing "
                  "tiling merged as an independent corroborating source",
        "relationship_count": len(result.edges),
        "relationships": result.edges,
        "review_notes": result.review_notes,
        "equipment_candidates": candidates,
    }


# --------------------------------------------------------------------------- #
# Live extraction (Anthropic lane) — kept injectable for tests
# --------------------------------------------------------------------------- #
IMAGE_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _load_prompt_package() -> Dict[str, str]:
    return {
        "system": (PROMPT_ROOT / "v1_system.md").read_text(encoding="utf-8"),
        "user_template": (PROMPT_ROOT / "v1_user_template.md").read_text(encoding="utf-8"),
    }


def _default_extract_fn(model: str) -> Callable[[Path], Dict[str, Any]]:  # pragma: no cover
    """Build the live Anthropic extractor (network; exercised via --run-live)."""
    import base64
    import anthropic

    client = anthropic.Anthropic()
    package = _load_prompt_package()

    def extract(image_path: Path) -> Dict[str, Any]:
        payload = base64.standard_b64encode(image_path.read_bytes()).decode()
        message = client.messages.create(
            model=model,
            max_tokens=4000,
            system=package["system"],
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64",
                                "media_type": IMAGE_MEDIA_TYPES[image_path.suffix.lower()],
                                "data": payload}},
                    {"type": "text",
                     "text": package["user_template"].format(source_filename=image_path.name)},
                ],
            }],
        )
        try:
            from .cost import record_usage
        except ImportError:
            from cost import record_usage
        record_usage(model, getattr(message, "usage", None))
        text = "".join(block.text for block in message.content if block.type == "text")
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start:end + 1])

    return extract


def extract_evidence(
    image_paths: Sequence[Path],
    extract_fn: Callable[[Path], Dict[str, Any]],
) -> List[EvidenceRow]:
    rows: List[EvidenceRow] = []
    for image_path in image_paths:
        try:
            payload = extract_fn(image_path)
        except Exception as error:  # noqa: BLE001 - preserved, never silently repaired
            rows.append(EvidenceRow(
                source_image=image_path.name, page_title="EXTRACTION_FAILED",
                evidence_kind="parse_failure", subject_raw="", object_raw="",
                link_state="n/a", detail=str(error)[:300]))
            continue
        rows.extend(evidence_rows_from_payload(image_path.name, payload))
    return rows


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(
        description="BMS-graphics relationship extraction + fusion (no DB writes)")
    parser.add_argument("--from-evidence-csv", help="fuse an existing evidence CSV (offline)")
    parser.add_argument("--screenshots-dir", help="extract live from screenshots (needs API key)")
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--evidence-csv-out", help="where to save extracted evidence rows")
    parser.add_argument("--tiling-json", help="merge a tiled-drawing relationships JSON")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--property-id", default="b470b97b-4ea7-481c-97b7-22a81a219587")
    parser.add_argument("--property-name", default="msa_orient_building_1")
    parser.add_argument("--floor", default="Floor_02")
    parser.add_argument("--floor-digit", default="2")
    parser.add_argument("--snapshot-version", default="w06")
    parser.add_argument("--no-extrapolation", action="store_true")
    args = parser.parse_args(argv)

    if args.from_evidence_csv:
        rows = read_evidence_csv(Path(args.from_evidence_csv))
        model_id = "n/a (fused from recorded evidence)"
    elif args.screenshots_dir and args.run_live:
        try:
            from .cost import GLOBAL_USAGE
        except ImportError:
            from cost import GLOBAL_USAGE
        GLOBAL_USAGE.reset()
        images = sorted(
            path for path in Path(args.screenshots_dir).iterdir()
            if path.suffix.lower() in IMAGE_MEDIA_TYPES)
        rows = extract_evidence(images, _default_extract_fn(args.model))
        model_id = args.model
        if args.evidence_csv_out:
            write_evidence_csv(Path(args.evidence_csv_out), rows)
    else:
        parser.error("provide --from-evidence-csv, or --screenshots-dir with --run-live")
        return 2

    result = fuse_evidence(
        rows, floor_digit=args.floor_digit,
        extrapolate_oavav_doas=not args.no_extrapolation)
    if args.tiling_json:
        merge_tiling_edges(
            result, json.loads(Path(args.tiling_json).read_text(encoding="utf-8")),
            floor_digit=args.floor_digit)

    document = build_snapshot_document(
        result, property_id=args.property_id, property_name=args.property_name,
        floor=args.floor, snapshot_version=args.snapshot_version, model_id=model_id)
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    review_count = sum(1 for edge in result.edges if edge["review_required"])
    print(f"wrote {len(result.edges)} edges ({review_count} review) -> {output_path}")

    if args.run_live:
        try:
            from .cost import write_run_metrics
        except ImportError:
            from cost import write_run_metrics
        metrics_path = output_path.parent / "relationships_run_metrics.json"
        write_run_metrics(
            metrics_path,
            run={"command": "graphics_relationships", "model": model_id, "floor": args.floor},
            counts={
                "edges_total": len(result.edges),
                "edges_review_required": review_count,
                "edges_confident": len(result.edges) - review_count,
            },
        )
        print(f"run metrics -> {metrics_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
