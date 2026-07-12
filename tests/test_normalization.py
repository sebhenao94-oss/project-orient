import csv
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import normalization  # noqa: E402
from models import DiscrepancyCategory, NormalizationStatus  # noqa: E402


PROPERTY_ID = "b470b97b-4ea7-481c-97b7-22a81a219587"
PROPERTY_NAME = "msa_orient_building_1"


def topic_row(raw_label, inferred_type, *, context=None):
    return {
        "snapshot_version": "w03",
        "property_id": PROPERTY_ID,
        "property_name": PROPERTY_NAME,
        "floor": "Floor_02",
        "raw_equipment_context": context or f"DEV1_{raw_label}",
        "raw_label": raw_label,
        "inferred_raw_type": inferred_type,
        "topic_count": "8",
        "evidence_strength": "multiple_point_evidence",
        "source_type": "topics",
        "review_required": "false",
        "review_reason": "",
    }


def llm_topic_row(
    raw_label,
    inferred_type,
    *,
    context=None,
    review_required="false",
    review_reason="",
):
    return {
        "snapshot_version": "w03-llm",
        "property_id": PROPERTY_ID,
        "property_name": PROPERTY_NAME,
        "floor": "Floor_02",
        "raw_equipment_context": context or f"DEV1_{raw_label}",
        "raw_label": raw_label,
        "inferred_raw_type": inferred_type,
        "confidence": "0.810",
        "topic_count": "8",
        "source_topics": f"Floor_02/{raw_label}/point_1",
        "source_method": "llm_assisted",
        "review_required": review_required,
        "review_reason": review_reason,
    }


def drawing_row(raw_label, canonical, equipment_type, *, run_status="succeeded"):
    return {
        "snapshot_version": "w03",
        "property_name": PROPERTY_NAME,
        "property_id": PROPERTY_ID,
        "floor": "Floor_02",
        "source_filename": "x.png",
        "source_relative_path": "x.png",
        "source_sha256": "d" * 64,
        "pdf_page_number": "",
        "prompt_version": "equipment_extraction_v3",
        "model_id": "Qwen/Qwen3-VL-2B-Instruct",
        "raw_label": raw_label,
        "llm_proposed_canonical_name": canonical,
        "equipment_type": equipment_type,
        "confidence": "0.99",
        "run_status": run_status,
        "review_required": "false",
        "review_reason": "",
    }


def write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def ambiguous_row(raw_label, inferred_type):
    return {
        "property_id": PROPERTY_ID,
        "floor_path": "Floor_02",
        "raw_equipment_context": f"DEV37159_{raw_label}",
        "raw_label": raw_label,
        "inferred_raw_type": inferred_type,
        "topic_count": "8",
        "path_floor": "2",
        "name_token_floor": "1",
        "status": "floor_ambiguous",
        "review_reason": "path=Floor_02 but unit name carries _1_ token; supervisor clarification pending",
    }


class CanonicalKeyTests(unittest.TestCase):
    def test_separators_and_zero_padding_collapse_to_same_key(self):
        # The two W3 sources spell the same unit differently.
        self.assertEqual(normalization.canonical_key("AHU-02A"), normalization.canonical_key("AHU_02A"))
        self.assertEqual(
            normalization.canonical_key("OAVAV_2_01"),
            normalization.canonical_key("OAVAV_02_01"),
        )
        self.assertEqual(
            normalization.canonical_key("VAVRH_2_01"),
            normalization.canonical_key("VAVRH_2_1"),
        )

    def test_device_prefix_is_stripped(self):
        self.assertEqual(normalization.canonical_key("DEV37159_EAVAV_1_01"), "EAVAV_1_1")

    def test_contested_floor_digit_is_preserved(self):
        # The whole point of the floor-ambiguity question: _1_ and _2_ must NOT
        # collapse to the same key.
        self.assertNotEqual(
            normalization.canonical_key("OAVAV_1_02"),
            normalization.canonical_key("OAVAV_2_02"),
        )

    def test_blank_label_raises(self):
        with self.assertRaises(normalization.NormalizationInputError):
            normalization.canonical_key("DEV123_")


