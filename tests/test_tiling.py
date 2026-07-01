import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

from PIL import Image  # noqa: E402

from tiling import compute_tile_boxes, tile_image  # noqa: E402


class TileGeometryTests(unittest.TestCase):
    def test_small_image_is_one_tile(self):
        boxes = compute_tile_boxes(1000, 800, max_tile_px=2500)
        self.assertEqual(boxes, [(0, 0, 1000, 800)])

    def test_large_drawing_is_fully_covered(self):
        w, h = 12600, 9000
        boxes = compute_tile_boxes(w, h, max_tile_px=2500, overlap_px=128)
        # Every tile is within the max size.
        for left, top, right, bottom in boxes:
            self.assertLessEqual(right - left, 2500)
            self.assertLessEqual(bottom - top, 2500)
        # Coverage: starts at the origin, reaches both far edges.
        self.assertEqual(min(b[0] for b in boxes), 0)
        self.assertEqual(min(b[1] for b in boxes), 0)
        self.assertEqual(max(b[2] for b in boxes), w)
        self.assertEqual(max(b[3] for b in boxes), h)
        # 6 cols x 4 rows for these dims.
        self.assertEqual(len(boxes), 24)

    def test_overlap_must_be_valid(self):
        with self.assertRaises(ValueError):
            compute_tile_boxes(5000, 5000, max_tile_px=2500, overlap_px=2500)
        with self.assertRaises(ValueError):
            compute_tile_boxes(0, 100)

    def test_adjacent_tiles_overlap(self):
        boxes = compute_tile_boxes(5000, 100, max_tile_px=2500, overlap_px=128)
        xs = sorted({(b[0], b[2]) for b in boxes})
        # Second tile starts before the first tile ends -> overlap.
        self.assertLess(xs[1][0], xs[0][1])


class TileImageTests(unittest.TestCase):
    def test_tiles_written_and_sized(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "drawing.png"
            Image.new("RGB", (5000, 1200), "white").save(src)

            tiles = tile_image(src, tmp / "tiles", max_tile_px=2500, overlap_px=128)

            self.assertEqual(len(tiles), 3)  # 3 cols x 1 row
            for tile in tiles:
                self.assertTrue(Path(tile.path).exists())
                with Image.open(tile.path) as im:
                    self.assertLessEqual(im.size[0], 2500)
                    self.assertLessEqual(im.size[1], 2500)

    def test_small_image_single_tile(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "shot.png"
            Image.new("RGB", (1200, 900), "white").save(src)
            tiles = tile_image(src, tmp / "tiles")
            self.assertEqual(len(tiles), 1)
            self.assertEqual(tiles[0].box, (0, 0, 1200, 900))


if __name__ == "__main__":
    unittest.main()
