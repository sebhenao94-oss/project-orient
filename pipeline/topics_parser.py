"""LLM-assisted topics -> equipment parser (addresses Sourav's W4 review #8).

Replaces the deterministic ``<floor>/<equipment>/<point>`` path parser as the
PRIMARY way to infer equipment from BMS topic names. An LLM groups points into
equipment units without assuming a fixed segment order / separator / prefix; the
old deterministic path-parse is retained only as a VALIDATION cross-check that
flags disagreements for human review (deterministic rules for validation and
post-processing, not primary extraction).

The LLM call is injectable via ``parse_fn`` so the grouping-validation-snapshot
core is fully offline-testable with a fake. The default wires the Anthropic
client at the cheapest text tier (Haiku), escalating only on a structural gate
failure (that escalation + the vision second-pass are Phase 2).
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

DEFAULT_TOPICS_MODEL = "claude-haiku-4-5"

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


# parse_fn seam: a list of topic names -> parsed equipment units. Injectable so
# tests exercise the validation/snapshot core without a live model.
TopicsParseFn = Callable[[Sequence[str]], List[ParsedTopicEquipment]]


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
