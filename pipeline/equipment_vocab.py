"""W4 equipment-vocabulary mapping for Project ORIENT.

Source of truth for equipment type keys is the supervisor's classification
library under ``equipments_point_types/`` (added on the ``dev_sd`` branch), plus
the plant-container keys from the June-15 brief Appendix A (the library defines
plant *components* such as ``CHILLER``/``BOILER`` but not the plant *containers*
``CHW-PLANT``/``HW-PLANT``/``COND-PLANT`` that appear in the worked example).

This module maps the older W3 inferred types (``AHU``, ``VAV``, ``VAVRH``,
``FPTU``, ``OAVAV``, ``EAVAV``, ``FCU``) onto that vocabulary, and produces a
canonical name in the team-lead convention ``{Type}_{floor}-{unit}``.

Some mappings cannot be fully determined from a raw label alone and are returned
with a review flag, per the W4 "best-guess base + flag" decision:

* ``VAVRH`` -> ``VAV-RH-HW`` (the supervisor notes VAVRH is most commonly hot-
  water reheat; the electric-reheat variant ``VAV-RH-ELEC`` cannot be ruled out).
* ``FPTU`` -> ``FPTU`` family placeholder; the parallel/series and HW/electric
  subtype requires drawing/schedule evidence.

The module is pure (no I/O, no model calls).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


# Keys defined in equipments_point_types/ (supervisor library). A unit test
# cross-checks this set against the library so the two cannot silently diverge.
LIBRARY_TYPE_KEYS = frozenset(
    {
        # equip_air_handling.py
        "AHU",
        "DOAS",
        "MAU",
        "FCU",
        # equip_air_terminal.py
        "VAV",
        "VAV-RH-HW",
        "VAV-RH-ELEC",
        "FPTU-PARALLEL-HW",
        "FPTU-SERIES-HW",
        "FPTU-PARALLEL-ELEC",
        "FPTU-SERIES-ELEC",
        "OAVAV",
        "OAVAV-RH-HW",
        "OAVAV-RH-ELEC",
        "EAVAV",
        # equip_chw_plant.py / equip_cond_plant.py / equip_hw_plant.py
        "CHILLER",
        "CHW-PUMP",
        "COOLING-TOWER",
        "COND-PUMP",
        "BOILER",
        "HW-PUMP",
        # equip_ventilation.py
        "ERV",
    }
)

# Plant-container keys from the brief Appendix A + the Floor-1 worked example.
PLANT_CONTAINER_KEYS = frozenset({"CHW-PLANT", "HW-PLANT", "COND-PLANT"})

# "FPTU" is a family placeholder used when the parallel/series + HW/electric
# subtype is not yet known; it is intentionally not a library key.
FAMILY_PLACEHOLDER_KEYS = frozenset({"FPTU"})

OFFICIAL_TYPE_KEYS = LIBRARY_TYPE_KEYS | PLANT_CONTAINER_KEYS


@dataclass(frozen=True)
class TypeMapping:
    raw_type: str
    mapped_type: str
    review_required: bool
    review_reason: str


# Maps the W3-era inferred types onto the current vocabulary. Confident mappings
# carry no review reason; ambiguous ones flag for review with the reason.
_RAW_TYPE_MAP = {
    "AHU": ("AHU", False, ""),
    "VAV": ("VAV", False, ""),
    "FCU": ("FCU", False, ""),
    "OAVAV": ("OAVAV", False, ""),
    "EAVAV": ("EAVAV", False, ""),
    "VAVRH": (
        "VAV-RH-HW",
        True,
        "reheat source assumed hot-water (supervisor: VAVRH most commonly HW); "
        "confirm against VAV-RH-ELEC",
    ),
    "FPTU": (
        "FPTU",
        True,
        "FPTU subtype unresolved: parallel/series and HW/electric require "
        "drawing or schedule evidence "
        "(FPTU-PARALLEL-HW / FPTU-SERIES-HW / FPTU-PARALLEL-ELEC / FPTU-SERIES-ELEC)",
    ),
}


def map_equipment_type(raw_type: str) -> TypeMapping:
    """Map a W3 inferred type onto the current vocabulary with a review flag."""
    key = (raw_type or "").strip().upper()
    if key in _RAW_TYPE_MAP:
        mapped, review, reason = _RAW_TYPE_MAP[key]
        return TypeMapping(raw_type=raw_type, mapped_type=mapped, review_required=review, review_reason=reason)
    if key in OFFICIAL_TYPE_KEYS:
        return TypeMapping(raw_type=raw_type, mapped_type=key, review_required=False, review_reason="")
    return TypeMapping(
        raw_type=raw_type,
        mapped_type=key or "UNRESOLVED",
        review_required=True,
        review_reason=f"unrecognized raw type '{raw_type}'; not in the current vocabulary",
    )


@dataclass(frozen=True)
class CanonicalName:
    canonical_name: str
    review_required: bool
    review_reason: str


def canonical_name(canonical_key: str, mapped_type: str, floor_digit: str = "2") -> CanonicalName:
    """Build a ``{Type}_{floor}-{unit}`` name from a teammate canonical key.

    ``canonical_key`` is the separator/zero-padding-insensitive key from the
    normalization layer (e.g. ``AHU_2_1``, ``FCU_PM_2_1``, ``AHU_02A``). The
    leading original-type token is dropped, the floor token is removed, and the
    remainder becomes the unit. Cases where the floor token cannot be isolated
    cleanly are flagged for review.
    """
    review = False
    reasons = []

    tokens = [token for token in (canonical_key or "").split("_") if token != ""]
    if not tokens:
        return CanonicalName(canonical_name=canonical_key, review_required=True, review_reason="empty canonical key")

    # Drop the leading original-type token (the key starts with the W3 type).
    unit_tokens = tokens[1:]

    floor_exact = floor_digit
    floor_padded = "0" + floor_digit

    removed_floor = False
    result_tokens = []
    for token in unit_tokens:
        if not removed_floor and token in (floor_exact, floor_padded):
            removed_floor = True
            continue
        result_tokens.append(token)

    if not removed_floor:
        # Try an inline floor split, e.g. "02A" -> floor "02", unit "A".
        split_tokens = []
        for index, token in enumerate(result_tokens):
            if not removed_floor and (token.startswith(floor_padded) or token.startswith(floor_exact)):
                prefix = floor_padded if token.startswith(floor_padded) else floor_exact
                remainder = token[len(prefix):]
                if remainder:
                    split_tokens.append(remainder)
                removed_floor = True
                review = True
                reasons.append(f"floor digit inferred from inline token '{token}'")
            else:
                split_tokens.append(token)
        result_tokens = split_tokens

    if not removed_floor:
        review = True
        reasons.append("could not isolate a floor token; floor assumed from snapshot")

    unit = "_".join(result_tokens)
    if not unit:
        review = True
        reasons.append("could not derive a unit identifier")
        unit = "_".join(unit_tokens)

    # Brief naming convention {Type}_{floor}-{unit} (e.g. AHU_2-01, matching the
    # Floor-1 DB worked example AHU_1-01). The trailing numeric unit token is
    # zero-padded to two digits (Sourav #1); letter units (A/B/C) are kept as-is.
    name = f"{mapped_type}_{floor_digit}-{_pad_unit(unit)}" if unit else f"{mapped_type}_{floor_digit}"
    return CanonicalName(canonical_name=name, review_required=review, review_reason="; ".join(reasons))


def _pad_unit(unit: str) -> str:
    """Zero-pad the trailing numeric token of a unit to two digits (1 -> 01)."""
    parts = unit.split("_")
    if parts and parts[-1].isdigit():
        parts[-1] = parts[-1].zfill(2)
    return "_".join(parts)


def classify(canonical_key: str, raw_type: str, floor_digit: str = "2") -> Tuple[str, str, bool, str]:
    """Convenience: return (mapped_type, canonical_name, review_required, review_reason)."""
    type_mapping = map_equipment_type(raw_type)
    name = canonical_name(canonical_key, type_mapping.mapped_type, floor_digit)
    review_required = type_mapping.review_required or name.review_required
    reasons = [reason for reason in (type_mapping.review_reason, name.review_reason) if reason]
    return type_mapping.mapped_type, name.canonical_name, review_required, "; ".join(reasons)