class ReconcileTests(unittest.TestCase):
    def test_matched_unit_is_settled(self):
        records = normalization.reconcile_floor_02(
            [topic_row("AHU-02A", "AHU")],
            [drawing_row("AHU 02 A", "AHU_02A", "AHU")],
            {},
        )
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.discrepancy_category, DiscrepancyCategory.MATCHED)
        self.assertEqual(record.status, NormalizationStatus.SETTLED)
        self.assertFalse(record.review_required)
        self.assertTrue(record.in_topics and record.in_drawings)

    def test_upstream_flag_routes_matched_unit_to_review(self):
        topic = topic_row("AHU-02A", "AHU")
        topic["review_required"] = "true"
        topic["review_reason"] = "vision second pass CONFLICT: sees FCU"
        records = normalization.reconcile_floor_02(
            [topic],
            [drawing_row("AHU 02 A", "AHU_02A", "AHU")],
            {},
        )

        record = records[0]
        self.assertEqual(record.discrepancy_category, DiscrepancyCategory.MATCHED)
        self.assertEqual(record.status, NormalizationStatus.REVIEW_REQUIRED)
        self.assertTrue(record.review_required)
        self.assertEqual(record.review_reason, topic["review_reason"])

    def test_upstream_reason_is_appended_to_reconciliation_reason(self):
        topic = topic_row("VAV_02_02", "VAV")
        topic["review_required"] = "yes"
        topic["review_reason"] = "topics parser found an ambiguous unit boundary"
        records = normalization.reconcile_floor_02(
            [topic],
            [drawing_row("VAV 02 02", "VAV_02_2", "FCU")],
            {},
        )

        self.assertEqual(
            records[0].review_reason,
            "type mismatch: topics=VAV drawings=FCU; "
            "topics parser found an ambiguous unit boundary",
        )

    def test_drawing_review_flag_routes_matched_unit_to_review(self):
        drawing = drawing_row("AHU 02 A", "AHU_02A", "AHU")
        drawing["review_required"] = "true"
        drawing["review_reason"] = "low extraction confidence: 0.71"
        records = normalization.reconcile_floor_02(
            [topic_row("AHU-02A", "AHU")],
            [drawing],
            {},
        )

        self.assertEqual(records[0].discrepancy_category, DiscrepancyCategory.MATCHED)
        self.assertEqual(records[0].status, NormalizationStatus.REVIEW_REQUIRED)
        self.assertTrue(records[0].review_required)
        self.assertEqual(records[0].review_reason, drawing["review_reason"])

    def test_drawing_review_state_is_merged_across_duplicate_sources(self):
        first = drawing_row("AHU 02 A", "AHU_02A", "AHU")
        first["source_filename"] = "ahu.png"
        second = drawing_row("AHU-02A", "AHU_02A", "AHU")
        second["source_filename"] = "mech.pdf"
        second["review_required"] = "yes"
        second["review_reason"] = "drawing sources disagree on the unit label"
        records = normalization.reconcile_floor_02(
            [topic_row("AHU-02A", "AHU")],
            [first, second],
            {},
        )

        self.assertTrue(records[0].review_required)
        self.assertEqual(records[0].status, NormalizationStatus.REVIEW_REQUIRED)
        self.assertEqual(records[0].review_reason, second["review_reason"])
        self.assertEqual(records[0].source_files, "ahu.png;mech.pdf")

    def test_upstream_resolution_note_is_retained_without_reopening_review(self):
        topic = topic_row("AHU-02A", "AHU")
        topic["review_reason"] = "vision second pass CONFIRMED AHU"
        records = normalization.reconcile_floor_02(
            [topic],
            [drawing_row("AHU 02 A", "AHU_02A", "AHU")],
            {},
        )

        self.assertEqual(records[0].status, NormalizationStatus.SETTLED)
        self.assertFalse(records[0].review_required)
        self.assertEqual(records[0].review_reason, topic["review_reason"])

    def test_topics_only_is_a_gap_routed_to_review(self):
        records = normalization.reconcile_floor_02([topic_row("AHU_2_01", "AHU")], [], {})
        self.assertEqual(records[0].discrepancy_category, DiscrepancyCategory.TOPICS_ONLY)
        self.assertTrue(records[0].review_required)
        self.assertTrue(records[0].in_topics)
        self.assertFalse(records[0].in_drawings)

    def test_drawing_only_is_a_gap_routed_to_review(self):
        records = normalization.reconcile_floor_02(
            [], [drawing_row("DAWNV 2 09", "DAWNV_2_09", "VAV")], {}
        )
        self.assertEqual(records[0].discrepancy_category, DiscrepancyCategory.DRAWING_ONLY)
        self.assertTrue(records[0].review_required)

    def test_type_mismatch_is_flagged(self):
        records = normalization.reconcile_floor_02(
            [topic_row("VAV_02_02", "VAV")],
            [drawing_row("VAV 02 02", "VAV_02_2", "FCU")],
            {},
        )
        self.assertEqual(records[0].discrepancy_category, DiscrepancyCategory.TYPE_MISMATCH)
        self.assertEqual(records[0].status, NormalizationStatus.REVIEW_REQUIRED)
        self.assertIn("VAV", records[0].review_reason)
        self.assertIn("FCU", records[0].review_reason)

    def test_failed_drawing_rows_are_ignored(self):
        records = normalization.reconcile_floor_02(
            [],
            [drawing_row("X 1", "X_1", "VAV", run_status="parse_failed")],
            {},
        )
        self.assertEqual(records, [])

    def test_repeated_drawing_rows_collapse_to_one_unit(self):
        records = normalization.reconcile_floor_02(
            [],
            [
                drawing_row("VAVRH 2 1", "VAVRH_2_1", "VAVRH"),
                drawing_row("VAVRH_2_1", "VAVRH_2_1", "VAVRH"),
            ],
            {},
        )
        self.assertEqual(len(records), 1)


