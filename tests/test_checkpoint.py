import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from checkpoint import RunCheckpoint, checkpoint_key  # noqa: E402
from extraction import extract_equipment_batch  # noqa: E402
from equipment_prompts import EquipmentPromptPackage  # noqa: E402
from models import (  # noqa: E402
    AIReadyImageRecord,
    EquipmentExtractionResponse,
    EquipmentExtractionRunResult,
)

SHA = "a" * 64
OTHER_SHA = "b" * 64


class FakeClient:
    def __init__(self, content='{"equipment":[]}'):
        self.content = content
        self.calls = 0

    async def chat_completions_create(self, *, model, messages, timeout_seconds=None):
        self.calls += 1
        return {"choices": [{"message": {"role": "assistant", "content": self.content}}]}


def image_record(root: Path, filename="ahu.png", sha=SHA, page=None):
    path = root / filename
    path.write_bytes(b"image")
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
        quality_flag=True,
        quality_status="passed",
        quality_reason="ok",
        warnings=[],
        extraction_eligible=True,
        preparation_status="prepared",
    )


def prompt_package():
    return EquipmentPromptPackage(
        prompt_version="equipment_extraction_v4",
        system_prompt="system",
        user_template="user",
        examples=(),
    )


def run_result(record: AIReadyImageRecord, status="succeeded", model="claude-haiku-4-5"):
    now = datetime.now(timezone.utc)
    kwargs = dict(
        source_filename=record.source_filename,
        source_relative_path=record.source_relative_path,
        source_sha256=record.source_sha256,
        source_file_type=record.source_file_type,
        prepared_image_path=record.prepared_image_local_path,
        prepared_image_filename=record.prepared_image_filename,
        image_mime_type=record.image_mime_type,
        pdf_page_number=record.source_page_number,
        prompt_version="equipment_extraction_v4",
        model_id=model,
        started_at=now,
        completed_at=now,
        status=status,
    )
    if status == "succeeded":
        kwargs["raw_assistant_response"] = '{"equipment":[]}'
        kwargs["parsed_response"] = EquipmentExtractionResponse(equipment=[])
    else:
        kwargs["error_type"] = "LLMConnectionError"
        kwargs["error_message"] = "boom"
    return EquipmentExtractionRunResult(**kwargs)


class TestCheckpointKey(unittest.TestCase):
    def test_key_distinguishes_page_prompt_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = image_record(root)
            page_record = image_record(root, filename="mech.pdf", page=2)
        base = checkpoint_key(record, "equipment_extraction_v4", "claude-haiku-4-5")
        self.assertNotEqual(
            base, checkpoint_key(page_record, "equipment_extraction_v4", "claude-haiku-4-5")
        )
        self.assertNotEqual(
            base, checkpoint_key(record, "equipment_extraction_v5", "claude-haiku-4-5")
        )
        self.assertNotEqual(
            base, checkpoint_key(record, "equipment_extraction_v4", "claude-opus-4-8")
        )


class TestRunCheckpoint(unittest.TestCase):
    def test_succeeded_result_round_trips_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = image_record(root)
            result = run_result(record)
            key = checkpoint_key(record, "equipment_extraction_v4", "claude-haiku-4-5")

            path = root / "checkpoint.jsonl"
            RunCheckpoint(path).record(key, result)

            revived = RunCheckpoint(path).succeeded_result(key)
            self.assertIsNotNone(revived)
            self.assertEqual(revived.model_dump(mode="json"), result.model_dump(mode="json"))

    def test_failed_entries_are_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = image_record(root)
            key = checkpoint_key(record, "equipment_extraction_v4", "claude-haiku-4-5")
            path = root / "checkpoint.jsonl"
            RunCheckpoint(path).record(key, run_result(record, status="transport_failed"))

            checkpoint = RunCheckpoint(path)
            self.assertEqual(checkpoint.status_for(key), "transport_failed")
            self.assertIsNone(checkpoint.succeeded_result(key))

    def test_last_entry_wins_for_a_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = image_record(root)
            key = checkpoint_key(record, "equipment_extraction_v4", "claude-haiku-4-5")
            path = root / "checkpoint.jsonl"
            first = RunCheckpoint(path)
            first.record(key, run_result(record, status="transport_failed"))
            first.record(key, run_result(record))

            checkpoint = RunCheckpoint(path)
            self.assertEqual(checkpoint.status_for(key), "succeeded")
            self.assertIsNotNone(checkpoint.succeeded_result(key))
            self.assertEqual(len(checkpoint), 1)

    def test_torn_trailing_line_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = image_record(root)
            key = checkpoint_key(record, "equipment_extraction_v4", "claude-haiku-4-5")
            path = root / "checkpoint.jsonl"
            RunCheckpoint(path).record(key, run_result(record))
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"key": "torn-entry", "status": "succ')  # crash mid-write

            checkpoint = RunCheckpoint(path)
            self.assertEqual(len(checkpoint), 1)
            self.assertIsNotNone(checkpoint.succeeded_result(key))

    def test_summary_counts_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = image_record(root, filename="a.png", sha=SHA)
            second = image_record(root, filename="b.png", sha=OTHER_SHA)
            path = root / "checkpoint.jsonl"
            checkpoint = RunCheckpoint(path)
            checkpoint.record(
                checkpoint_key(first, "v", "m"), run_result(first)
            )
            checkpoint.record(
                checkpoint_key(second, "v", "m"), run_result(second, status="transport_failed")
            )
            self.assertEqual(checkpoint.summary(), {"succeeded": 1, "transport_failed": 1})


class TestBatchOnResultHook(unittest.TestCase):
    def test_on_result_invoked_per_image_as_checkpoint_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = [
                image_record(root, filename="a.png", sha=SHA),
                image_record(root, filename="b.png", sha=OTHER_SHA),
            ]
            checkpoint = RunCheckpoint(root / "checkpoint.jsonl")

            def on_result(record, result):
                checkpoint.record(
                    checkpoint_key(record, "equipment_extraction_v4", "claude-haiku-4-5"),
                    result,
                )

            results = asyncio.run(
                extract_equipment_batch(
                    image_records=records,
                    prompt_package=prompt_package(),
                    model="claude-haiku-4-5",
                    client=FakeClient(),
                    on_result=on_result,
                )
            )
            self.assertEqual(len(results), 2)
            reloaded = RunCheckpoint(root / "checkpoint.jsonl")
            self.assertEqual(len(reloaded), 2)
            for record in records:
                key = checkpoint_key(record, "equipment_extraction_v4", "claude-haiku-4-5")
                self.assertIsNotNone(reloaded.succeeded_result(key))


if __name__ == "__main__":
    unittest.main()
