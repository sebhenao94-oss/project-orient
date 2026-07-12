"""LLM-assisted topics -> equipment parser (addresses Sourav's W4 review #8).

Replaces the deterministic ``<floor>/<equipment>/<point>`` path parser as the
PRIMARY way to infer equipment from BMS topic names. An LLM groups points into
equipment units without assuming a fixed segment order / separator / prefix; the
old deterministic path-parse is retained only as a VALIDATION cross-check that
flags disagreements for human review (deterministic rules for validation and
post-processing, not primary extraction).

The LLM call is injectable via ``parse_fn`` so the grouping-validation-snapshot
core is fully offline-testable with a fake. The default wires the Anthropic
client at the cheapest text tier (Haiku). Items the text parser flags for review
get a VISION SECOND PASS (Sourav #13): the unit's source screenshot is routed to
a vision model before falling back to human review. Agreement clears explicitly
type-only flags; all other ambiguity stays in review with the result recorded.

    python -m pipeline.topics_parser --topics-csv <csv> --output-path <out> \
        --property-id <id> --property-name <name> --run-live \
        [--vision-escalate-dir downloads/Floor_2 --example-image-dir downloads/Floor_2]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

try:
    from .cost import GLOBAL_USAGE, record_usage, write_run_metrics
except ImportError:  # pragma: no cover - bare-import fallback
    from cost import GLOBAL_USAGE, record_usage, write_run_metrics

DEFAULT_TOPICS_MODEL = "claude-haiku-4-5"
DEFAULT_EQUIPMENT_TYPE_CONTEXT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "equipment_type_context.md"
)

TOPICS_EQUIPMENT_SNAPSHOT_COLUMNS = (
    "snapshot_version",
    "property_id",
    "property_name",
    "floor",
    "raw_equipment_context",
    "raw_label",
    "inferred_raw_type",
    "confidence",
    "topic_count",
    "source_topics",
    "source_method",
    "review_required",
    "review_reason",
)

# Known HVAC types offered to the model (aligned with the equipment vocabulary).
KNOWN_EQUIPMENT_TYPES = (
    "AHU", "DOAS", "MAU", "FCU", "VAV", "VAV-RH-HW", "VAV-RH-ELEC",
    "FPTU-HW", "FPTU-ELEC", "CHW-PLANT", "HW-PLANT", "COND-PLANT",
    "VENTILATION", "ERV",
)


@dataclass
class ParsedTopicEquipment:
    """One equipment unit inferred from a group of topic names."""

    raw_context: str
    raw_label: str
    equipment_type: str
    floor: str
    source_topics: List[str] = field(default_factory=list)
    confidence: Optional[float] = None
    review_required: bool = False
    review_reason: str = ""


class TopicsCoverageError(ValueError):
    """Raised when model-assigned topics do not exactly cover the input multiset."""

    _MAX_EXAMPLES_PER_CATEGORY = 3
    _MAX_TOPIC_REPR_CHARS = 120

    def __init__(
        self,
        *,
        missing: Counter,
        unexpected: Counter,
        duplicates: Counter,
    ) -> None:
        self.missing = Counter(missing)
        self.unexpected = Counter(unexpected)
        self.duplicates = Counter(duplicates)
        details = []
        for label, counts in (
            ("missing", self.missing),
            ("unexpected", self.unexpected),
            ("duplicate", self.duplicates),
        ):
            if counts:
                details.append(self._bounded_detail(label, counts))
        super().__init__("topic coverage mismatch: " + "; ".join(details))

    @classmethod
    def _bounded_detail(cls, label: str, counts: Counter) -> str:
        examples = []
        for topic, count in sorted(counts.items(), key=lambda item: str(item[0]))[
            : cls._MAX_EXAMPLES_PER_CATEGORY
        ]:
            rendered = repr(topic)
            if len(rendered) > cls._MAX_TOPIC_REPR_CHARS:
                rendered = rendered[: cls._MAX_TOPIC_REPR_CHARS - 3] + "..."
            examples.append(f"{rendered} x{count}")
        remaining = len(counts) - len(examples)
        if remaining:
            examples.append(f"+{remaining} more distinct")
        return (
            f"{label} {sum(counts.values())} assignment(s) across "
            f"{len(counts)} topic(s) [{', '.join(examples)}]"
        )


# parse_fn seam: a list of topic names -> parsed equipment units. Injectable so
# tests exercise the validation/snapshot core without a live model.
TopicsParseFn = Callable[[Sequence[str]], List[ParsedTopicEquipment]]


def validate_topic_coverage(
    topic_names: Sequence[str], units: Sequence[ParsedTopicEquipment]
) -> None:
    """Require the model output to assign every input topic exactly once.

    Topic names are compared as a multiset so repeated rows in the input remain
    repeated obligations. A known topic assigned more times than it appeared is
    reported as a duplicate; a name absent from the input is unexpected.
    """
    expected = Counter(topic_names)
    assigned = Counter(topic for unit in units for topic in unit.source_topics)
    if expected == assigned:
        return

    missing = expected - assigned
    excess = assigned - expected
    unexpected = Counter(
        {topic: count for topic, count in excess.items() if topic not in expected}
    )
    duplicates = Counter(
        {topic: count for topic, count in excess.items() if topic in expected}
    )
    raise TopicsCoverageError(
        missing=missing,
        unexpected=unexpected,
        duplicates=duplicates,
    )


# --------------------------------------------------------------------------- #
# Deterministic path parse — kept ONLY as a validation cross-check
# --------------------------------------------------------------------------- #
_DEVICE_PREFIX = re.compile(r"^DEV\d+_")


def _path_context(topic_path: str, floor_prefix: str) -> Optional[str]:
    """Old logic: the ``<floor>/<context>/<point>`` middle segment, or None."""
    parts = topic_path.split("/")
    if len(parts) < 3 or parts[0] != floor_prefix or not parts[1]:
        return None
    return _DEVICE_PREFIX.sub("", parts[1])


def _type_base(equipment_type: str) -> str:
    return re.split(r"[-_]", equipment_type.strip())[0].upper() if equipment_type else ""


def validate_against_paths(
    units: List[ParsedTopicEquipment], floor_prefix: str
) -> List[ParsedTopicEquipment]:
    """Flag units whose LLM grouping/type disagrees with the deterministic parse.

    A unit is routed to review when: its topics do not fit the standard path
    shape at all; its topics span more than one path context (a merge the LLM
    may have gotten wrong); or its type is not evident in the path label.
    """
    for unit in units:
        contexts = {
            ctx
            for ctx in (_path_context(t, floor_prefix) for t in unit.source_topics)
            if ctx
        }
        reasons: List[str] = []
        if not contexts:
            reasons.append("no deterministic path match (non-standard topic format)")
        elif len(contexts) > 1:
            reasons.append(f"topics span multiple path contexts {sorted(contexts)}")
        else:
            label = next(iter(contexts))
            base = _type_base(unit.equipment_type)
            if base and base not in label.upper() and unit.equipment_type != "UNRESOLVED":
                reasons.append(f"type '{unit.equipment_type}' not evident in path label '{label}'")
        if reasons:
            unit.review_required = True
            existing = [unit.review_reason] if unit.review_reason else []
            unit.review_reason = "; ".join(existing + reasons)
    return units


def parse_topics_equipment(
    topic_names: Sequence[str],
    *,
    floor_prefix: str,
    parse_fn: TopicsParseFn,
) -> List[ParsedTopicEquipment]:
    """Primary LLM parse, then the deterministic validation cross-check."""
    units = list(parse_fn(list(topic_names)))
    validate_topic_coverage(topic_names, units)
    return validate_against_paths(units, floor_prefix)


# --------------------------------------------------------------------------- #
# Default LLM parse_fn (real path; not exercised in the offline tests)
# --------------------------------------------------------------------------- #
TOPICS_SYSTEM_PROMPT = (
    "You are an HVAC BMS analyst. You are given a list of BMS point/topic names "
    "for one building floor. Each name encodes the equipment it belongs to plus a "
    "measured point. Group the topics that belong to the SAME physical equipment "
    "unit and identify that unit.\n\n"
    "Do NOT assume a fixed segment order, separator, or prefix — infer the "
    "structure from the names themselves; buildings differ.\n\n"
    "Every exact input topic name must appear in source_topics exactly once "
    "across the complete response. Do not omit, invent, or repeat a topic.\n\n"
    "For each distinct equipment unit return a JSON object with: raw_context (the "
    "identifying substring as it appears), raw_label (a cleaned label), "
    "equipment_type (one of: " + ", ".join(KNOWN_EQUIPMENT_TYPES) + "; use "
    "\"UNRESOLVED\" if unclear), floor (if inferable, else \"\"), source_topics "
    "(the exact topic names in this unit), confidence (0.0-1.0), review_required "
    "(true if ambiguous/conflicting/unsure), and review_reason (short, when "
    "review_required). Return ONLY a JSON array of these objects, no prose."
)

TOPICS_USER_TEMPLATE = (
    "Property: {property_name}\nFloor: {floor}\nTopic names ({count}):\n{topics}\n\n"
    "Return the JSON array."
)


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
        t = t.strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    return t.strip()


def _opt_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_units_json(text: str, default_floor: str) -> List[ParsedTopicEquipment]:
    """Parse the model's JSON array into ParsedTopicEquipment (tolerates fences)."""
    payload = json.loads(_strip_code_fence(text))
    units: List[ParsedTopicEquipment] = []
    for obj in payload:
        units.append(
            ParsedTopicEquipment(
                raw_context=str(obj.get("raw_context", "")),
                raw_label=str(obj.get("raw_label", obj.get("raw_context", ""))),
                equipment_type=str(obj.get("equipment_type", "UNRESOLVED")),
                floor=str(obj.get("floor") or default_floor),
                source_topics=[str(t) for t in obj.get("source_topics", [])],
                confidence=_opt_float(obj.get("confidence")),
                review_required=bool(obj.get("review_required", False)),
                review_reason=str(obj.get("review_reason", "")),
            )
        )
    return units


