import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import extraction  # noqa: E402
import ingestion  # noqa: E402
import run as pipeline_run  # noqa: E402
from equipment_prompts import EquipmentPromptPackage  # noqa: E402
from models import AIReadyImageRecord, IngestionPreparationResult  # noqa: E402


SOURCE_SHA256 = "b" * 64


def pdf_page_record(root: Path, page_number: int = 2) -> AIReadyImageRecord:
    prepared_path = root / "processed" / "mechanical_plan_page_002.png"
    return AIReadyImageRecord(
        source_filename="mechanical_plan.pdf",
        source_relative_path="drawings/mechanical_plan.pdf",
        source_file_type="pdf",
        source_sha256=SOURCE_SHA256,
        source_local_path=str(root / "sources" / "mechanical_plan.pdf"),
        raw_s3_key="Team-4/raw/pdfs/drawings/mechanical_plan.pdf",
        prepared_image_local_path=str(prepared_path),
        prepared_image_s3_key=None,
        prepared_image_filename=prepared_path.name,
        image_format="PNG",
        image_mime_type="image/png",
        source_page_number=page_number,
        width=12600,
        height=9000,
        pixel_count=113400000,
        quality_flag=False,
        quality_status="failed",
        quality_reason="offline fixture is intentionally ineligible",
        warnings=["offline manifest-contract fixture"],
        extraction_eligible=False,
        preparation_status="quality_failed",
    )


def prompt_package() -> EquipmentPromptPackage:
    return EquipmentPromptPackage(
        prompt_version="equipment_extraction_v4",
        system_prompt="system",
        user_template="extract",
        examples=(),
    )


class TestAIReadyImageManifest(unittest.TestCase):
    def test_pdf_record_round_trip_is_deterministic_and_overwrite_safe(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            record = pdf_page_record(root)
            first_path = root / "first.jsonl"
            second_path = root / "second.jsonl"

            ingestion.write_ai_ready_image_manifest([record], first_path)
            ingestion.write_ai_ready_image_manifest([record], second_path)
            original_bytes = first_path.read_bytes()
            loaded = ingestion.load_ai_ready_image_manifest(first_path)

            self.assertEqual(original_bytes, second_path.read_bytes())
            self.assertEqual(loaded, [record])
            self.assertEqual(loaded[0].source_filename, "mechanical_plan.pdf")
            self.assertEqual(loaded[0].source_relative_path, "drawings/mechanical_plan.pdf")
            self.assertEqual(loaded[0].source_sha256, SOURCE_SHA256)
            self.assertEqual(loaded[0].source_page_number, 2)
            self.assertEqual(
                first_path.read_text(encoding="utf-8"),
                json.dumps(
                    record.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
            )

            replacement = record.model_copy(update={"source_page_number": 3})
            with self.assertRaises(ingestion.AIReadyImageManifestError):
                ingestion.write_ai_ready_image_manifest([replacement], first_path)
            self.assertEqual(first_path.read_bytes(), original_bytes)

            ingestion.write_ai_ready_image_manifest(
                [replacement],
                first_path,
                overwrite=True,
            )
            self.assertEqual(
                ingestion.load_ai_ready_image_manifest(first_path)[0].source_page_number,
                3,
            )

    def test_loader_reports_pydantic_validation_with_line_number(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = pdf_page_record(root).model_dump(mode="json")
            payload["source_page_number"] = 0
            manifest_path = root / "invalid.jsonl"
            manifest_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ingestion.AIReadyImageManifestError,
                "line 1",
            ):
                ingestion.load_ai_ready_image_manifest(manifest_path)


class TestStageManifestIntegration(unittest.TestCase):
    def test_stage1_defaults_manifest_below_work_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            work_dir = root / "work"
            record = pdf_page_record(root)
            result = IngestionPreparationResult(prepared_image_records=[record])

            with mock.patch.object(
                pipeline_run,
                "prepare_sources_for_extraction",
                return_value=result,
            ), mock.patch("builtins.print"):
                exit_code = pipeline_run.main(
                    [
                        str(root / "sources"),
                        "--work-dir",
                        str(work_dir),
                        "--raw-prefix",
                        "Team-4/raw/",
                    ]
                )

            manifest_path = work_dir / pipeline_run.DEFAULT_PREPARED_RECORDS_MANIFEST_NAME
            loaded = ingestion.load_ai_ready_image_manifest(manifest_path)

        self.assertEqual(exit_code, 0)
        self.assertEqual(loaded, [record])

    def test_stage1_manifest_conflict_is_rejected_before_ingestion(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest_path = root / "existing.jsonl"
            manifest_path.write_text("existing\n", encoding="utf-8")

            with mock.patch.object(
                pipeline_run,
                "prepare_sources_for_extraction",
            ) as prepare, mock.patch("builtins.print"):
                exit_code = pipeline_run.main(
                    [
                        str(root / "sources"),
                        "--prepared-records-manifest",
                        str(manifest_path),
                        "--raw-prefix",
                        "Team-4/raw/",
                    ]
                )

        self.assertEqual(exit_code, 1)
        prepare.assert_not_called()

    def test_stage2_consumes_manifest_without_rescanning_or_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            record = pdf_page_record(root)
            manifest_path = root / "prepared_image_records.jsonl"
            raw_runs_path = root / "out" / "runs.jsonl"
            snapshot_path = root / "out" / "drawing.csv"
            metrics_path = root / "out" / "metrics.json"
            ingestion.write_ai_ready_image_manifest([record], manifest_path)

            with mock.patch.object(
                extraction,
                "_prepared_image_records_from_dir",
                side_effect=AssertionError("manifest input must not rescan images"),
            ) as scan_images, mock.patch.object(
                extraction,
                "load_equipment_prompt_package",
                return_value=prompt_package(),
            ), mock.patch.object(
                extraction,
                "request_equipment_extraction",
                side_effect=AssertionError("ineligible fixture must not call a model"),
            ) as request_model, mock.patch("builtins.print"):
                exit_code = extraction.main(
                    [
                        "extract",
                        "--prepared-records-manifest",
                        str(manifest_path),
                        "--example-image-dir",
                        str(root),
                        "--no-type-context",
                        "--model",
                        "offline-flat-model",
                        "--drawing-model",
                        "offline-drawing-model",
                        "--run-live",
                        "--no-checkpoint",
                        "--output-dir",
                        str(root / "out"),
                        "--raw-runs-path",
                        str(raw_runs_path),
                        "--snapshot-path",
                        str(snapshot_path),
                        "--metrics-path",
                        str(metrics_path),
                    ]
                )

            run_payload = json.loads(raw_runs_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        scan_images.assert_not_called()
        request_model.assert_not_called()
        self.assertEqual(run_payload["source_filename"], "mechanical_plan.pdf")
        self.assertEqual(run_payload["source_relative_path"], "drawings/mechanical_plan.pdf")
        self.assertEqual(run_payload["source_sha256"], SOURCE_SHA256)
        self.assertEqual(run_payload["source_file_type"], "pdf")
        self.assertEqual(run_payload["pdf_page_number"], 2)
        self.assertEqual(run_payload["model_id"], "offline-drawing-model")


if __name__ == "__main__":
    unittest.main()
