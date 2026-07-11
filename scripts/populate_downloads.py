"""Populate downloads/<floor>/ with the source files for a pipeline run.

Keeps inputs in a stable repo location so README run commands never need path
edits. Two modes:

* ``--from-s3`` (production) — pull recognised source files from the project
  bucket's ``S3_INPUT_PREFIX`` into ``downloads/<floor>/``, downloading only
  files that are new or whose size changed. ``--check`` lists what a sync
  would fetch without downloading (exit code 1 when the bucket has new or
  changed files, so the check can gate a run).
* local copy (fallback) — copy recognised files from a local directory.

Usage:
    python scripts/populate_downloads.py --floor Floor_2 --from-s3
    python scripts/populate_downloads.py --floor Floor_2 --from-s3 --check
    python scripts/populate_downloads.py --floor Floor_2 --source "<dir>"
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Callable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_SOURCE = Path(r"C:\Users\Seb\Desktop\Project Orient Local\Screenshots")
SOURCE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".dwg"}


def populate(floor: str, source: Path, *, dry_run: bool = False, dest_root: Optional[Path] = None) -> int:
    """Local-directory copy mode (fallback when the bucket is unreachable)."""
    dest = (dest_root or REPO_ROOT) / "downloads" / floor
    if not source.exists():
        print(f"source not found: {source}", file=sys.stderr)
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted(source.iterdir()):
        if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS:
            target = dest / path.name
            print(f"{'[dry-run] ' if dry_run else ''}{path.name} -> downloads/{floor}/{path.name}")
            if not dry_run:
                shutil.copy2(path, target)
            copied += 1
    print(f"{copied} file(s) into downloads/{floor}/")
    return 0


def sync_from_s3(
    floor: str,
    *,
    check_only: bool = False,
    key_contains: Optional[str] = None,
    dest_root: Optional[Path] = None,
    list_objects_fn: Optional[Callable[[], List[dict]]] = None,
    download_fn: Optional[Callable[[str, Path], Path]] = None,
) -> int:
    """Pull new/changed source files from the bucket into downloads/<floor>/.

    A file is downloaded when it is absent locally or its size differs from the
    bucket object (new upload or replacement). ``check_only`` reports instead of
    downloading and exits 1 when anything would be fetched, so the check can be
    run before a pipeline invocation to detect newly added bucket files.
    """
    if list_objects_fn is None or download_fn is None:
        from pipeline import s3_utils

        list_objects_fn = list_objects_fn or s3_utils.list_input_objects
        download_fn = download_fn or s3_utils.download_file

    dest = (dest_root or REPO_ROOT) / "downloads" / floor
    dest.mkdir(parents=True, exist_ok=True)

    new_files = 0
    changed = 0
    up_to_date = 0
    skipped = 0
    for obj in sorted(list_objects_fn(), key=lambda item: item["key"]):
        key = obj["key"]
        filename = key.rsplit("/", 1)[-1]
        if not filename or Path(filename).suffix.lower() not in SOURCE_EXTENSIONS:
            skipped += 1
            continue
        if key_contains and key_contains not in key:
            skipped += 1
            continue
        local = dest / filename
        if not local.exists():
            status = "new"
            new_files += 1
        elif local.stat().st_size != int(obj.get("size", -1)):
            status = "changed"
            changed += 1
        else:
            up_to_date += 1
            continue
        action = "[check] would fetch" if check_only else "fetching"
        print(f"{action} {status}: {key} -> downloads/{floor}/{filename}")
        if not check_only:
            download_fn(key, local)

    pending = new_files + changed
    verb = "pending" if check_only else "fetched"
    print(
        f"downloads/{floor}/: {pending} {verb} ({new_files} new, {changed} changed), "
        f"{up_to_date} up to date, {skipped} skipped (unsupported/filtered)"
    )
    if check_only and pending:
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Populate downloads/<floor>/ for a run.")
    parser.add_argument("--floor", default="Floor_2", help="floor subfolder, e.g. Floor_2")
    parser.add_argument(
        "--from-s3",
        action="store_true",
        help="Sync from the S3 bucket (S3_BUCKET / S3_INPUT_PREFIX in .env; AWS creds in shell).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="With --from-s3: report new/changed bucket files without downloading (exit 1 if any).",
    )
    parser.add_argument(
        "--key-contains",
        default=None,
        help="With --from-s3: only consider bucket keys containing this substring.",
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="local source directory (fallback mode)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.from_s3:
        return sync_from_s3(args.floor, check_only=args.check, key_contains=args.key_contains)
    if args.check:
        print("--check requires --from-s3", file=sys.stderr)
        return 2
    return populate(args.floor, args.source, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
