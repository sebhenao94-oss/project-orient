import sys
import warnings
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image


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

class _FakeImage:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.size = (width, height)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


class TestImageQuality(unittest.TestCase):
    def _write_image(self, root: Path, filename: str, size) -> Path:
        image_path = root / filename
        Image.new("RGB", size, color="white").save(image_path)
        return image_path

    def test_normal_landscape_image_passes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = self._write_image(Path(tmp_dir), "landscape.png", (1200, 800))

            result = ingestion.check_image_quality(image_path)

        self.assertTrue(result["quality_flag"])
        self.assertTrue(result["is_quality_sufficient"])
        self.assertEqual(result["pixel_count"], 960000)
        self.assertEqual(result["warnings"], [])

    def test_normal_portrait_image_passes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = self._write_image(Path(tmp_dir), "portrait.png", (800, 1200))

            result = ingestion.check_image_quality(image_path)

        self.assertTrue(result["quality_flag"])
        self.assertEqual(result["warnings"], [])

    def test_project_like_wide_image_passes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = self._write_image(Path(tmp_dir), "ahu.png", (2174, 877))

            result = ingestion.check_image_quality(image_path)

        self.assertTrue(result["quality_flag"])
        self.assertEqual(result["width"], 2174)
        self.assertEqual(result["height"], 877)

    def test_project_like_vavrh_image_passes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = self._write_image(Path(tmp_dir), "vavrh.png", (1379, 976))

            result = ingestion.check_image_quality(image_path)

        self.assertTrue(result["quality_flag"])
        self.assertEqual(result["width"], 1379)
        self.assertEqual(result["height"], 976)

    def test_long_side_below_minimum_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = self._write_image(Path(tmp_dir), "small.png", (999, 800))

            result = ingestion.check_image_quality(image_path)

        self.assertFalse(result["quality_flag"])
        self.assertIn("long side must be at least 1000px", result["reason"])

    def test_short_side_below_minimum_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = self._write_image(Path(tmp_dir), "short.png", (1200, 749))

            result = ingestion.check_image_quality(image_path)

        self.assertFalse(result["quality_flag"])
        self.assertIn("short side must be at least 750px", result["reason"])

    def test_exact_minimum_dimensions_pass(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = self._write_image(Path(tmp_dir), "exact.png", (1000, 750))

            result = ingestion.check_image_quality(image_path)

        self.assertTrue(result["quality_flag"])
        self.assertEqual(result["pixel_count"], 750000)

    def test_oversized_image_warns_but_does_not_fail(self):
        with patch.object(ingestion.Image, "open", return_value=_FakeImage(10001, 10000)):
            result = ingestion.check_image_quality("oversized.png")

        self.assertTrue(result["quality_flag"])
        self.assertGreater(result["pixel_count"], ingestion.MAX_RECOMMENDED_PIXEL_COUNT)
        self.assertIn("unusually large", result["reason"])
        self.assertTrue(result["warnings"])

    def test_corrupt_image_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "corrupt.png"
            image_path.write_bytes(b"not an image")

            result = ingestion.check_image_quality(image_path)

        self.assertFalse(result["quality_flag"])
        self.assertIsNone(result["width"])
        self.assertIsNone(result["height"])
        self.assertIn("Unable to read image file", result["reason"])

    def test_decompression_bomb_warning_is_captured(self):
        def fake_open(_file_path):
            warnings.warn(
                "large image warning",
                ingestion.Image.DecompressionBombWarning,
            )
            return _FakeImage(12600, 9000)

        with warnings.catch_warnings(record=True) as leaked_warnings:
            warnings.simplefilter("always")
            with patch.object(ingestion.Image, "open", side_effect=fake_open):
                result = ingestion.check_image_quality("large.png")

        self.assertTrue(result["quality_flag"])
        self.assertIn("large image warning", result["warnings"])
        self.assertEqual(leaked_warnings, [])
        self.assertIn("unusually large", result["reason"])

    def test_existing_callers_remain_compatible(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = self._write_image(Path(tmp_dir), "compatible.png", (1200, 800))

            result = ingestion.check_image_quality(image_path)

        self.assertIn("width", result)
        self.assertIn("height", result)
        self.assertIn("is_quality_sufficient", result)
        self.assertIn("reason", result)
        self.assertEqual(result["is_quality_sufficient"], result["quality_flag"])

    def test_source_image_bytes_remain_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = self._write_image(Path(tmp_dir), "unchanged.png", (1200, 800))
            before = image_path.read_bytes()

            ingestion.check_image_quality(image_path)

            self.assertEqual(image_path.read_bytes(), before)

    def test_no_excluded_operations_are_called(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = self._write_image(Path(tmp_dir), "local.png", (1200, 800))

            with patch.object(ingestion, "convert_pdf_to_images") as convert_pdf:
                with patch.object(ingestion, "list_source_s3_keys") as list_s3:
                    with patch.object(ingestion.boto3, "client") as boto_client:
                        result = ingestion.check_image_quality(image_path)

        self.assertTrue(result["quality_flag"])
        convert_pdf.assert_not_called()
        list_s3.assert_not_called()
        boto_client.assert_not_called()


class _FakePdfPage:
    def __init__(self, saved_paths=None):
        self.saved_paths = saved_paths if saved_paths is not None else []

    def save(self, image_path, image_format):
        self.saved_paths.append((Path(image_path), image_format))
        Path(image_path).write_bytes(b"png page")


class _FailingPdfPage:
    def save(self, _image_path, _image_format):
        raise OSError("save failed")


class TestPdfConversion(unittest.TestCase):
    def _write_pdf(self, root: Path, filename="sample.pdf", content=b"pdf bytes") -> Path:
        pdf_path = root / filename
        pdf_path.write_bytes(content)
        return pdf_path

    def test_missing_source_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            missing_pdf = root / "missing.pdf"

            with self.assertRaisesRegex(FileNotFoundError, "PDF source path does not exist"):
                ingestion.convert_pdf_to_images(missing_pdf, root / "out")

    def test_directory_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            directory_path = root / "folder.pdf"
            directory_path.mkdir()

            with self.assertRaisesRegex(IsADirectoryError, "PDF source path is not a file"):
                ingestion.convert_pdf_to_images(directory_path, root / "out")

    def test_non_pdf_extension_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            text_file = root / "not_pdf.txt"
            text_file.write_bytes(b"not pdf")

            with self.assertRaisesRegex(ValueError, "must have a .pdf extension"):
                ingestion.convert_pdf_to_images(text_file, root / "out")

    def test_dpi_below_300_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = self._write_pdf(root)

            with self.assertRaisesRegex(ValueError, "DPI must be at least 300"):
                ingestion.convert_pdf_to_images(pdf_path, root / "out", dpi=299)

    def test_default_dpi_is_300(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = self._write_pdf(root)

            with patch.object(
                ingestion,
                "convert_from_path",
                return_value=[_FakePdfPage()],
            ) as convert_from_path:
                ingestion.convert_pdf_to_images(pdf_path, root / "out")

            convert_from_path.assert_called_once()
            self.assertEqual(convert_from_path.call_args.kwargs["dpi"], 300)

    def test_custom_poppler_path_is_passed_to_convert_from_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = self._write_pdf(root)
            poppler_path = r"C:\poppler\bin"

            with patch.object(
                ingestion,
                "convert_from_path",
                return_value=[_FakePdfPage()],
            ) as convert_from_path:
                ingestion.convert_pdf_to_images(
                    pdf_path,
                    root / "out",
                    poppler_path=poppler_path,
                )

            self.assertEqual(
                convert_from_path.call_args.kwargs["poppler_path"],
                poppler_path,
            )

    def test_multipage_conversion_uses_deterministic_ordered_filenames(self):
        saved_paths = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = self._write_pdf(root, filename="multi.PDF")
            output_dir = root / "out"

            with patch.object(
                ingestion,
                "convert_from_path",
                return_value=[_FakePdfPage(saved_paths), _FakePdfPage(saved_paths)],
            ):
                generated_paths = ingestion.convert_pdf_to_images(pdf_path, output_dir)

            expected_paths = [
                output_dir / "multi" / "page_001.png",
                output_dir / "multi" / "page_002.png",
            ]
            self.assertEqual(generated_paths, expected_paths)
            self.assertEqual([path for path, _format in saved_paths], expected_paths)
            self.assertEqual([image_format for _path, image_format in saved_paths], ["PNG", "PNG"])

    def test_output_directory_is_created(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = self._write_pdf(root)
            output_dir = root / "new" / "output"

            with patch.object(ingestion, "convert_from_path", return_value=[_FakePdfPage()]):
                ingestion.convert_pdf_to_images(pdf_path, output_dir)

            self.assertTrue((output_dir / "sample").is_dir())

    def test_missing_poppler_exception_becomes_clear_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = self._write_pdf(root)

            with patch.object(
                ingestion,
                "convert_from_path",
                side_effect=ingestion.PDFInfoNotInstalledError("missing poppler"),
            ):
                with self.assertRaisesRegex(RuntimeError, "Poppler is required"):
                    ingestion.convert_pdf_to_images(pdf_path, root / "out")

    def test_page_count_exception_becomes_clear_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = self._write_pdf(root)

            with patch.object(
                ingestion,
                "convert_from_path",
                side_effect=ingestion.PDFPageCountError("bad page count"),
            ):
                with self.assertRaisesRegex(RuntimeError, "Unable to read page count"):
                    ingestion.convert_pdf_to_images(pdf_path, root / "out")

    def test_pdf_syntax_exception_becomes_clear_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = self._write_pdf(root)

            with patch.object(
                ingestion,
                "convert_from_path",
                side_effect=ingestion.PDFSyntaxError("bad syntax"),
            ):
                with self.assertRaisesRegex(RuntimeError, "invalid or unreadable"):
                    ingestion.convert_pdf_to_images(pdf_path, root / "out")

    def test_unexpected_page_save_failure_becomes_clear_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = self._write_pdf(root)

            with patch.object(ingestion, "convert_from_path", return_value=[_FailingPdfPage()]):
                with self.assertRaisesRegex(RuntimeError, "Unable to save converted PDF page 1"):
                    ingestion.convert_pdf_to_images(pdf_path, root / "out")

    def test_source_pdf_bytes_remain_unchanged(self):
        source_bytes = b"source pdf bytes"
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = self._write_pdf(root, content=source_bytes)

            with patch.object(ingestion, "convert_from_path", return_value=[_FakePdfPage()]):
                ingestion.convert_pdf_to_images(pdf_path, root / "out")

            self.assertEqual(pdf_path.read_bytes(), source_bytes)

    def test_no_excluded_services_or_image_quality_are_called(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf_path = self._write_pdf(root)

            with patch.object(ingestion, "convert_from_path", return_value=[_FakePdfPage()]):
                with patch.object(ingestion, "check_image_quality") as check_quality:
                    with patch.object(ingestion, "list_source_s3_keys") as list_s3:
                        with patch.object(ingestion.boto3, "client") as boto_client:
                            ingestion.convert_pdf_to_images(pdf_path, root / "out")

            check_quality.assert_not_called()
            list_s3.assert_not_called()
            boto_client.assert_not_called()

if __name__ == "__main__":
    unittest.main()
