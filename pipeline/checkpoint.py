"""Crash-safe checkpointing for extraction runs (lead final-checklist 2a).

A batch that crashes or is interrupted should not re-spend tokens on images
that already succeeded. The checkpoint is an append-only JSONL file: one line
per completed image attempt, written and flushed as each result lands, keyed by
``(source identity, pdf page, prompt content, route, model)``. On the next run, images
whose key already has a ``succeeded`` entry are skipped and their stored result
is reused verbatim (it carries the full provenance payload); failed or skipped
entries are retried. Because the file is append-only, the last entry for a key
wins, and a partial line from a hard crash is ignored.

The key includes a prompt-content fingerprint, extraction route, model, and
quality eligibility so in-place prompt edits or routing/config changes naturally
invalidate prior results rather than silently reusing stale ones.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

if __package__:
    from .models import AIReadyImageRecord, EquipmentExtractionRunResult
else:  # pragma: no cover - exercised only when run as a top-level script
    from models import AIReadyImageRecord, EquipmentExtractionRunResult


def checkpoint_key(
    record: AIReadyImageRecord,
    prompt_version: str,
    model: str,
    *,
    prompt_fingerprint: str = "",
    extraction_mode: str = "flat",
) -> str:
    """Stable identity of one extraction attempt's inputs."""
    page = record.source_page_number or 0
    relative_path = record.source_relative_path.replace("\\", "/")
    eligible = "eligible" if record.extraction_eligible else "ineligible"
    return (
        f"{record.source_sha256}|src:{relative_path}|p{page}|{eligible}|"
        f"{prompt_version}|pf:{prompt_fingerprint or 'legacy'}|"
        f"mode:{extraction_mode}|{model}"
    )


class RunCheckpoint:
    """Append-only per-run ledger of extraction results keyed by input identity."""

    def __init__(self, path: Any) -> None:
        self.path = Path(path)
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    # A hard crash can leave one torn trailing line; ignore it.
                    continue
                key = entry.get("key")
                if isinstance(key, str) and key:
                    self._entries[key] = entry

    def __len__(self) -> int:
        return len(self._entries)

    def status_for(self, key: str) -> Optional[str]:
        entry = self._entries.get(key)
        return entry.get("status") if entry else None

    def succeeded_result(self, key: str) -> Optional[EquipmentExtractionRunResult]:
        """Revive the stored result for a succeeded key; None otherwise.

        A stored payload that no longer validates (e.g. written by an older
        schema) is treated as absent so the image simply reruns.
        """
        entry = self._entries.get(key)
        if not entry or entry.get("status") != "succeeded":
            return None
        payload = entry.get("result")
        if not isinstance(payload, dict):
            return None
        try:
            return EquipmentExtractionRunResult.model_validate(payload)
        except Exception:
            return None

    def record(self, key: str, result: EquipmentExtractionRunResult) -> None:
        """Append one completed attempt and flush immediately (crash-safe)."""
        entry = {
            "key": key,
            "status": result.status,
            "source_filename": result.source_filename,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "result": result.model_dump(mode="json"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True))
            handle.write("\n")
            handle.flush()
        self._entries[key] = entry

    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self._entries.values():
            status = str(entry.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
        return counts
