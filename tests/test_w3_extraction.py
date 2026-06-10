import asyncio
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import extraction  # noqa: E402
from equipment_prompts import EquipmentPromptPackage  # noqa: E402
from llm_client import LLMConnectionError  # noqa: E402
from models import AIReadyImageRecord, EquipmentExtractionResponse  # noqa: E402


SHA = "a" * 64


class FakeClient:
    def __init__(self, responses=None, error=None, delay=0):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.delay = delay

    async def chat_completions_create(self, *, model, messages, timeout_seconds=None):
        self.calls.append({"model": model, "messages": messages})
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.error:
                raise self.error
            content = self.responses.pop(0) if self.responses else '{"equipment":[]}'
            return {"choices": [{"message": {"role": "assistant", "content": content}}]}
        finally:
            self.active -= 1


def write_image(root: Path, filename="ahu.png") -> Path:
    path = root / filename
    path.write_bytes(b"image")
    return path


def image_record(root: Path, filename="ahu.png", eligible=True, sha=SHA, page=None):
    path = write_image(root, filename)
    return AIReadyImageRecord(
        source_filename=filename,
        source_relative_path=filename,
        source_file_type="pdf" if page else "image",
        source_sha256=sha,
        source_local_path=str(path),
        raw_s3_key="Team-4/raw/images/" + filename,
        prepared_image_local_path=str(path),
        prepared_image_filename=filename,
        image_format="PNG",
        image_mime_type="image/png",
        source_page_number=page,
        width=1200,
        height=800,
        pixel_count=960000,
        quality_flag=eligible,
        quality_status="passed" if eligible else "failed",
        quality_reason="ok" if eligible else "too small",
        warnings=[],
        extraction_eligible=eligible,
        preparation_status="prepared" if eligible else "quality_failed",
    )


def prompt_package():
    return EquipmentPromptPackage(
        prompt_version="equipment_extraction_v2",
        system_prompt="system",
        user_template="extract",
        examples=(),
    )


def success_json(label="AHU 02 A", confidence=0.98):
    return json.dumps(
        {
            "equipment": [
                {
                    "raw_label": label,
                    "canonical_name": label.replace(" ", "_"),
                    "equipment_type": "AHU",
                    "confidence": confidence,
                }
            ]
        }
    )


