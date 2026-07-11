"""Generate the equipment-type prompt context from ``equipments_point_types/``.

The supervisor's classification library defines each equipment type together
with its point-type payload and Haystack equip tags. Equipment *extraction*
does not need the point-type payload — sending it only adds detail the model
must ignore. This module is the intermediary step that renders the library
into a prompt-context artifact in one of two modes:

* default — the full classification reference (type -> equip tags + point
  types), useful for documentation and later point-classification stages;
* ``--simple`` — equipment type names only, the artifact the equipment
  extractor consumes (``prompts/equipment_type_context.md``).

Adapted from the ``dev_sd_2`` prototype; the ``--simple`` mode implements the
team lead's final-checklist direction (strip the classification list down to
type names and point the extractor at that simplified list).
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EQUIPMENT_DIR = PROJECT_ROOT / "equipments_point_types"
DEFAULT_OUTPUT = PROJECT_ROOT / "prompts" / "equipment_type_context.md"


def load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_equipment_definitions(equipment_dir: Path) -> Dict[str, Dict[str, Any]]:
    definitions: Dict[str, Dict[str, Any]] = {}
    for path in sorted(Path(equipment_dir).glob("equip_*.py")):
        module = load_module(path)
        equipment = getattr(module, "EQUIPMENT", None)
        if not isinstance(equipment, dict):
            continue
        for equipment_type, definition in equipment.items():
            definitions[str(equipment_type)] = {
                "source_file": path.name,
                "point_types": list(definition.get("point_types", [])),
                "equip_tags": list(definition.get("equip_tags", [])),
            }
    return dict(sorted(definitions.items()))


def render_simple_context(definitions: Dict[str, Dict[str, Any]]) -> str:
    """Type names only — the extraction-facing simplified list."""
    lines = [
        "# Equipment Types",
        "",
        "The complete list of in-scope equipment type classifications. Point-type",
        "detail is intentionally omitted: extraction identifies equipment units,",
        "not points.",
        "",
    ]
    lines.extend(f"- {equipment_type}" for equipment_type in definitions)
    return "\n".join(lines).rstrip() + "\n"


def render_full_context(definitions: Dict[str, Dict[str, Any]]) -> str:
    """Full classification reference: equip tags and point types per type."""
    lines = ["# Equipment Type Classification Reference", ""]
    for equipment_type, definition in definitions.items():
        lines.append(f"## {equipment_type}")
        lines.append(f"Source: {definition['source_file']}")
        if definition["equip_tags"]:
            lines.append("Equip tags: " + ", ".join(definition["equip_tags"]))
        if definition["point_types"]:
            lines.append("Point types: " + ", ".join(definition["point_types"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate equipment-type prompt context from equipments_point_types/."
    )
    parser.add_argument("--equipment-dir", default=str(DEFAULT_EQUIPMENT_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Emit equipment type names only (the extraction-facing artifact).",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    definitions = load_equipment_definitions(Path(args.equipment_dir))
    if not definitions:
        raise RuntimeError(f"No EQUIPMENT definitions found in {args.equipment_dir}")

    render = render_simple_context if args.simple else render_full_context
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render(definitions), encoding="utf-8")
    mode = "simple (type names only)" if args.simple else "full reference"
    print(f"Wrote {len(definitions)} equipment types [{mode}] to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
