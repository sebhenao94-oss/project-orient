import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import extraction  # noqa: E402
from extraction import extract_equipment_from_drawing  # noqa: E402
from models import AIReadyImageRecord  # noqa: E402
from tiling import TileInfo  # noqa: E402


def _record(eligible=True):
    return AIReadyImageRecord(
        source_filename="drawing.png",
        source_relative_path="drawings/drawing.png",
        source_file_type="image",
        source_sha256="a" * 64,
        prepared_image_local_path="/tmp/drawing.png",
        prepared_image_filename="drawing.png",
        quality_flag=True,
        quality_status="passed" if eligible else "failed",
        quality_reason="ok" if eligible else "too small",
        extraction_eligible=eligible,
        preparation_status="prepared" if eligible else "quality_failed",
    )


class _Pkg:
    prompt_version = "equipment_extraction_v4"


def _fake_tiles(names):
    return [TileInfo(path=n, box=(0, 0, 1, 1), row=i, col=0) for i, n in enumerate(names)]


def _run(record=None, tiles=None, canned=None, ink=None, prefilter=True):
    tiles = tiles if tiles is not None else _fake_tiles(["t0", "t1", "t2"])
    canned = canned or {}

    async def fake_request(*, message_plan, model, client):
        return canned[message_plan]  # message_plan is the tile path (patched plan)

    with mock.patch.object(extraction, "tile_image", return_value=tiles), \
         mock.patch.object(extraction, "build_equipment_message_plan", side_effect=lambda pkg, path, include_examples=True: str(path)), \
         mock.patch.object(extraction, "_tile_has_ink", side_effect=(ink or (lambda p: True))), \
         mock.patch.object(extraction, "request_equipment_extraction", side_effect=fake_request):
        return asyncio.run(
            extract_equipment_from_drawing(
                image_record=record or _record(),
                prompt_package=_Pkg(),
                model="claude-opus-4-8",
                client=object(),
                prefilter=prefilter,
            )
        )


AHU = '{"equipment":[{"raw_label":"AHU 2-2","canonical_name":"AHU 2-2","equipment_type":"AHU","confidence":0.90}]}'
MIX = ('{"equipment":[{"raw_label":"VAV 2-1","canonical_name":"VAV 2-1","equipment_type":"VAV","confidence":0.80},'
       '{"raw_label":"AHU 2-2","canonical_name":"AHU 2-2","equipment_type":"AHU","confidence":0.95}]}')
EMPTY = '{"equipment":[]}'


class DrawingExtractionTests(unittest.TestCase):
    def test_unions_across_tiles_keeping_max_confidence(self):
        result = _run(canned={"t0": AHU, "t1": MIX, "t2": EMPTY})
        self.assertEqual(result.status, "succeeded")
        names = {c.canonical_name: c.confidence for c in result.parsed_response.equipment}
        self.assertEqual(set(names), {"AHU 2-2", "VAV 2-1"})
        self.assertEqual(names["AHU 2-2"], 0.95)  # max across duplicate tiles
        # union is sorted by canonical_name
        self.assertEqual([c.canonical_name for c in result.parsed_response.equipment],
                         ["AHU 2-2", "VAV 2-1"])

    def test_union_merges_whitespace_variants_across_tiles(self):
        spaced = '{"equipment":[{"raw_label":"OAVAV 2-1","canonical_name":"OAVAV 2-1","equipment_type":"OAVAV","confidence":0.90}]}'
        tight = '{"equipment":[{"raw_label":"OAVAV2-1","canonical_name":"OAVAV2-1","equipment_type":"OAVAV","confidence":0.95}]}'
        result = _run(tiles=_fake_tiles(["t0", "t1"]), canned={"t0": spaced, "t1": tight})
        # "OAVAV 2-1" and "OAVAV2-1" are the same unit across overlapping tiles.
        self.assertEqual(len(result.parsed_response.equipment), 1)
        self.assertEqual(result.parsed_response.equipment[0].confidence, 0.95)

    def test_prefilter_skips_blank_tiles_before_calling_model(self):
        called = []

        async def fake_request(*, message_plan, model, client):
            called.append(message_plan)
            return {"t0": AHU, "blank": MIX}[message_plan]

        tiles = _fake_tiles(["t0", "blank"])
        with mock.patch.object(extraction, "tile_image", return_value=tiles), \
             mock.patch.object(extraction, "build_equipment_message_plan", side_effect=lambda pkg, path, include_examples=True: str(path)), \
             mock.patch.object(extraction, "_tile_has_ink", side_effect=lambda p: p != "blank"), \
             mock.patch.object(extraction, "request_equipment_extraction", side_effect=fake_request):
            result = asyncio.run(extract_equipment_from_drawing(
                image_record=_record(), prompt_package=_Pkg(), model="m", client=object(),
            ))
        self.assertEqual(called, ["t0"])  # blank tile never sent to the model
        self.assertEqual({c.canonical_name for c in result.parsed_response.equipment}, {"AHU 2-2"})

    def test_all_blank_tiles_succeeds_empty(self):
        result = _run(tiles=_fake_tiles(["t0"]), canned={"t0": EMPTY},
                      ink=lambda p: False)  # every tile filtered out
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.parsed_response.equipment, [])

    def test_all_tiles_fail_reports_failure(self):
        bad = "not json at all"
        result = _run(tiles=_fake_tiles(["t0", "t1"]), canned={"t0": bad, "t1": bad})
        self.assertEqual(result.status, "parse_failed")
        self.assertIsNone(result.parsed_response)

    def test_ineligible_record_is_skipped_without_tiling(self):
        with mock.patch.object(extraction, "tile_image") as tiled:
            result = asyncio.run(extract_equipment_from_drawing(
                image_record=_record(eligible=False), prompt_package=_Pkg(),
                model="m", client=object(),
            ))
        tiled.assert_not_called()
        self.assertEqual(result.status, "skipped")


if __name__ == "__main__":
    unittest.main()