class TestSingleImageExtraction(unittest.IsolatedAsyncioTestCase):
    async def test_success_preserves_raw_response_and_parsed_result(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            raw = success_json()
            result = await extraction.extract_equipment_from_image(
                image_record=image_record(Path(tmp_dir)),
                prompt_package=prompt_package(),
                model="qwen-test",
                client=FakeClient(responses=[raw]),
            )

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.raw_assistant_response, raw)
        self.assertIsInstance(result.parsed_response, EquipmentExtractionResponse)
        self.assertEqual(result.parsed_response.equipment[0].raw_label, "AHU 02 A")
        self.assertEqual(result.source_sha256, SHA)
        self.assertEqual(result.prompt_version, "equipment_extraction_v2")

    async def test_transport_failure_returns_result(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = await extraction.extract_equipment_from_image(
                image_record=image_record(Path(tmp_dir)),
                prompt_package=prompt_package(),
                model="qwen-test",
                client=FakeClient(error=LLMConnectionError("offline")),
            )

        self.assertEqual(result.status, "transport_failed")
        self.assertEqual(result.error_type, "LLMConnectionError")
        self.assertIsNone(result.raw_assistant_response)

    async def test_malformed_json_returns_parse_failure_with_raw_response(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = await extraction.extract_equipment_from_image(
                image_record=image_record(Path(tmp_dir)),
                prompt_package=prompt_package(),
                model="qwen-test",
                client=FakeClient(responses=["not json"]),
            )

        self.assertEqual(result.status, "parse_failed")
        self.assertEqual(result.raw_assistant_response, "not json")
        self.assertIsNone(result.parsed_response)

    async def test_schema_invalid_response_returns_validation_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            raw = json.dumps(
                {
                    "equipment": [
                        {
                            "raw_label": "EAVAV 1",
                            "canonical_name": "EAVAV_1",
                            "equipment_type": "EAVAV",
                            "confidence": 0.8,
                        }
                    ]
                }
            )
            result = await extraction.extract_equipment_from_image(
                image_record=image_record(Path(tmp_dir)),
                prompt_package=prompt_package(),
                model="qwen-test",
                client=FakeClient(responses=[raw]),
            )

        self.assertEqual(result.status, "validation_failed")
        self.assertEqual(result.raw_assistant_response, raw)

    async def test_ineligible_image_is_skipped_without_client_call(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = FakeClient(responses=[success_json()])
            result = await extraction.extract_equipment_from_image(
                image_record=image_record(Path(tmp_dir), eligible=False),
                prompt_package=prompt_package(),
                model="qwen-test",
                client=client,
            )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(client.calls, [])


class TestBatchExtraction(unittest.IsolatedAsyncioTestCase):
    async def test_batch_preserves_order_and_one_result_per_input(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            records = [image_record(root, "a.png"), image_record(root, "b.png")]
            client = FakeClient(responses=[success_json("A"), "not json"])
            results = await extraction.extract_equipment_batch(
                image_records=records,
                prompt_package=prompt_package(),
                model="qwen-test",
                max_concurrency=1,
                client=client,
            )

        self.assertEqual([result.source_filename for result in results], ["a.png", "b.png"])
        self.assertEqual([result.status for result in results], ["succeeded", "parse_failed"])
        self.assertEqual(len(results), 2)

    async def test_batch_respects_concurrency_bound(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            records = [image_record(root, f"{index}.png") for index in range(5)]
            client = FakeClient(responses=[success_json(str(index)) for index in range(5)], delay=0.01)
            await extraction.extract_equipment_batch(
                image_records=records,
                prompt_package=prompt_package(),
                model="qwen-test",
                max_concurrency=2,
                client=client,
            )

        self.assertLessEqual(client.max_active, 2)

    async def test_invalid_concurrency_fails(self):
        with self.assertRaisesRegex(ValueError, "max_concurrency"):
            await extraction.extract_equipment_batch(
                image_records=[],
                prompt_package=prompt_package(),
                model="qwen-test",
                max_concurrency=0,
                client=FakeClient(),
            )


class TestExtractionArtifacts(unittest.TestCase):
    def _success_result(self, root: Path, confidence=0.98):
        return asyncio.run(
            extraction.extract_equipment_from_image(
                image_record=image_record(root, page=1),
                prompt_package=prompt_package(),
                model="qwen-test",
                client=FakeClient(responses=[success_json(confidence=confidence)]),
            )
        )

    def test_jsonl_artifact_is_deterministic_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result = self._success_result(root)
            output_path = root / "runs.jsonl"

            extraction.write_extraction_run_jsonl([result], output_path)
            first = output_path.read_text(encoding="utf-8")
            with self.assertRaises(extraction.ExtractionArtifactError):
                extraction.write_extraction_run_jsonl([result], output_path)

        self.assertEqual(len(first.strip().splitlines()), 1)
        self.assertIn('"status": "succeeded"', first)

    def test_drawing_snapshot_has_expected_columns_and_low_confidence_review(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            good = self._success_result(root, confidence=0.98)
            low = self._success_result(root, confidence=0.5)
            failed = asyncio.run(
                extraction.extract_equipment_from_image(
                    image_record=image_record(root, "bad.png"),
                    prompt_package=prompt_package(),
                    model="qwen-test",
                    client=FakeClient(responses=["not json"]),
                )
            )
            output_path = root / "drawing.csv"

            extraction.write_drawing_equipment_snapshot(
                [good, low, failed],
                output_path,
                snapshot_version="w03",
                property_name="msa_orient_building_1",
                property_id="property-id",
                floor="Floor_02",
            )
            with output_path.open("r", encoding="utf-8") as csv_file:
                rows = list(csv.DictReader(csv_file))

        self.assertEqual(list(rows[0].keys()), list(extraction.DRAWING_EQUIPMENT_SNAPSHOT_COLUMNS))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["review_required"], "false")
        self.assertEqual(rows[1]["review_required"], "true")
        self.assertEqual(rows[1]["review_reason"], "low_confidence")
        self.assertEqual(rows[0]["floor"], "Floor_02")
        self.assertEqual(rows[0]["llm_proposed_canonical_name"], "AHU_02_A")


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None
        self.closed = False

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)

    def cursor(self):
        return self.cursor_obj


class TestTopicsSnapshotExporter(unittest.TestCase):
    def test_topics_snapshot_groups_second_segment_and_classifies_with_precedence(self):
        rows = [
            ("Floor_02/DEV1_VAVRH_2_01/ActCoolSP",),
            ("Floor_02/DEV1_VAVRH_2_01/ActHeatSP",),
            ("Floor_02/DEV2_OAVAV_1_01/ActFlow",),
            ("Floor_02/DEV3_VAV_02_05/ActFlow",),
            ("Floor_03/DEV9_AHU/Other",),
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            connection = FakeConnection(rows)
            output_path = Path(tmp_dir) / "topics.csv"
            result = extraction.export_topics_equipment_snapshot(
                connection=connection,
                property_id="pid",
                property_name="property",
                floor_prefix="Floor_02",
                output_path=output_path,
                snapshot_version="w03",
                expected_distinct_context_count=3,
            )
            with output_path.open("r", encoding="utf-8") as csv_file:
                output_rows = list(csv.DictReader(csv_file))

        self.assertEqual(result.distinct_context_count, 3)
        self.assertIn("SELECT", connection.cursor_obj.query.upper())
        self.assertNotIn("UPDATE", connection.cursor_obj.query.upper())
        self.assertTrue(connection.cursor_obj.closed)
        self.assertEqual([row["raw_label"] for row in output_rows], ["VAVRH_2_01", "OAVAV_1_01", "VAV_02_05"])
        self.assertEqual([row["inferred_raw_type"] for row in output_rows], ["VAVRH", "OAVAV", "VAV"])
        self.assertEqual(output_rows[0]["review_required"], "false")
        self.assertEqual(output_rows[1]["review_required"], "true")
        self.assertEqual(output_rows[0]["evidence_strength"], "multiple_point_evidence")

    def test_topics_snapshot_rejects_existing_output_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "topics.csv"
            output_path.write_text("existing", encoding="utf-8")
            with self.assertRaises(extraction.ExtractionArtifactError):
                extraction.export_topics_equipment_snapshot(
                    connection=FakeConnection([]),
                    property_id="pid",
                    property_name="property",
                    floor_prefix="Floor_02",
                    output_path=output_path,
                    snapshot_version="w03",
                )

    def test_topics_snapshot_count_expectation_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaisesRegex(extraction.ExtractionArtifactError, "Expected 37"):
                extraction.export_topics_equipment_snapshot(
                    connection=FakeConnection([("Floor_02/DEV1_AHU/Point",)]),
                    property_id="pid",
                    property_name="property",
                    floor_prefix="Floor_02",
                    output_path=Path(tmp_dir) / "topics.csv",
                    snapshot_version="w03",
                    expected_distinct_context_count=37,
                )


class TestExtractionCli(unittest.TestCase):
    def test_module_help_works(self):
        import subprocess

        completed = subprocess.run(
            [sys.executable, "-m", "pipeline.extraction", "--help"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("W3 equipment extraction", completed.stdout)


if __name__ == "__main__":
    unittest.main()