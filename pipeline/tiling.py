"""Drawing tiling for the L4 (Opus) tier.

Mechanical drawings are huge (~12600x9000) and dense; Claude resizes a
whole image down to its long-edge limit, losing the fine line-work that
encodes serving relationships and reheat coils (the W4 0-edge gap). The unblock
is to split the drawing into a grid of overlapping tiles small enough that each
is sent at full resolution, run each tile, then union the per-tile results.

This module is the correctness-critical geometry (pure, fully testable) plus a
PIL-based image tiler. The overlap keeps equipment/labels that straddle a tile
boundary readable in at least one tile.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

DEFAULT_MAX_TILE_PX = 2500  # within Opus 4.8's ~2576px long-edge full-res limit
DEFAULT_OVERLAP_PX = 128


@dataclass
class TileInfo:
    """One saved tile: file path, source-pixel box, and grid position."""

    path: str
    box: Tuple[int, int, int, int]  # (left, top, right, bottom) in source pixels
    row: int
    col: int


def _starts(total: int, tile: int, overlap: int) -> List[int]:
    """Evenly-spaced tile start offsets covering [0, total] with overlap.

    Tiles are full-size; the last tile ends exactly at ``total``. Returns [0]
    when the extent already fits in one tile.
    """
    if total <= 0:
        raise ValueError("extent must be positive")
    if tile <= 0:
        raise ValueError("tile size must be positive")
    if overlap < 0 or overlap >= tile:
        raise ValueError("overlap must be in [0, tile)")
    if total <= tile:
        return [0]

    step = tile - overlap
    count = math.ceil((total - overlap) / step)
    if count <= 1:
        return [0]
    span = total - tile
    starts = [round(i * span / (count - 1)) for i in range(count)]

    deduped: List[int] = []
    for start in starts:
        if not deduped or start != deduped[-1]:
            deduped.append(start)
    return deduped


def compute_tile_boxes(
    width: int,
    height: int,
    *,
    max_tile_px: int = DEFAULT_MAX_TILE_PX,
    overlap_px: int = DEFAULT_OVERLAP_PX,
) -> List[Tuple[int, int, int, int]]:
    """Cover a WxH image with overlapping (left, top, right, bottom) tile boxes."""
    xs = _starts(width, max_tile_px, overlap_px)
    ys = _starts(height, max_tile_px, overlap_px)
    boxes: List[Tuple[int, int, int, int]] = []
    for top in ys:
        for left in xs:
            right = min(left + max_tile_px, width)
            bottom = min(top + max_tile_px, height)
            boxes.append((left, top, right, bottom))
    return boxes


def tile_image(
    image_path,
    out_dir,
    *,
    max_tile_px: int = DEFAULT_MAX_TILE_PX,
    overlap_px: int = DEFAULT_OVERLAP_PX,
) -> List[TileInfo]:
    """Split an image into overlapping PNG tiles and return their metadata.

    A drawing that already fits in one tile yields a single tile (a no-op split),
    so callers can route every drawing through this uniformly.
    """
    from PIL import Image

    # Mechanical drawings (~113 MP) exceed Pillow's default DecompressionBomb
    # guard; this module exists precisely to handle such images, so lift the cap.
    Image.MAX_IMAGE_PIXELS = None

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tiles: List[TileInfo] = []
    with Image.open(image_path) as image:
        width, height = image.size
        xs = _starts(width, max_tile_px, overlap_px)
        ys = _starts(height, max_tile_px, overlap_px)
        for row, top in enumerate(ys):
            for col, left in enumerate(xs):
                right = min(left + max_tile_px, width)
                bottom = min(top + max_tile_px, height)
                box = (left, top, right, bottom)
                tile_path = out_dir / f"tile_r{row}_c{col}.png"
                image.crop(box).save(tile_path, "PNG")
                tiles.append(TileInfo(str(tile_path), box, row, col))
    return tiles
