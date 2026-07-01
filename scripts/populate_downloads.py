"""Populate downloads/<floor>/ with the source files for a pipeline run.

Sourav W4-review #5/#6: keep inputs in a stable repo location so run commands
never need path edits. Copies recognised source files (screenshots + drawings)
from a source directory into downloads/<floor>/. The default source is the local
screenshots folder; a future version will pull from the S3 input prefix.

Usage:
    python scripts/populate_downloads.py --floor Floor_2 --source "<dir>"
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path(r"C:\Users\Seb\Desktop\Project Orient Local\Screenshots")
SOURCE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".dwg"}


def populate(floor: str, source: Path, *, dry_run: bool = False) -> int:
    dest = REPO_ROOT / "downloads" / floor
    if not source.exists():
        print(f"source not found: {source}", file=sys.stderr)
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted(source.iterdir()):
        if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS:
            target = dest / path.name
            print(f"{'[dry-run] ' if dry_run else ''}{path.name} -> {target.relative_to(REPO_ROOT)}")
            if not dry_run:
                shutil.copy2(path, target)
            copied += 1
    print(f"{copied} file(s) into downloads/{floor}/")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Populate downloads/<floor>/ for a run.")
    parser.add_argument("--floor", default="Floor_2", help="floor subfolder, e.g. Floor_2")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="source directory of images")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return populate(args.floor, args.source, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
