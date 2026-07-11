import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import cost  # noqa: E402
from cost import UsageRecorder, write_run_metrics  # noqa: E402
from equipment_prompts import EquipmentPromptPackage  # noqa: E402
from llm_client import request_equipment_extraction  # noqa: E402
from equipment_prompts import build_equipment_message_plan  # noqa: E402


class TestUsageRecorder(unittest.TestCase):
    def test_accumulates_per_model_and_batch_mode(self):
        recorder = UsageRecorder()
        recorder.record("claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 10})
        recorder.record("claude-haiku-4-5", {"input_tokens": 50, "output_tokens": 5})
        recorder.record("claude-opus-4-8", {"input_tokens": 30, "output_tokens": 3}, batch=True)

        snapshot = recorder.snapshot()
        self.assertEqual(len(snapshot["models"]), 2)
        haiku = next(entry for entry in snapshot["models"] if entry["model"] == "claude-haiku-4-5")
        self.assertEqual(haiku["calls"], 2)
        self.assertEqual(haiku["input_tokens"], 150)
        self.assertEqual(haiku["output_tokens"], 15)
        self.assertFalse(haiku["batch"])
        opus = next(entry for entry in snapshot["models"] if entry["model"] == "claude-opus-4-8")
        self.assertTrue(opus["batch"])
        self.assertEqual(snapshot["totals"]["calls"], 3)
        self.assertEqual(snapshot["totals"]["input_tokens"], 180)
        self.assertEqual(snapshot["totals"]["total_tokens"], 180 + 18)

    def test_batch_bucket_costs_half_of_realtime(self):
        realtime = UsageRecorder()
        realtime.record("claude-haiku-4-5", {"input_tokens": 1_000_000})
        batch = UsageRecorder()
        batch.record("claude-haiku-4-5", {"input_tokens": 1_000_000}, batch=True)
        realtime_cost = realtime.snapshot()["totals"]["estimated_cost_usd"]
        batch_cost = batch.snapshot()["totals"]["estimated_cost_usd"]
        self.assertAlmostEqual(batch_cost, realtime_cost / 2)

    def test_reset_clears_buckets(self):
        recorder = UsageRecorder()
        recorder.record("claude-haiku-4-5", {"input_tokens": 100})
        recorder.reset()
        self.assertEqual(recorder.snapshot()["totals"]["calls"], 0)

    def test_unknown_model_costs_zero_but_counts_tokens(self):
        recorder = UsageRecorder()
        recorder.record("qwen3-vl-2b", {"input_tokens": 500, "output_tokens": 50})
        snapshot = recorder.snapshot()
        self.assertEqual(snapshot["totals"]["total_tokens"], 550)
        self.assertEqual(snapshot["totals"]["estimated_cost_usd"], 0.0)


class TestWriteRunMetrics(unittest.TestCase):
    def test_writes_run_counts_and_usage_sections(self):
        recorder = UsageRecorder()
        recorder.record("claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 2})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_metrics.json"
            write_run_metrics(
                path,
                run={"command": "extract", "model": "claude-haiku-4-5"},
                counts={"images_total": 3, "equipment_candidates_confident": 2},
                recorder=recorder,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["run"]["command"], "extract")
        self.assertEqual(payload["counts"]["images_total"], 3)
        self.assertEqual(payload["usage"]["totals"]["input_tokens"], 10)
        self.assertIn("written_at", payload)


class UsageReportingFakeClient:
    """OpenAI-envelope fake that includes a usage block, as the Anthropic
    adapter's wrapped responses do."""

    async def chat_completions_create(self, *, model, messages, timeout_seconds=None):
        return {
            "choices": [{"message": {"role": "assistant", "content": '{"equipment":[]}'}}],
            "usage": {"input_tokens": 42, "output_tokens": 7},
        }


class TestRequestSeamRecordsUsage(unittest.TestCase):
    def test_equipment_request_records_into_global_recorder(self):
        cost.GLOBAL_USAGE.reset()
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "target.png"
            image.write_bytes(b"image")
            package = EquipmentPromptPackage(
                prompt_version="equipment_extraction_v4",
                system_prompt="system",
                user_template="user",
                examples=(),
            )
            plan = build_equipment_message_plan(package, image)
            asyncio.run(
                request_equipment_extraction(
                    message_plan=plan,
                    model="claude-haiku-4-5",
                    client=UsageReportingFakeClient(),
                )
            )
        snapshot = cost.GLOBAL_USAGE.snapshot()
        cost.GLOBAL_USAGE.reset()
        haiku = next(entry for entry in snapshot["models"] if entry["model"] == "claude-haiku-4-5")
        self.assertEqual(haiku["input_tokens"], 42)
        self.assertEqual(haiku["output_tokens"], 7)


if __name__ == "__main__":
    unittest.main()
