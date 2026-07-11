import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "populate_downloads.py"

spec = importlib.util.spec_from_file_location("populate_downloads", SCRIPT_PATH)
populate_downloads = importlib.util.module_from_spec(spec)
sys.modules["populate_downloads"] = populate_downloads
spec.loader.exec_module(populate_downloads)


class FakeBucket:
    """Injectable stand-in for the S3 listing/download seam (offline tests)."""

    def __init__(self, objects):
        self.objects = list(objects)
        self.downloaded = []

    def list_objects(self):
        return [{"key": key, "size": len(body)} for key, body in self.objects]

    def download(self, key, local_path):
        for object_key, body in self.objects:
            if object_key == key:
                Path(local_path).parent.mkdir(parents=True, exist_ok=True)
                Path(local_path).write_bytes(body)
                self.downloaded.append(key)
                return Path(local_path)
        raise AssertionError(f"unexpected download for key {key}")


class TestSyncFromS3(unittest.TestCase):
    def _sync(self, bucket, root, **kwargs):
        return populate_downloads.sync_from_s3(
            "Floor_2",
            dest_root=root,
            list_objects_fn=bucket.list_objects,
            download_fn=bucket.download,
            **kwargs,
        )

    def test_downloads_new_files_and_skips_unsupported(self):
        bucket = FakeBucket(
            [
                ("Team-4/Floor_2/ahu_02c.png", b"png-bytes"),
                ("Team-4/Floor_2/mech.pdf", b"pdf-bytes"),
                ("Team-4/Floor_2/notes.txt", b"not a source file"),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exit_code = self._sync(bucket, root)
            dest = root / "downloads" / "Floor_2"
            self.assertEqual(exit_code, 0)
            self.assertEqual(
                sorted(path.name for path in dest.iterdir()),
                ["ahu_02c.png", "mech.pdf"],
            )
        self.assertEqual(sorted(bucket.downloaded), ["Team-4/Floor_2/ahu_02c.png", "Team-4/Floor_2/mech.pdf"])

    def test_up_to_date_files_are_not_redownloaded(self):
        bucket = FakeBucket([("Team-4/Floor_2/ahu_02c.png", b"png-bytes")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "downloads" / "Floor_2"
            dest.mkdir(parents=True)
            (dest / "ahu_02c.png").write_bytes(b"png-bytes")
            exit_code = self._sync(bucket, root)
            self.assertEqual(exit_code, 0)
        self.assertEqual(bucket.downloaded, [])

    def test_size_change_triggers_redownload(self):
        bucket = FakeBucket([("Team-4/Floor_2/ahu_02c.png", b"png-bytes-longer")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "downloads" / "Floor_2"
            dest.mkdir(parents=True)
            (dest / "ahu_02c.png").write_bytes(b"old")
            self._sync(bucket, root)
            self.assertEqual((dest / "ahu_02c.png").read_bytes(), b"png-bytes-longer")
        self.assertEqual(bucket.downloaded, ["Team-4/Floor_2/ahu_02c.png"])

    def test_check_mode_reports_without_downloading_and_exits_1(self):
        bucket = FakeBucket([("Team-4/Floor_2/new_upload.png", b"png-bytes")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exit_code = self._sync(bucket, root, check_only=True)
            self.assertEqual(exit_code, 1)
            self.assertFalse((root / "downloads" / "Floor_2" / "new_upload.png").exists())
        self.assertEqual(bucket.downloaded, [])

    def test_check_mode_clean_exits_0(self):
        bucket = FakeBucket([("Team-4/Floor_2/ahu_02c.png", b"png-bytes")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "downloads" / "Floor_2"
            dest.mkdir(parents=True)
            (dest / "ahu_02c.png").write_bytes(b"png-bytes")
            self.assertEqual(self._sync(bucket, root, check_only=True), 0)

    def test_key_contains_filter(self):
        bucket = FakeBucket(
            [
                ("Team-4/Floor_2/ahu_02c.png", b"png-bytes"),
                ("Team-4/Floor_3/ahu_03a.png", b"png-bytes"),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._sync(bucket, root, key_contains="Floor_2")
            dest = root / "downloads" / "Floor_2"
            self.assertEqual([path.name for path in dest.iterdir()], ["ahu_02c.png"])


class TestLocalPopulate(unittest.TestCase):
    def test_local_copy_mode_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "vav_2_1.png").write_bytes(b"png-bytes")
            (source / "ignore.txt").write_text("nope")
            exit_code = populate_downloads.populate("Floor_2", source, dest_root=root)
            self.assertEqual(exit_code, 0)
            dest = root / "downloads" / "Floor_2"
            self.assertEqual([path.name for path in dest.iterdir()], ["vav_2_1.png"])

    def test_missing_source_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exit_code = populate_downloads.populate("Floor_2", root / "missing", dest_root=root)
            self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
