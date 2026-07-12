import asyncio
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import extraction  # noqa: E402
import cost  # noqa: E402
from checkpoint import checkpoint_key  # noqa: E402
from equipment_prompts import EquipmentPromptPackage  # noqa: E402
from models import AIReadyImageRecord  # noqa: E402


SHA = "d" * 64


def image_record(root: Path, filename: str, *, width: int, height: int) -> AIReadyImageRecord:
    path = root / filename
    Image.new("RGB", (32, 32), "white").save(path)
    return AIReadyImageRecord(
        source_filename=filename,
        source_relative_path=filename,
        source_file_type="image",
        source_sha256=SHA,
        source_local_path=str(path),
        prepared_image_local_path=str(path),
        prepared_image_filename=filename,
        image_format="PNG",
        image_mime_type="image/png",
        width=width,
        height=height,
        pixel_count=width * height,
        quality_flag=True,
        quality_status="passed",
        quality_reason="ok",
        warnings=[],
        extraction_eligible=True,
        preparation_status="prepared",
    )


def prompt_package() -> EquipmentPromptPackage:
    return EquipmentPromptPackage(
        prompt_version="equipment_extraction_v4",
        system_prompt="system",
        user_template="extract",
        examples=(),
    )


class TestExtractionRouting(unittest.TestCase):
    def test_routes_large_drawing_to_capable_model_and_screenshot_to_flat_model(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            drawing = image_record(root, "drawing.png", width=13000, height=9000)
            screenshot = image_record(root, "screen.png", width=1200, height=800)

            routes = extraction.route_records(
                [drawing, screenshot],
                model="cheap-model",
                drawing_model="capable-model",
            )

        self.assertEqual(
            [(route.route, route.model) for route in routes],
            [("drawing", "capable-model"), ("flat", "cheap-model")],
        )
        self.assertNotEqual(
            checkpoint_key(drawing, "equipment_extraction_v4", routes[0].model),
            checkpoint_key(screenshot, "equipment_extraction_v4", routes[1].model),
        )

    def test_flat_mode_uses_one_model_for_every_record(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            records = [
                image_record(root, "drawing.png", width=13000, height=9000),
                image_record(root, "screen.png", width=1200, height=800),
            ]
            routes = extraction.route_records(
                records,
                model="one-model",
                drawing_model="unused-model",
                flat=True,
            )

        self.assertEqual(
            [(route.route, route.model) for route in routes],
            [("flat", "one-model"), ("flat", "one-model")],
        )

    def test_checkpoint_lookup_uses_each_route_effective_model(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            records = [
                image_record(root, "drawing.png", width=13000, height=9000),
                image_record(root, "screen.png", width=1200, height=800),
            ]
            routes = extraction.route_records(
                records,
                model="cheap-model",
                drawing_model="capable-model",
            )

            class RecordingCheckpoint:
                def __init__(self):
                    self.keys = []

                def succeeded_result(self, key):
                    self.keys.append(key)
                    return None

            checkpoint = RecordingCheckpoint()
            reused, pending = extraction.partition_checkpointed_routes(
                routes,
                checkpoint=checkpoint,
                prompt_version="equipment_extraction_v4",
                prompt_fingerprint="prompt-content-hash",
            )

        self.assertEqual(reused, {})
        self.assertEqual([index for index, _ in pending], [0, 1])
        self.assertEqual(
            checkpoint.keys,
            [
                checkpoint_key(
                    records[0],
                    "equipment_extraction_v4",
                    "capable-model",
                    prompt_fingerprint="prompt-content-hash",
                    extraction_mode=extraction._checkpoint_extraction_mode(routes[0]),
                ),
                checkpoint_key(
                    records[1],
                    "equipment_extraction_v4",
                    "cheap-model",
                    prompt_fingerprint="prompt-content-hash",
                    extraction_mode="flat",
                ),
            ],
        )

    def test_routed_dispatch_selects_tiling_and_flat_extractors_in_input_order(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            records = [
                image_record(root, "screen.png", width=1200, height=800),
                image_record(root, "drawing.png", width=13000, height=9000),
            ]
            routes = extraction.route_records(
                records,
                model="cheap-model",
                drawing_model="capable-model",
            )
            completed = []

            async def flat_extract(**kwargs):
                return ("flat", kwargs["model"], kwargs["image_record"].source_filename)

            async def drawing_extract(**kwargs):
                return ("drawing", kwargs["model"], kwargs["image_record"].source_filename)

            with mock.patch.object(
                extraction, "extract_equipment_from_image", side_effect=flat_extract
            ) as flat_mock, mock.patch.object(
                extraction, "extract_equipment_from_drawing", side_effect=drawing_extract
            ) as drawing_mock:
                results = asyncio.run(
                    extraction.extract_equipment_routed_batch(
                        routes=routes,
                        prompt_package=prompt_package(),
                        max_concurrency=2,
                        on_result=lambda route, result: completed.append(
                            (route.record.source_filename, result)
                        ),
                    )
                )

        self.assertEqual(
            results,
            [
                ("flat", "cheap-model", "screen.png"),
                ("drawing", "capable-model", "drawing.png"),
            ],
        )
        self.assertEqual(flat_mock.call_count, 1)
        self.assertEqual(drawing_mock.call_count, 1)
        self.assertCountEqual([name for name, _ in completed], ["screen.png", "drawing.png"])

    def test_extract_help_documents_routing_and_hybrid_batch_behavior(self):
        completed = subprocess.run(
            [sys.executable, "-m", "pipeline.extraction", "extract", "--help"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--drawing-model", completed.stdout)
        self.assertIn("--flat", completed.stdout)
        self.assertIn("Routed drawings still run realtime", completed.stdout)

    def test_batch_cli_splits_screenshots_and_realtime_drawings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            screenshot = image_record(root, "screen.png", width=1200, height=800)
            drawing = image_record(root, "drawing.png", width=13000, height=9000)
            package = prompt_package()
            screenshot_result = extraction._skipped_result(
                screenshot, package, "cheap-model", extraction._utc_now()
            )
            drawing_result = extraction._skipped_result(
                drawing, package, "capable-model", extraction._utc_now()
            )

            async def routed_batch(**kwargs):
                self.assertEqual([route.record for route in kwargs["routes"]], [drawing])
                self.assertEqual([route.model for route in kwargs["routes"]], ["capable-model"])
                return [drawing_result]

            with mock.patch.object(
                extraction, "_prepared_image_records_from_dir", return_value=[screenshot, drawing]
            ), mock.patch.object(
                extraction, "load_equipment_prompt_package", return_value=package
            ), mock.patch.object(
                extraction,
                "extract_equipment_batch_via_batch_api",
                return_value=[screenshot_result],
            ) as batch_mock, mock.patch.object(
                extraction, "extract_equipment_routed_batch", side_effect=routed_batch
            ) as routed_mock, mock.patch.object(
                extraction, "write_extraction_run_jsonl"
            ), mock.patch.object(
                extraction, "write_drawing_equipment_snapshot"
            ), mock.patch.object(
                cost, "write_run_metrics"
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    return_code = extraction.main(
                        [
                            "extract",
                            "--input-dir",
                            str(root),
                            "--example-image-dir",
                            str(root),
                            "--model",
                            "cheap-model",
                            "--drawing-model",
                            "capable-model",
                            "--run-live",
                            "--batch",
                            "--no-checkpoint",
                            "--allow-incomplete",
                            "--overwrite",
                        ]
                    )

        self.assertEqual(return_code, 0)
        self.assertEqual(
            batch_mock.call_args.kwargs["image_records"],
            [screenshot],
        )
        self.assertEqual(batch_mock.call_args.kwargs["model"], "cheap-model")
        self.assertEqual(routed_mock.call_count, 1)
        self.assertIn("Batch mode split", stdout.getvalue())

    def test_cli_writes_artifacts_and_metrics_then_fails_incomplete_run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            record = image_record(root, "screen.png", width=1200, height=800)
            package = prompt_package()
            skipped = extraction._skipped_result(
                record, package, "cheap-model", extraction._utc_now()
            )
            metrics_path = root / "out" / "metrics.json"

            async def routed_batch(**kwargs):
                return [skipped]

            with mock.patch.object(
                extraction, "_prepared_image_records_from_dir", return_value=[record]
            ), mock.patch.object(
                extraction, "load_equipment_prompt_package", return_value=package
            ), mock.patch.object(
                extraction, "extract_equipment_routed_batch", side_effect=routed_batch
            ), mock.patch.object(
                extraction, "write_extraction_run_jsonl"
            ) as write_runs, mock.patch.object(
                extraction, "write_drawing_equipment_snapshot"
            ) as write_snapshot:
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    return_code = extraction.main(
                        [
                            "extract",
                            "--input-dir",
                            str(root),
                            "--example-image-dir",
                            str(root),
                            "--model",
                            "cheap-model",
                            "--run-live",
                            "--no-checkpoint",
                            "--output-dir",
                            str(root / "out"),
                            "--snapshot-path",
                            str(root / "out" / "drawing.csv"),
                            "--metrics-path",
                            str(metrics_path),
                            "--overwrite",
                        ]
                    )

            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

        self.assertEqual(return_code, 1)
        write_runs.assert_called_once()
        write_snapshot.assert_called_once()
        self.assertEqual(metrics["counts"]["images_total"], 1)
        self.assertEqual(metrics["counts"]["images_succeeded"], 0)
        self.assertEqual(metrics["counts"]["images_incomplete"], 1)
        self.assertEqual(metrics["counts"]["image_status"], {"skipped": 1})
        self.assertIn("Incomplete extraction run: 1 of 1 source image", stdout.getvalue())
        self.assertIn("Artifacts and metrics were written", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
