import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _path in (PROJECT_ROOT, PROJECT_ROOT / "pipeline"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import topics_parser  # noqa: E402
from topics_parser import (  # noqa: E402
    DEFAULT_EQUIPMENT_TYPE_CONTEXT_PATH,
    ParsedTopicEquipment,
    TopicsCoverageError,
    default_vision_extract_fn,
    parse_topics_equipment,
    parse_units_json,
    select_vision_candidate_type,
    validate_against_paths,
    validate_topic_coverage,
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
        source_topics = [topic for parsed in canned for topic in parsed.source_topics]
        result = parse_topics_equipment(
            source_topics, floor_prefix=FLOOR, parse_fn=lambda _names: canned
        )
        self.assertFalse(result[0].review_required)
        self.assertTrue(result[1].review_required)


class TopicCoverageTests(unittest.TestCase):
    def test_exact_multiset_coverage_allows_repeated_input_occurrences(self):
        topics = ["Floor_02/AHU/T", "Floor_02/AHU/T"]
        validate_topic_coverage(topics, [unit("AHU", "AHU", topics)])

    def test_reports_missing_unexpected_and_duplicate_assignments(self):
        parsed = [unit("AHU", "AHU", ["topic-a", "topic-a", "topic-c"])]
        with self.assertRaises(TopicsCoverageError) as raised:
            validate_topic_coverage(["topic-a", "topic-b"], parsed)

        error = raised.exception
        self.assertEqual(error.missing, {"topic-b": 1})
        self.assertEqual(error.unexpected, {"topic-c": 1})
        self.assertEqual(error.duplicates, {"topic-a": 1})
        self.assertIn("missing", str(error))
        self.assertIn("unexpected", str(error))
        self.assertIn("duplicate", str(error))

    def test_error_message_is_bounded_for_large_topic_sets(self):
        topics = [f"topic-{index}-{'x' * 300}" for index in range(100)]
        with self.assertRaises(TopicsCoverageError) as raised:
            validate_topic_coverage(topics, [])
        self.assertLess(len(str(raised.exception)), 700)
        self.assertIn("+97 more distinct", str(raised.exception))

    def test_parse_rejects_incomplete_model_output_before_validation(self):
        with self.assertRaises(TopicsCoverageError):
            parse_topics_equipment(
                ["topic-a", "topic-b"],
                floor_prefix=FLOOR,
                parse_fn=lambda _names: [unit("AHU", "AHU", ["topic-a"])],
            )

    def test_live_cli_returns_nonzero_without_writing_incomplete_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic_csv = Path(tmp) / "topics.csv"
            output_csv = Path(tmp) / "output.csv"
            with topic_csv.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["topic_name"])
                writer.writerow(["topic-a"])
            incomplete = lambda _names: [unit("AHU", "AHU", [])]
            with patch.object(
                topics_parser,
                "anthropic_topics_parse_fn",
                return_value=incomplete,
            ), redirect_stderr(io.StringIO()) as stderr, redirect_stdout(io.StringIO()):
                code = topics_parser.main(
                    [
                        "--topics-csv",
                        str(topic_csv),
                        "--output-path",
                        str(output_csv),
                        "--run-live",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertFalse(output_csv.exists())
        self.assertIn("Topics parse rejected", stderr.getvalue())


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
        u.review_reason = "equipment type uncertain"
        vision_second_pass([u], image_dir=Path("."), extract_fn=lambda _p, _u: "AHU",
                           resolve_image=lambda _u: Path("AHU_02A.png"))
        self.assertFalse(u.review_required)
        self.assertIn("CONFIRMED", u.review_reason)

    def test_confirmation_does_not_clear_non_type_ambiguity(self):
        reasons = (
            "topics span multiple path contexts ['AHU_01', 'AHU_02']",
            "no deterministic path match (non-standard topic format)",
            "floor ambiguous",
            "equipment identity ambiguous",
            "type-only: floor ambiguous",
            "topics-only",
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
                u.review_required = True
                u.review_reason = reason
                vision_second_pass(
                    [u],
                    image_dir=Path("."),
                    extract_fn=lambda _p, _u: "AHU",
                    resolve_image=lambda _u: Path("AHU.png"),
                )
                self.assertTrue(u.review_required)
                self.assertIn(reason, u.review_reason)
                self.assertIn("CONFIRMED", u.review_reason)
                self.assertIn("review retained", u.review_reason)

    def test_confirmation_does_not_clear_mixed_type_and_floor_reasons(self):
        u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
        u.review_required = True
        u.review_reason = "equipment type uncertain; floor ambiguous"
        vision_second_pass(
            [u],
            image_dir=Path("."),
            extract_fn=lambda _p, _u: "AHU",
            resolve_image=lambda _u: Path("AHU.png"),
        )
        self.assertTrue(u.review_required)
        self.assertTrue(u.review_reason.startswith("equipment type uncertain; floor ambiguous"))

    def test_conflict_keeps_the_flag(self):
        u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
        u.review_required = True
        vision_second_pass([u], image_dir=Path("."), extract_fn=lambda _p, _u: "FCU",
                           resolve_image=lambda _u: Path("x.png"))
        self.assertTrue(u.review_required)
        self.assertIn("CONFLICT", u.review_reason)

    def test_no_screenshot_keeps_flag_with_note(self):
        u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
        u.review_required = True
        vision_second_pass([u], image_dir=Path("."), extract_fn=lambda _p, _u: "AHU",
                           resolve_image=lambda _u: None)
        self.assertTrue(u.review_required)
        self.assertIn("no screenshot", u.review_reason)

    def test_non_flagged_units_are_untouched(self):
        u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
        u.review_required = False
        vision_second_pass([u], image_dir=Path("."), extract_fn=lambda _p, _u: "FCU",
                           resolve_image=lambda _u: Path("x.png"))
        self.assertFalse(u.review_required)
        self.assertEqual(u.review_reason, "")

    def test_extractor_receives_the_specific_target_unit(self):
        u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
        u.review_required = True
        u.review_reason = "equipment type uncertain"
        seen = []

        def extract(_path, target_unit):
            seen.append(target_unit)
            return "AHU"

        vision_second_pass(
            [u],
            image_dir=Path("."),
            extract_fn=extract,
            resolve_image=lambda _u: Path("AHU.png"),
        )
        self.assertEqual(seen, [u])

    def test_candidate_selection_matches_raw_or_canonical_label(self):
        u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
        candidates = [
            {
                "raw_label": "FCU 2-01",
                "canonical_name": "FCU_2-01",
                "equipment_type": "FCU",
            },
            {
                "raw_label": "air handler",
                "canonical_name": "AHU_02_01",
                "equipment_type": "AHU",
            },
        ]
        self.assertEqual(select_vision_candidate_type(u, candidates), "AHU")

    def test_candidate_selection_rejects_no_match_or_ambiguous_match(self):
        u = unit("AHU_2-01", "AHU", ["Floor_02/DEV1_AHU_2_01/T"])
        unrelated = {
            "raw_label": "FCU 2-01",
            "canonical_name": "FCU_2-01",
            "equipment_type": "FCU",
        }
        matching = {
            "raw_label": "AHU 2-01",
            "canonical_name": "AHU_2-01",
            "equipment_type": "AHU",
        }
        self.assertIsNone(select_vision_candidate_type(u, [unrelated]))
        self.assertIsNone(select_vision_candidate_type(u, [matching, dict(matching)]))

    def test_default_extractor_uses_unit_floor_target_and_simple_context(self):
        async def fake_extract_equipment_batch(**_kwargs):
            return [
                SimpleNamespace(
                    status="succeeded",
                    parsed_response=SimpleNamespace(
                        equipment=[
                            {
                                "raw_label": "FCU 7-01",
                                "canonical_name": "FCU_7-01",
                                "equipment_type": "FCU",
                            },
                            {
                                "raw_label": "AHU 7-01",
                                "canonical_name": "AHU_7-01",
                                "equipment_type": "AHU",
                            },
                        ]
                    ),
                )
            ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "AHU_7-01.png"
            image.write_bytes(b"image")
            u = unit("AHU_7-01", "AHU", ["Floor_07/DEV1_AHU_7_01/T"])
            u.floor = "Floor_07"
            with patch(
                "equipment_prompts.load_equipment_prompt_package",
                return_value=object(),
            ) as load_package, patch(
                "extraction._prepared_image_records_from_dir",
                return_value=[object()],
            ) as prepare_records, patch(
                "extraction.extract_equipment_batch",
                new=fake_extract_equipment_batch,
            ):
                extract = default_vision_extract_fn(
                    prompt_root=root / "prompts",
                    example_image_dir=root / "examples",
                    model="test-model",
                )
                detected = extract(image, u)

        self.assertEqual(detected, "AHU")
        self.assertEqual(prepare_records.call_args.kwargs["floor"], "Floor_07")
        self.assertEqual(
            load_package.call_args.kwargs["type_context_path"],
            DEFAULT_EQUIPMENT_TYPE_CONTEXT_PATH,
        )

    def test_default_extractor_allows_context_to_be_disabled_for_tests(self):
        with patch(
            "equipment_prompts.load_equipment_prompt_package",
            return_value=object(),
        ) as load_package:
            default_vision_extract_fn(
                prompt_root=Path("prompts"),
                example_image_dir=Path("examples"),
                model="test-model",
                type_context_path=None,
            )
        self.assertIsNone(load_package.call_args.kwargs["type_context_path"])

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