class FloorAmbiguousTests(unittest.TestCase):
    """The seven contested-floor units must always be routed to review."""

    def test_ambiguous_unit_overrides_a_topics_match(self):
        ambiguous = {normalization.canonical_key("EAVAV_1_01"): ambiguous_row("EAVAV_1_01", "EAVAV")}
        records = normalization.reconcile_floor_02(
            [topic_row("EAVAV_1_01", "EAVAV")],
            [],
            ambiguous,
        )
        record = records[0]
        self.assertEqual(record.status, NormalizationStatus.FLOOR_AMBIGUOUS)
        self.assertEqual(record.discrepancy_category, DiscrepancyCategory.FLOOR_AMBIGUOUS)
        self.assertTrue(record.review_required)
        self.assertTrue(record.review_reason.strip())

    def test_ambiguous_unit_is_never_silently_settled(self):
        # Even if it appears in both sources with a consistent type, a contested
        # unit must not become "settled".
        ambiguous = {normalization.canonical_key("OAVAV_1_02"): ambiguous_row("OAVAV_1_02", "OAVAV")}
        records = normalization.reconcile_floor_02(
            [topic_row("OAVAV_1_02", "OAVAV")],
            [drawing_row("OAVAV 1 02", "OAVAV_1_02", "OAVAV")],
            ambiguous,
        )
        self.assertNotEqual(records[0].status, NormalizationStatus.SETTLED)
        self.assertEqual(records[0].status, NormalizationStatus.FLOOR_AMBIGUOUS)


class SummaryAndWriteTests(unittest.TestCase):
    def _records(self):
        return normalization.reconcile_floor_02(
            [topic_row("AHU-02A", "AHU"), topic_row("AHU_2_01", "AHU")],
            [
                drawing_row("AHU 02 A", "AHU_02A", "AHU"),
                drawing_row("DAWNV 2 09", "DAWNV_2_09", "VAV"),
            ],
            {},
        )

    def test_summary_counts(self):
        summary = normalization.summarize(self._records())
        self.assertEqual(summary.total_units, 3)
        self.assertEqual(summary.matched_count, 1)
        self.assertEqual(summary.topics_only_count, 1)
        self.assertEqual(summary.drawing_only_count, 1)
        self.assertEqual(summary.review_required_count, 2)

    def test_write_snapshot_round_trips_headers_and_rows(self):
        records = self._records()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "normalized_equipment_floor_02.csv"
            normalization.write_normalized_snapshot(records, out)
            with out.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(list(reader.fieldnames), normalization.NORMALIZED_SNAPSHOT_HEADERS)
                rows = list(reader)
            self.assertEqual(len(rows), len(records))

    def test_write_refuses_to_overwrite_without_flag(self):
        records = self._records()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.csv"
            normalization.write_normalized_snapshot(records, out)
            with self.assertRaises(normalization.NormalizationArtifactError):
                normalization.write_normalized_snapshot(records, out)
            normalization.write_normalized_snapshot(records, out, overwrite=True)