def anthropic_topics_parse_fn(
    *,
    property_name: str,
    floor: str,
    model: str = DEFAULT_TOPICS_MODEL,
    client: Optional[Any] = None,
) -> TopicsParseFn:
    """Default parse_fn bound to run context; wires the Anthropic client (Haiku)."""
    try:
        from .anthropic_client import AnthropicMessagesClient
    except ImportError:  # pragma: no cover - bare-import fallback
        from anthropic_client import AnthropicMessagesClient  # type: ignore

    def _fn(topic_names: Sequence[str]) -> List[ParsedTopicEquipment]:
        active = client or AnthropicMessagesClient.from_environment()
        user = TOPICS_USER_TEMPLATE.format(
            property_name=property_name,
            floor=floor,
            count=len(topic_names),
            topics="\n".join(topic_names),
        )
        messages = [
            {"role": "system", "content": TOPICS_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        response = asyncio.run(active.chat_completions_create(model=model, messages=messages))
        record_usage(model, response.get("usage"))
        text = response["choices"][0]["message"]["content"]
        return parse_units_json(text, floor)

    return _fn


# --------------------------------------------------------------------------- #
# Snapshot writer (per-floor; enriched with confidence + source topics)
# --------------------------------------------------------------------------- #
def write_topics_equipment_snapshot(
    units: List[ParsedTopicEquipment],
    output_path: Any,
    *,
    property_id: str,
    property_name: str,
    floor: str,
    snapshot_version: str,
    source_method: str = "llm_assisted",
    overwrite: bool = False,
) -> Path:
    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists; pass overwrite=True")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TOPICS_EQUIPMENT_SNAPSHOT_COLUMNS)
        writer.writeheader()
        for unit in sorted(units, key=lambda u: (u.raw_label.lower(), u.raw_label)):
            writer.writerow(
                {
                    "snapshot_version": snapshot_version,
                    "property_id": property_id,
                    "property_name": property_name,
                    "floor": floor,
                    "raw_equipment_context": unit.raw_context,
                    "raw_label": unit.raw_label,
                    "inferred_raw_type": unit.equipment_type,
                    "confidence": "" if unit.confidence is None else f"{unit.confidence:.3f}",
                    "topic_count": len(unit.source_topics),
                    "source_topics": ";".join(unit.source_topics),
                    "source_method": source_method,
                    "review_required": "true" if unit.review_required else "false",
                    "review_reason": unit.review_reason,
                }
            )
    return output_path


# --------------------------------------------------------------------------- #
# Vision second pass for review-flagged items (Sourav #13)
# --------------------------------------------------------------------------- #
# image path + target unit -> detected equipment_type (or None). Injectable so the escalation
# logic is offline-testable without a live vision model.
VisionExtractFn = Callable[[Path, ParsedTopicEquipment], Optional[str]]


def _append_reason(existing: str, extra: str) -> str:
    return f"{existing}; {extra}" if existing else extra


def _normalize_for_match(value: str) -> str:
    """Strip provenance/separators/zero-padding for conservative label matching."""
    without_prefix = _DEVICE_PREFIX.sub("", value or "").upper()
    tokens = re.findall(r"[A-Z]+|\d+", without_prefix)
    return "".join(str(int(token)) if token.isdigit() else token for token in tokens)


def resolve_screenshot(unit: ParsedTopicEquipment, image_dir: Path) -> Optional[Path]:
    """Find the source screenshot for a unit by fuzzy-matching its identifier."""
    image_dir = Path(image_dir)
    if not image_dir.exists():
        return None
    targets = {_normalize_for_match(unit.raw_context), _normalize_for_match(unit.raw_label)}
    targets.discard("")
    for path in sorted(image_dir.iterdir()):
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and _normalize_for_match(path.stem) in targets:
            return path
    return None


def apply_vision_result(unit: ParsedTopicEquipment, detected_type: Optional[str]) -> None:
    """Merge a vision second-pass result into a flagged unit."""
    if detected_type is None:
        unit.review_reason = _append_reason(unit.review_reason, "vision second pass found no equipment")
        return
    if detected_type.upper() == (unit.equipment_type or "").upper():
        # Vision can settle a type question, but not grouping/floor/identity.
        type_only = _review_reasons_are_explicitly_type_only(unit.review_reason)
        unit.review_reason = _append_reason(unit.review_reason, f"vision second pass CONFIRMED {detected_type}")
        if type_only:
            unit.review_required = False
        else:
            unit.review_required = True
            unit.review_reason = _append_reason(
                unit.review_reason,
                "review retained because prior reasons were not exclusively type-only",
            )
    else:
        unit.review_required = True
        unit.review_reason = _append_reason(
            unit.review_reason, f"vision second pass CONFLICT: sees {detected_type}, topics say {unit.equipment_type}"
        )


def _review_reasons_are_explicitly_type_only(review_reason: str) -> bool:
    reasons = [reason.strip() for reason in (review_reason or "").split(";") if reason.strip()]
    return bool(reasons) and all(_is_explicit_type_only_reason(reason) for reason in reasons)


def _is_explicit_type_only_reason(reason: str) -> bool:
    normalized = " ".join(reason.strip().lower().split())
    if re.fullmatch(r"type '.+' not evident in path label '.+'", normalized):
        return True
    if re.search(
        r"\b(?:group(?:ing|ed|s)?|floor|identity|path|context(?:s)?|"
        r"merge(?:d|s|ing)?|split(?:s|ting)?|span(?:s|ned|ning)?)\b",
        normalized,
    ):
        return False
    if (
        normalized == "type-only"
        or normalized == "[type-only]"
        or normalized.startswith("type-only:")
        or normalized.startswith("[type-only]")
    ):
        return True
    has_type_subject = bool(re.search(r"\b(?:equipment )?type\b", normalized))
    has_type_uncertainty = bool(
        re.search(
            r"\b(?:ambiguous|ambiguity|uncertain|uncertainty|unclear|unresolved|"
            r"unknown|mismatch|conflict|disagreement)\b|low confidence|not evident",
            normalized,
        )
    )
    return has_type_subject and has_type_uncertainty


def vision_second_pass(
    units: List[ParsedTopicEquipment],
    *,
    image_dir: Path,
    extract_fn: VisionExtractFn,
    resolve_image: Optional[Callable[[ParsedTopicEquipment], Optional[Path]]] = None,
) -> List[ParsedTopicEquipment]:
    """Route each review-flagged unit to a vision model before human review."""
    resolve = resolve_image or (lambda u: resolve_screenshot(u, image_dir))
    for unit in units:
        if not unit.review_required:
            continue
        image = resolve(unit)
        if image is None:
            unit.review_reason = _append_reason(unit.review_reason, "no screenshot for vision second pass")
            continue
        apply_vision_result(unit, extract_fn(image, unit))
    return units


def select_vision_candidate_type(
    unit: ParsedTopicEquipment, candidates: Sequence[Any]
) -> Optional[str]:
    """Return a type only for one candidate that labels the requested unit."""
    targets = {
        _normalize_for_match(unit.raw_context),
        _normalize_for_match(unit.raw_label),
    }
    targets.discard("")
    matches = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            raw_label = candidate.get("raw_label", "")
            canonical_name = candidate.get("canonical_name", "")
        else:
            raw_label = getattr(candidate, "raw_label", "")
            canonical_name = getattr(candidate, "canonical_name", "")
        labels = {
            _normalize_for_match(str(raw_label or "")),
            _normalize_for_match(str(canonical_name or "")),
        }
        labels.discard("")
        if targets.intersection(labels):
            matches.append(candidate)

    if len(matches) != 1:
        return None
    candidate = matches[0]
    equipment_type = (
        candidate.get("equipment_type")
        if isinstance(candidate, dict)
        else getattr(candidate, "equipment_type", None)
    )
    if equipment_type is None:
        return None
    value = equipment_type.value if hasattr(equipment_type, "value") else str(equipment_type)
    return value.strip() or None


def default_vision_extract_fn(
    *,
    prompt_root: Path,
    example_image_dir: Path,
    model: str,
    type_context_path: Optional[Path] = DEFAULT_EQUIPMENT_TYPE_CONTEXT_PATH,
) -> VisionExtractFn:
    """Wire the real vision second pass to the equipment image extractor (escalation entry)."""
    try:
        from .extraction import extract_equipment_batch, _prepared_image_records_from_dir
        from .equipment_prompts import load_equipment_prompt_package
    except ImportError:  # pragma: no cover
        from extraction import extract_equipment_batch, _prepared_image_records_from_dir  # type: ignore
        from equipment_prompts import load_equipment_prompt_package  # type: ignore
    import shutil, tempfile

    package = load_equipment_prompt_package(
        "equipment_extraction_v4",
        Path(prompt_root),
        Path(example_image_dir),
        type_context_path=type_context_path,
    )

    def _fn(image_path: Path, unit: ParsedTopicEquipment) -> Optional[str]:
        with tempfile.TemporaryDirectory(prefix="orient_vision_") as tmp:
            shutil.copy2(image_path, Path(tmp) / Path(image_path).name)
            records = _prepared_image_records_from_dir(tmp, floor=unit.floor)
            results = asyncio.run(extract_equipment_batch(
                image_records=records, prompt_package=package, model=model, max_concurrency=1))
            candidates = []
            for res in results:
                if res.status == "succeeded" and res.parsed_response and res.parsed_response.equipment:
                    candidates.extend(res.parsed_response.equipment)
            return select_vision_candidate_type(unit, candidates)

    return _fn


# --------------------------------------------------------------------------- #
# CLI — the primary topics extraction path (LLM-first, deterministic-validated)
# --------------------------------------------------------------------------- #
def load_topic_names_from_csv(csv_path: Any, column: str = "topic_name") -> List[str]:
    names: List[str] = []
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            value = (row.get(column) or "").strip()
            if value:
                names.append(value)
    return names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LLM-assisted topics->equipment extraction (primary path).")
    parser.add_argument("--topics-csv", required=True, help="CSV of BMS topic names (topic_name column).")
    parser.add_argument("--topic-column", default="topic_name")
    parser.add_argument("--floor-prefix", default="Floor_02")
    parser.add_argument("--property-id", default="unknown")
    parser.add_argument("--property-name", default="unknown")
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--snapshot-version", default="w06")
    parser.add_argument("--model", default=DEFAULT_TOPICS_MODEL)
    parser.add_argument("--vision-escalate-dir", default=None, help="Screenshot dir for the vision second pass on flagged units.")
    parser.add_argument("--example-image-dir", default=None, help="Few-shot example images for the vision pass.")
    parser.add_argument("--vision-model", default="claude-haiku-4-5")
    parser.add_argument("--prompt-root", default=None)
    parser.add_argument(
        "--metrics-path",
        default=None,
        help="Run-metrics JSON path (default: topics_run_metrics.json beside the output CSV).",
    )
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:  # load .env (ANTHROPIC_API_KEY / LLM_CA_BUNDLE) for standalone runs
        from . import config  # noqa: F401
    except ImportError:  # pragma: no cover
        try:
            import config  # type: ignore # noqa: F401
        except ImportError:
            pass
    args = build_parser().parse_args(argv)
    names = load_topic_names_from_csv(args.topics_csv, args.topic_column)
    print(f"topic names: {len(names)}")
    if not args.run_live:
        print("Dry run (no --run-live): skipping LLM calls.")
        return 0

    GLOBAL_USAGE.reset()
    parse_fn = anthropic_topics_parse_fn(
        property_name=args.property_name, floor=args.floor_prefix, model=args.model
    )
    try:
        units = parse_topics_equipment(names, floor_prefix=args.floor_prefix, parse_fn=parse_fn)
    except TopicsCoverageError as exc:
        print(f"Topics parse rejected: {exc}", file=sys.stderr)
        return 2

    if args.vision_escalate_dir and args.example_image_dir:
        prompt_root = args.prompt_root or str(Path(__file__).resolve().parents[1] / "prompts" / "equipment_extraction")
        extract_fn = default_vision_extract_fn(
            prompt_root=Path(prompt_root), example_image_dir=Path(args.example_image_dir), model=args.vision_model
        )
        units = vision_second_pass(units, image_dir=Path(args.vision_escalate_dir), extract_fn=extract_fn)

    out = write_topics_equipment_snapshot(
        units, args.output_path, property_id=args.property_id, property_name=args.property_name,
        floor=args.floor_prefix, snapshot_version=args.snapshot_version, overwrite=args.overwrite,
    )
    n_review = sum(1 for u in units if u.review_required)
    print(f"wrote {len(units)} units ({n_review} review_required) -> {out}")

    metrics_path = (
        Path(args.metrics_path)
        if args.metrics_path
        else Path(args.output_path).parent / "topics_run_metrics.json"
    )
    write_run_metrics(
        metrics_path,
        run={
            "command": "topics_parser",
            "model": args.model,
            "vision_model": args.vision_model if args.vision_escalate_dir else None,
            "floor": args.floor_prefix,
            "topic_names": len(names),
        },
        counts={
            "units_total": len(units),
            "units_review_required": n_review,
            "units_confident": sum(
                1
                for u in units
                if not u.review_required and (u.confidence is None or u.confidence >= 0.75)
            ),
        },
    )
    print(f"run metrics -> {metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
