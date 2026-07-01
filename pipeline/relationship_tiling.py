"""Tiled relationship extraction from full-resolution mechanical drawings.

Mechanical drawings (~12600x9000 px) exceed the model's on-send resize limit, so
a whole-image call downsamples the line-work away and recovers 0 serving edges
(the W4 result). This mirrors the L4 equipment tiler: split each drawing into
overlapping full-resolution tiles, run the relationship prompt on each non-blank
tile, and UNION the per-tile edges — deduping by (child, ref_type, parent),
keeping the max confidence and OR-ing the conflict flag. Provenance (source
drawing per edge) is preserved. No database writes.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

if __package__:
    from .tiling import tile_image, DEFAULT_MAX_TILE_PX, DEFAULT_OVERLAP_PX
    from .extraction import _tile_has_ink, _prepared_image_records_from_dir
    from .relationships import extract_relationships_batch
else:  # pragma: no cover - bare-import fallback
    from tiling import tile_image, DEFAULT_MAX_TILE_PX, DEFAULT_OVERLAP_PX  # type: ignore
    from extraction import _tile_has_ink, _prepared_image_records_from_dir  # type: ignore
    from relationships import extract_relationships_batch  # type: ignore


@dataclass
class UnionedEdge:
    child: str
    parent: str
    ref_type: str
    confidence: Optional[float] = None
    conflict: bool = False
    conflict_reason: Optional[str] = None
    source_drawings: List[str] = field(default_factory=list)
    tile_hits: int = 0

    @property
    def key(self) -> str:
        return f"{self.child}|{self.ref_type}|{self.parent}"


def union_edges(raw_edges: Sequence[dict]) -> List[UnionedEdge]:
    """Dedupe per-tile edges by (child, ref_type, parent).

    Keeps the highest confidence, ORs the conflict flag, counts how many tiles
    voted for the edge (a cross-tile agreement signal), and accumulates the
    source drawings. ``raw_edges`` are dicts with child/parent/ref_type/
    confidence/conflict/conflict_reason/source_drawing.
    """
    merged: Dict[str, UnionedEdge] = {}
    for e in raw_edges:
        child, parent, ref_type = e["child"], e["parent"], e["ref_type"]
        key = f"{child}|{ref_type}|{parent}"
        conf = e.get("confidence")
        conflict = bool(e.get("conflict"))
        drawing = e.get("source_drawing")
        if key not in merged:
            merged[key] = UnionedEdge(
                child=child, parent=parent, ref_type=ref_type,
                confidence=conf, conflict=conflict,
                conflict_reason=e.get("conflict_reason"),
                source_drawings=[drawing] if drawing else [],
                tile_hits=1,
            )
            continue
        u = merged[key]
        u.tile_hits += 1
        if conf is not None and (u.confidence is None or conf > u.confidence):
            u.confidence = conf
        if conflict and not u.conflict:
            u.conflict = True
            u.conflict_reason = e.get("conflict_reason") or u.conflict_reason
        if drawing and drawing not in u.source_drawings:
            u.source_drawings.append(drawing)
    return list(merged.values())


async def _edges_for_drawing(
    drawing_path: Path,
    *,
    equipment_list_text: str,
    prompt_package,
    model: str,
    max_tile_px: int,
    overlap_px: int,
    max_concurrency: int,
) -> tuple:
    """Tile one drawing, run relationships per non-blank tile, return raw edges."""
    with tempfile.TemporaryDirectory(prefix="orient_rel_tiles_") as tile_dir, \
         tempfile.TemporaryDirectory(prefix="orient_rel_run_") as run_dir:
        tiles = tile_image(drawing_path, Path(tile_dir), max_tile_px=max_tile_px, overlap_px=overlap_px)
        content = [t for t in tiles if _tile_has_ink(str(t.path))]
        run_root = Path(run_dir)
        for i, t in enumerate(content):
            shutil.copy2(t.path, run_root / f"{drawing_path.stem}_tile_{i:03d}.png")
        records = _prepared_image_records_from_dir(str(run_root), floor="Floor_02")
        results = await extract_relationships_batch(
            image_records=records,
            equipment_list_text=equipment_list_text,
            prompt_package=prompt_package,
            model=model,
            max_concurrency=max_concurrency,
        )
        raw_edges: List[dict] = []
        succeeded = 0
        for res in results:
            if res.status == "succeeded" and res.parsed_response is not None:
                succeeded += 1
                for edge in res.parsed_response.relationships:
                    raw_edges.append({
                        "child": edge.child,
                        "parent": edge.parent,
                        "ref_type": edge.ref_type.value if hasattr(edge.ref_type, "value") else str(edge.ref_type),
                        "confidence": edge.confidence,
                        "conflict": getattr(edge, "conflict", False),
                        "conflict_reason": getattr(edge, "conflict_reason", None),
                        "source_drawing": drawing_path.name,
                    })
        return raw_edges, {"drawing": drawing_path.name, "tiles": len(tiles), "content_tiles": len(content), "tiles_succeeded": succeeded}


async def extract_drawing_relationships(
    drawing_paths: Sequence[Path],
    *,
    equipment_list_text: str,
    prompt_package,
    model: str,
    max_tile_px: int = DEFAULT_MAX_TILE_PX,
    overlap_px: int = DEFAULT_OVERLAP_PX,
    max_concurrency: int = 3,
) -> tuple:
    """Extract + union serving relationships across a set of drawings."""
    all_raw: List[dict] = []
    stats: List[dict] = []
    for path in drawing_paths:
        raw, stat = await _edges_for_drawing(
            Path(path), equipment_list_text=equipment_list_text, prompt_package=prompt_package,
            model=model, max_tile_px=max_tile_px, overlap_px=overlap_px, max_concurrency=max_concurrency,
        )
        all_raw.extend(raw)
        stats.append(stat)
    return union_edges(all_raw), stats