class InputValidationTests(unittest.TestCase):
    def test_llm_header_literal_matches_topics_parser(self):
        import topics_parser

        self.assertEqual(
            normalization.TOPICS_SNAPSHOT_HEADERS_LLM,
            topics_parser.TOPICS_EQUIPMENT_SNAPSHOT_COLUMNS,
        )

    def test_missing_file_raises(self):
        with self.assertRaises(normalization.NormalizationInputError):
            normalization._read_rows(Path("does_not_exist.csv"), normalization.TOPICS_SNAPSHOT_HEADERS)

    def test_bad_headers_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.csv"
            bad.write_text("wrong,headers\n1,2\n", encoding="utf-8")
            with self.assertRaises(normalization.NormalizationInputError):
                normalization._read_rows(bad, normalization.TOPICS_SNAPSHOT_HEADERS)

    def test_invalid_topics_headers_name_both_accepted_schemas(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.csv"
            bad.write_text("wrong,headers\n1,2\n", encoding="utf-8")
            with self.assertRaises(normalization.NormalizationInputError) as raised:
                normalization._read_rows(
                    bad,
                    [
                        normalization.TOPICS_SNAPSHOT_HEADERS,
                        normalization.TOPICS_SNAPSHOT_HEADERS_LLM,
                    ],
                )

        message = str(raised.exception)
        self.assertIn("accepted schema 1", message)
        self.assertIn("evidence_strength", message)
        self.assertIn("accepted schema 2", message)
        self.assertIn("source_method", message)
        self.assertIn("actual headers: [wrong, headers]", message)

    def test_normalize_accepts_llm_topics_and_preserves_matched_flag(self):
        reason = "vision second pass CONFLICT: sees FCU, topics say AHU"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            topics = root / "topics.csv"
            drawings = root / "drawings.csv"
            ambiguous = root / "ambiguous.csv"
            write_csv(
                topics,
                normalization.TOPICS_SNAPSHOT_HEADERS_LLM,
                [
                    llm_topic_row(
                        "AHU-02A",
                        "AHU",
                        review_required="true",
                        review_reason=reason,
                    )
                ],
            )
            write_csv(
                drawings,
                normalization.DRAWING_SNAPSHOT_HEADERS,
                [drawing_row("AHU 02 A", "AHU_02A", "AHU")],
            )
            write_csv(ambiguous, normalization.FLOOR_AMBIGUOUS_HEADERS, [])

            records = normalization.normalize_floor_02(
                topics_path=topics,
                drawing_path=drawings,
                floor_ambiguous_path=ambiguous,
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].discrepancy_category, DiscrepancyCategory.MATCHED)
        self.assertEqual(records[0].status, NormalizationStatus.REVIEW_REQUIRED)
        self.assertTrue(records[0].review_required)
        self.assertEqual(records[0].review_reason, reason)

    def test_normalize_still_accepts_unflagged_deterministic_topics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            topics = root / "topics.csv"
            drawings = root / "drawings.csv"
            ambiguous = root / "ambiguous.csv"
            write_csv(
                topics,
                normalization.TOPICS_SNAPSHOT_HEADERS,
                [topic_row("AHU-02A", "AHU")],
            )
            write_csv(
                drawings,
                normalization.DRAWING_SNAPSHOT_HEADERS,
                [drawing_row("AHU 02 A", "AHU_02A", "AHU")],
            )
            write_csv(ambiguous, normalization.FLOOR_AMBIGUOUS_HEADERS, [])

            records = normalization.normalize_floor_02(
                topics_path=topics,
                drawing_path=drawings,
                floor_ambiguous_path=ambiguous,
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, NormalizationStatus.SETTLED)
        self.assertFalse(records[0].review_required)


if __name__ == "__main__":
    unittest.main()
