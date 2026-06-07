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


class TestLocalSourceManifest(unittest.TestCase):
    def _write_file(self, root: Path, relative_path: str, content: bytes) -> Path:
        file_path = root / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        return file_path

    def test_recursive_discovery_supported_types_and_classification(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_file(root, "screens/A.PNG", b"png")
            self._write_file(root, "screens/B.JPG", b"jpg")
            self._write_file(root, "screens/C.JpEg", b"jpeg")
            self._write_file(root, "drawings/D.PDF", b"pdf")
            self._write_file(root, "cad/E.DwG", b"dwg")

            records = ingestion.build_local_source_manifest(root)

        self.assertEqual(len(records), 5)
        self.assertEqual(
            {record.source_filename: record.file_type for record in records},
            {
                "A.PNG": "image",
                "B.JPG": "image",
                "C.JpEg": "image",
                "D.PDF": "pdf",
                "E.DwG": "dwg",
            },
        )
        self.assertTrue(all(record.ingestion_status == "discovered" for record in records))

    def test_unsupported_file_is_included_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_file(root, "notes/readme.txt", b"hello")

            records = ingestion.build_local_source_manifest(root)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].file_type, "unsupported")
        self.assertEqual(records[0].ingestion_status, "skipped")

    def test_deterministic_ordering_by_relative_path_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_file(root, "z/file.pdf", b"z")
            self._write_file(root, "A/file.png", b"a")
            self._write_file(root, "m/second.dwg", b"second")

            records = ingestion.build_local_source_manifest(root)

        self.assertEqual(
            [record.relative_path for record in records],
            ["A/file.png", "m/second.dwg", "z/file.pdf"],
        )

    def test_file_size_and_sha256_are_recorded(self):
        content = b"checksum me"
        expected_sha256 = "820eb62b7660a216f711bd0df37ac8a176b662a159959870edc200b857262daf"
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_file(root, "image.png", content)

            records = ingestion.build_local_source_manifest(root)

        self.assertEqual(records[0].file_size_bytes, len(content))
        self.assertEqual(records[0].sha256, expected_sha256)

    def test_empty_directory_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            records = ingestion.build_local_source_manifest(tmp_dir)

        self.assertEqual(records, [])

    def test_missing_input_directory_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_path = Path(tmp_dir) / "missing"

            with self.assertRaisesRegex(FileNotFoundError, "Local input path does not exist"):
                ingestion.build_local_source_manifest(missing_path)

    def test_file_path_instead_of_directory_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            file_path = self._write_file(root, "single.png", b"content")

            with self.assertRaisesRegex(NotADirectoryError, "Local input path is not a directory"):
                ingestion.build_local_source_manifest(file_path)

    def test_source_files_remain_unchanged(self):
        content = b"original bytes"
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_file = self._write_file(root, "nested/source.pdf", content)
            before = source_file.read_bytes()

            ingestion.build_local_source_manifest(root)

            self.assertEqual(source_file.read_bytes(), before)

    def test_excluded_operations_are_not_called(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_file(root, "graphic.png", b"graphic")
            self._write_file(root, "drawing.pdf", b"pdf")

            with patch.object(ingestion, "convert_pdf_to_images") as convert_pdf:
                with patch.object(ingestion, "check_image_quality") as check_quality:
                    with patch.object(ingestion, "list_source_s3_keys") as list_s3:
                        with patch.object(ingestion.boto3, "client") as boto_client:
                            records = ingestion.build_local_source_manifest(root)

            self.assertEqual(len(records), 2)
            convert_pdf.assert_not_called()
            check_quality.assert_not_called()
            list_s3.assert_not_called()
            boto_client.assert_not_called()
if __name__ == "__main__":
    unittest.main()
