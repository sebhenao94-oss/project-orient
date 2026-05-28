import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import ingestion  # noqa: E402


class TestIngestion(unittest.TestCase):
    def setUp(self):
        self.env = {
            "S3_BUCKET": "msa-summer-2026",
            "S3_INPUT_PREFIX": "Team-4/",
            "S3_OUTPUT_PREFIX": "Team-4/pipeline_outputs/",
        }

    def _mock_s3_client(self, pages):
        client = Mock()
        paginator = Mock()
        paginator.paginate.side_effect = pages
        client.get_paginator.return_value = paginator
        return client

    def test_list_source_s3_keys_lists_required_subfolders_and_excludes_outputs(self):
        pages = [
            [{"Contents": [{"Key": "Team-4/screenshots/ahu.png"}]}],
            [{"Contents": [{"Key": "Team-4/drawings/floor.pdf"}]}],
            [
                {
                    "Contents": [
                        {"Key": "Team-4/bms_exports/"},
                        {"Key": "Team-4/bms_exports/export.csv"},
                        {"Key": "Team-4/pipeline_outputs/processed/page_001.png"},
                    ]
                }
            ],
        ]
        client = self._mock_s3_client(pages)

        with patch.dict(ingestion.os.environ, self.env, clear=False):
            keys = ingestion.list_source_s3_keys(s3_client=client)

        self.assertEqual(
            keys,
            [
                "Team-4/screenshots/ahu.png",
                "Team-4/drawings/floor.pdf",
                "Team-4/bms_exports/export.csv",
            ],
        )
        client.get_paginator.assert_called_with("list_objects_v2")
        prefixes = [
            call.kwargs["Prefix"]
            for call in client.get_paginator.return_value.paginate.call_args_list
        ]
        self.assertEqual(
            prefixes,
            [
                "Team-4/screenshots/",
                "Team-4/drawings/",
                "Team-4/bms_exports/",
            ],
        )

    def test_ingest_source_files_returns_source_file_objects(self):
        pages = [
            [{"Contents": [{"Key": "Team-4/screenshots/good.png"}]}],
            [{"Contents": [{"Key": "Team-4/drawings/floor.pdf"}]}],
            [{"Contents": [{"Key": "Team-4/bms_exports/export.csv"}]}],
        ]
        client = self._mock_s3_client(pages)

        def fake_download(_bucket, _key, local_path):
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            Path(local_path).write_text("placeholder", encoding="utf-8")

        client.download_file.side_effect = fake_download

        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_page = Path(tmp_dir) / "processed" / "floor" / "page_001.png"

            with patch.dict(ingestion.os.environ, self.env, clear=False):
                with patch.object(
                    ingestion,
                    "check_image_quality",
                    return_value={
                        "width": 1200,
                        "height": 1200,
                        "is_quality_sufficient": True,
                        "reason": "Image meets minimum resolution threshold",
                    },
                ):
                    with patch.object(
                        ingestion,
                        "convert_pdf_to_images",
                        return_value=[pdf_page],
                    ):
                        records = ingestion.ingest_source_files(
                            download_dir=tmp_dir,
                            s3_client=client,
                        )

        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].s3_key, "Team-4/screenshots/good.png")
        self.assertEqual(records[0].file_type, "image")
        self.assertTrue(records[0].quality_flag)
        self.assertEqual(records[0].processed_status, "processed")

        self.assertEqual(records[1].file_type, "pdf")
        self.assertTrue(records[1].quality_flag)
        self.assertEqual(records[1].processed_status, "processed")

        self.assertEqual(records[2].file_type, "unsupported")
        self.assertIsNone(records[2].quality_flag)
        self.assertEqual(records[2].processed_status, "skipped")


if __name__ == "__main__":
    unittest.main()
