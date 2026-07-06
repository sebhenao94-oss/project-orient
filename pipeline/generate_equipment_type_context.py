"""Generate prompt context from equipments_point_types definitions."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


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


def load_equipment_definitions(equipment_dir: Path) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for path in sorted(equipment_dir.glob("equip_*.py")):
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


def render_context(definitions: dict[str, dict[str, Any]]) -> str:
    lines = ["# Equipment Types", ""]
    lines.extend(f"- {equipment_type}" for equipment_type in definitions)
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate equipment type prompt context.")
    parser.add_argument("--equipment-dir", default=str(DEFAULT_EQUIPMENT_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)

    definitions = load_equipment_definitions(Path(args.equipment_dir))
    if not definitions:
        raise RuntimeError(f"No EQUIPMENT definitions found in {args.equipment_dir}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_context(definitions), encoding="utf-8")
    print(f"Wrote {len(definitions)} equipment types to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
