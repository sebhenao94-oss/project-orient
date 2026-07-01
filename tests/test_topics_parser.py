import csv
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _path in (PROJECT_ROOT, PROJECT_ROOT / "pipeline"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from topics_parser import (  # noqa: E402
    ParsedTopicEquipment,
    parse_topics_equipment,
    parse_units_json,
    validate_against_paths,
    write_topics_equipment_snapshot,
    TOPICS_EQUIPMENT_SNAPSHOT_COLUMNS,
    resolve_screenshot,
    vision_second_pass,
    load_topic_names_from_csv,
)

FLOOR = "Floor_02"


def unit(raw_label, equipment_type, topics, **kw):
    return ParsedTopicEquipment(
        raw_context=kw.get("raw_context", raw_label),
        raw_label=raw_label,
        equipment_type=equipment_type,
        floor=FLOOR,
        source_topics=list(topics),
        confidence=kw.get("confidence"),
    )


class ValidationCrossCheckTests(unittest.TestCase):
    def test_agreement_is_not_flagged(self):
        u = unit(
            "AHU_01",
            "AHU",
            ["Floor_02/DEV1_AHU_01/SupplyTemp", "Floor_02/DEV1_AHU_01/ReturnTemp"],
        )
        validate_against_paths([u], FLOOR)
        self.assertFalse(u.review_required)
        self.assertEqual(u.review_reason, "")

    def test_topics_spanning_two_contexts_are_flagged(self):
        u = unit(
            "AHU_01",
            "AHU",
            ["Floor_02/DEV1_AHU_01/T", "Floor_02/DEV2_VAV_03/T"],
        )
        validate_against_paths([u], FLOOR)
        self.assertTrue(u.review_required)
        self.assertIn("multiple path contexts", u.review_reason)

    def test_nonstandard_format_is_flagged(self):
        u = unit("AHU-1", "AHU", ["AHU-1:SupplyTemp", "AHU-1:ReturnTemp"])
        validate_against_paths([u], FLOOR)
        self.assertTrue(u.review_required)
        self.assertIn("no deterministic path match", u.review_reason)

    def test_type_disagreement_is_flagged(self):
        u = unit("AHU_01", "FCU", ["Floor_02/DEV1_AHU_01/T"])
        validate_against_paths([u], FLOOR)
        self.assertTrue(u.review_required)
        self.assertIn("not evident in path label", u.review_reason)

    def test_parse_topics_equipment_runs_parse_then_validation(self):
        canned = [
            unit("AHU_01", "AHU", ["Floor_02/DEV1_AHU_01/T"]),  # agrees
            unit("FCU_01", "VAV", ["Floor_02/DEV9_FCU_01/T"]),  # type mismatch -> flagged
        ]
        result = parse_topics_equipment(
            ["ignored"], floor_prefix=FLOOR, parse_fn=lambda _names: canned
        )
        self.assertFalse(result[0].review_required)
        self.assertTrue(result[1].review_required)


class ParseUnitsJsonTests(unittest.TestCase):
    def test_parses_plain_json_array(self):
        text = (
            '[{"raw_context":"DEV1_AHU_01","raw_label":"AHU_01","equipment_type":"AHU",'
            '"floor":"Floor_02","source_topics":["Floor_02/DEV1_AHU_01/T"],'
            '"confidence":0.8,"review_required":false}]'
        )
        units = parse_units_json(text, FLOOR)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].equipment_type, "AHU")
        self.assertEqual(units[0].confidence, 0.8)

    def test_tolerates_code_fence_and_missing_floor(self):
        text = '```json\n[{"raw_context":"X","equipment_type":"FCU","source_topics":[]}]\n```'
        units = parse_units_json(text, FLOOR)
        self.assertEqual(units[0].equipment_type, "FCU")
        self.assertEqual(units[0].floor, FLOOR)  # falls back to default
        self.assertIsNone(units[0].confidence)


class SnapshotWriterTests(unittest.TestCase):
    def test_writes_expected_columns_and_rows(self):
        units = [
            unit("AHU_01", "AHU", ["Floor_02/DEV1_AHU_01/T"], confidence=0.91),
            unit("VAV_03", "VAV", ["Floor_02/DEV2_VAV_03/T"]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "Floor_2" / "topics_equipment.csv"
            write_topics_equipment_snapshot(
                units,
                out,
                property_id="prop",
                property_name="bldg",
                floor=FLOOR,
                snapshot_version="w06",
            )
            with out.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        self.assertEqual(tuple(rows[0].keys()), TOPICS_EQUIPMENT_SNAPSHOT_COLUMNS)
        self.assertEqual(len(rows), 2)
        ahu = next(r for r in rows if r["raw_label"] == "AHU_01")
        self.assertEqual(ahu["inferred_raw_type"], "AHU")
        self.assertEqual(ahu["confidence"], "0.910")
        self.assertEqual(ahu["source_method"], "llm_assisted")

    def test_refuses_overwrite_without_flag(self):
        units = [unit("AHU_01", "AHU", ["Floor_02/DEV1_AHU_01/T"])]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "topics.csv"
            write_topics_equipment_snapshot(
                units, out, property_id="p", property_name="b", floor=FLOOR, snapshot_version="w06"
            )
            with self.assertRaises(FileExistsError):
                write_topics_equipment_snapshot(
                    units, out, property_id="p", property_name="b", floor=FLOOR, snapshot_version="w06"
                )


class VisionSecondPassTests(unittest.TestCase):
    def test_resolve_screenshot_matches_fuzzily(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "VAVRH_2_1.png").write_bytes(b"x")
            (d / "AHU_02A.png").write_bytes(b"x")
            u = unit("VAVRH_2_1", "VAV", ["Floor_02/DEV1_VAVRH_2_1/T"], raw_context="DEV1_VAVRH_2_1")
            self.assertEqual(resolve_screenshot(u, d).name, "VAVRH_2_1.png")

    def test_confirmation_clears_the_flag(self):
        u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
        u.review_required = True
        u.review_reason = "topics-only"
        vision_second_pass([u], image_dir=Path("."), extract_fn=lambda _p: "AHU",
                           resolve_image=lambda _u: Path("AHU_02A.png"))
        self.assertFalse(u.review_required)
        self.assertIn("CONFIRMED", u.review_reason)

    def test_conflict_keeps_the_flag(self):
        u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
        u.review_required = True
        vision_second_pass([u], image_dir=Path("."), extract_fn=lambda _p: "FCU",
                           resolve_image=lambda _u: Path("x.png"))
        self.assertTrue(u.review_required)
        self.assertIn("CONFLICT", u.review_reason)

    def test_no_screenshot_keeps_flag_with_note(self):
        u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
        u.review_required = True
        vision_second_pass([u], image_dir=Path("."), extract_fn=lambda _p: "AHU",
                           resolve_image=lambda _u: None)
        self.assertTrue(u.review_required)
        self.assertIn("no screenshot", u.review_reason)

    def test_non_flagged_units_are_untouched(self):
        u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
        u.review_required = False
        vision_second_pass([u], image_dir=Path("."), extract_fn=lambda _p: "FCU",
                           resolve_image=lambda _u: Path("x.png"))
        self.assertFalse(u.review_required)
        self.assertEqual(u.review_reason, "")

    def test_load_topic_names_from_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "topics.csv"
            with p.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["topic_name", "x"])
                w.writerow(["Floor_02/DEV1_AHU_1/T", "1"])
                w.writerow(["", "2"])
            self.assertEqual(load_topic_names_from_csv(p), ["Floor_02/DEV1_AHU_1/T"])


if __name__ == "__main__":
    unittest.main()
