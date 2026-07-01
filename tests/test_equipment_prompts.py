import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
PROMPT_DIR = PROJECT_ROOT / "prompts" / "equipment_extraction"
sys.path.insert(0, str(PIPELINE_DIR))

import equipment_prompts  # noqa: E402
from equipment_prompts import (  # noqa: E402
    AssistantJsonMessage,
    ExampleImageResolutionError,
    PromptManifestError,
    PromptPackageFileError,
    SystemTextMessage,
    UnsupportedPromptVersionError,
    UserImageTextMessage,
    build_equipment_message_plan,
    load_equipment_prompt_package,
)
from models import EquipmentExtractionResponse  # noqa: E402


PROMPT_VERSION = "equipment_extraction_v4"
PROMPT_FILENAMES = [
    "v4_system.md",
    "v4_user_template.md",
    "v4_few_shot_examples.json",
]
EXPECTED_FILENAMES = [
    "AHU_02A.png",
    "VAV_2_05.png",
    "VAVRH_2_1.png",
]
EXPECTED_ROLE_ORDER = [
    "system",
    "user",
    "assistant",
    "user",
    "assistant",
    "user",
    "assistant",
    "user",
]


class TestEquipmentPromptPackageLoading(unittest.TestCase):
    def _write_example_files(self, root: Path, filenames=EXPECTED_FILENAMES) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            image_path = root / filename
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(b"not real image bytes")

    def _copy_prompt_package(
        self,
        root: Path,
        manifest_transform=None,
        omit_filename=None,
        manifest_text=None,
    ) -> Path:
        prompt_root = root / "prompts"
        prompt_root.mkdir(parents=True, exist_ok=True)
        for filename in PROMPT_FILENAMES:
            if filename == omit_filename:
                continue
            destination = prompt_root / filename
            if filename == "v4_few_shot_examples.json" and manifest_text is not None:
                destination.write_text(manifest_text, encoding="utf-8")
            else:
                shutil.copyfile(PROMPT_DIR / filename, destination)

        if manifest_transform is not None:
            manifest_path = prompt_root / "v4_few_shot_examples.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_transform(manifest)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        return prompt_root

    def _load_committed_package(self, example_dir: Path):
        return load_equipment_prompt_package(
            PROMPT_VERSION,
            PROMPT_DIR,
            example_dir,
        )

    def test_loads_current_prompt_package_and_preserves_manifest_order(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            example_dir = Path(tmp_dir) / "examples"
            self._write_example_files(example_dir)

            package = self._load_committed_package(example_dir)

        self.assertEqual(package.prompt_version, PROMPT_VERSION)
        self.assertTrue(package.system_prompt.strip())
        self.assertTrue(package.user_template.strip())
        self.assertEqual(len(package.examples), 3)
        self.assertEqual(
            [example.image_filename for example in package.examples],
            EXPECTED_FILENAMES,
        )
        for example in package.examples:
            self.assertIsInstance(example.expected_response, EquipmentExtractionResponse)
            self.assertEqual(example.resolved_image_path.parent, example_dir.resolve())

    def test_loads_v4_prompt_package_encodes_page_focused_policy(self):
        v4_examples = ["AHU_02A.png", "VAV_2_05.png", "VAVRH_2_1.png"]
        with tempfile.TemporaryDirectory() as tmp_dir:
            example_dir = Path(tmp_dir) / "examples"
            self._write_example_files(example_dir, v4_examples)

            package = load_equipment_prompt_package(
                "equipment_extraction_v4",
                PROMPT_DIR,
                example_dir,
            )

        self.assertEqual(package.prompt_version, "equipment_extraction_v4")
        self.assertEqual(len(package.examples), 3)
        self.assertEqual(
            [example.image_filename for example in package.examples],
            v4_examples,
        )
        system_text = package.system_prompt
        self.assertIn("navigation panel", system_text)
        self.assertIn("summary/monitoring table", system_text)
        self.assertIn("bare prefix", system_text)
        self.assertIn("cropped tile", system_text)

    def test_message_plan_uses_expected_order_and_provider_neutral_messages(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_dir = root / "examples"
            self._write_example_files(example_dir)
            target_image = root / "target.png"
            target_image.write_bytes(b"not a decodable image")
            package = self._load_committed_package(example_dir)

            plan = build_equipment_message_plan(package, target_image)

        self.assertEqual(len(plan.messages), 8)
        self.assertEqual([message.role for message in plan.messages], EXPECTED_ROLE_ORDER)
        self.assertIsInstance(plan.messages[0], SystemTextMessage)
        self.assertEqual(plan.messages[0].text, package.system_prompt)

        example_user_messages = plan.messages[1:7:2]
        self.assertTrue(all(isinstance(message, UserImageTextMessage) for message in example_user_messages))
        self.assertEqual(
            [message.image_path for message in example_user_messages],
            [example.resolved_image_path for example in package.examples],
        )

        assistant_messages = plan.messages[2:7:2]
        self.assertTrue(all(isinstance(message, AssistantJsonMessage) for message in assistant_messages))
        self.assertEqual(
            assistant_messages[0].json_text,
            '{"equipment":[{"raw_label":"AHU 02 A","canonical_name":"AHU_02A","equipment_type":"AHU","confidence":0.98}]}',
        )
        for message in assistant_messages:
            self.assertNotIn("```", message.json_text)
            self.assertEqual(
                EquipmentExtractionResponse(**json.loads(message.json_text)),
                message.expected_response,
            )

        final_message = plan.messages[-1]
        self.assertIsInstance(final_message, UserImageTextMessage)
        self.assertEqual(final_message.image_path, target_image.resolve())
        self.assertEqual(final_message.text, package.user_template)

    def test_message_plan_can_omit_few_shot_examples(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_dir = root / "examples"
            self._write_example_files(example_dir)
            target_image = root / "target.png"
            target_image.write_bytes(b"not a decodable image")
            package = self._load_committed_package(example_dir)

            plan = build_equipment_message_plan(package, target_image, include_examples=False)

        # System + target only -- no few-shot user/assistant demonstration turns.
        self.assertEqual(len(plan.messages), 2)
        self.assertEqual([message.role for message in plan.messages], ["system", "user"])
        self.assertIsInstance(plan.messages[0], SystemTextMessage)
        self.assertIsInstance(plan.messages[-1], UserImageTextMessage)
        self.assertEqual(plan.messages[-1].image_path, target_image.resolve())

    def test_placeholder_image_bytes_are_not_decoded_or_encoded(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_dir = root / "examples"
            self._write_example_files(example_dir)
            target_image = root / "target.png"
            target_image.write_bytes(b"this is not an image")

            package = self._load_committed_package(example_dir)
            plan = build_equipment_message_plan(package, target_image)

        for message in plan.messages:
            self.assertFalse(hasattr(message, "image_bytes"))
            self.assertFalse(hasattr(message, "image_url"))
            self.assertFalse(hasattr(message, "base64"))
        self.assertFalse(hasattr(equipment_prompts, "boto3"))
        self.assertFalse(hasattr(equipment_prompts, "requests"))
        self.assertFalse(hasattr(equipment_prompts, "Image"))
        self.assertFalse(hasattr(equipment_prompts, "base64"))

    def test_unsupported_prompt_version_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaisesRegex(
                UnsupportedPromptVersionError,
                "Unsupported equipment prompt version",
            ):
                load_equipment_prompt_package(
                    "equipment_extraction_v999",
                    PROMPT_DIR,
                    Path(tmp_dir),
                )

    def test_manifest_version_must_match_requested_version(self):
        def mutate(manifest):
            manifest["prompt_version"] = "equipment_extraction_v1"

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_root = self._copy_prompt_package(root, manifest_transform=mutate)
            example_dir = root / "examples"
            self._write_example_files(example_dir)

            with self.assertRaisesRegex(PromptManifestError, "does not match requested version"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, example_dir)

    def test_missing_system_prompt_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            prompt_root = self._copy_prompt_package(Path(tmp_dir), omit_filename="v4_system.md")

            with self.assertRaisesRegex(PromptPackageFileError, "missing system prompt"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, Path(tmp_dir))

    def test_missing_user_template_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            prompt_root = self._copy_prompt_package(
                Path(tmp_dir),
                omit_filename="v4_user_template.md",
            )

            with self.assertRaisesRegex(PromptPackageFileError, "missing user template"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, Path(tmp_dir))

    def test_missing_manifest_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            prompt_root = self._copy_prompt_package(
                Path(tmp_dir),
                omit_filename="v4_few_shot_examples.json",
            )

            with self.assertRaisesRegex(PromptPackageFileError, "missing few-shot manifest"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, Path(tmp_dir))

    def test_malformed_manifest_json_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            prompt_root = self._copy_prompt_package(
                Path(tmp_dir),
                manifest_text="{not-json",
            )

            with self.assertRaisesRegex(PromptManifestError, "malformed JSON manifest"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, Path(tmp_dir))

    def test_manifest_top_level_must_be_object(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            prompt_root = self._copy_prompt_package(Path(tmp_dir), manifest_text="[]")

            with self.assertRaisesRegex(PromptManifestError, "top-level value must be an object"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, Path(tmp_dir))

    def test_missing_example_image_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_root = self._copy_prompt_package(root)
            example_dir = root / "examples"
            example_dir.mkdir()

            with self.assertRaisesRegex(ExampleImageResolutionError, "image file does not exist"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, example_dir)

    def test_example_image_directory_instead_of_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_root = self._copy_prompt_package(root)
            example_dir = root / "examples"
            self._write_example_files(example_dir, EXPECTED_FILENAMES[1:])
            (example_dir / EXPECTED_FILENAMES[0]).mkdir(parents=True)

            with self.assertRaisesRegex(ExampleImageResolutionError, "image path is not a file"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, example_dir)

    def test_missing_target_image_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_dir = root / "examples"
            self._write_example_files(example_dir)
            package = self._load_committed_package(example_dir)

            with self.assertRaisesRegex(ExampleImageResolutionError, "Target image file does not exist"):
                build_equipment_message_plan(package, root / "missing.png")

    def test_target_directory_instead_of_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_dir = root / "examples"
            self._write_example_files(example_dir)
            target_dir = root / "target.png"
            target_dir.mkdir()
            package = self._load_committed_package(example_dir)

            with self.assertRaisesRegex(ExampleImageResolutionError, "Target image path is not a file"):
                build_equipment_message_plan(package, target_dir)

    def test_invalid_expected_response_fails_validation(self):
        def mutate(manifest):
            manifest["examples"][0]["expected_response"]["equipment"][0]["equipment_type"] = "GAVAV"

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_root = self._copy_prompt_package(root, manifest_transform=mutate)
            example_dir = root / "examples"
            self._write_example_files(example_dir)

            with self.assertRaisesRegex(PromptManifestError, "invalid expected_response"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, example_dir)

    def test_missing_required_example_field_fails(self):
        def mutate(manifest):
            del manifest["examples"][0]["user_text"]

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_root = self._copy_prompt_package(root, manifest_transform=mutate)
            example_dir = root / "examples"
            self._write_example_files(example_dir)

            with self.assertRaisesRegex(PromptManifestError, "missing required field user_text"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, example_dir)

    def test_blank_image_filename_fails(self):
        def mutate(manifest):
            manifest["examples"][0]["image_filename"] = "   "

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_root = self._copy_prompt_package(root, manifest_transform=mutate)
            example_dir = root / "examples"
            self._write_example_files(example_dir)

            with self.assertRaisesRegex(PromptManifestError, "image_filename.*nonblank"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, example_dir)

    def test_blank_user_text_fails(self):
        def mutate(manifest):
            manifest["examples"][0]["user_text"] = ""

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_root = self._copy_prompt_package(root, manifest_transform=mutate)
            example_dir = root / "examples"
            self._write_example_files(example_dir)

            with self.assertRaisesRegex(PromptManifestError, "user_text.*nonblank"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, example_dir)

    def test_duplicate_image_filename_fails(self):
        def mutate(manifest):
            manifest["examples"][1]["image_filename"] = manifest["examples"][0]["image_filename"]

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_root = self._copy_prompt_package(root, manifest_transform=mutate)
            example_dir = root / "examples"
            self._write_example_files(example_dir)

            with self.assertRaisesRegex(PromptManifestError, "duplicate example image_filename"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, example_dir)

    def test_empty_examples_list_fails(self):
        def mutate(manifest):
            manifest["examples"] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_root = self._copy_prompt_package(root, manifest_transform=mutate)

            with self.assertRaisesRegex(PromptManifestError, "examples list must not be empty"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, root / "examples")

    def test_absolute_example_image_path_fails(self):
        def mutate(manifest):
            manifest["examples"][0]["image_filename"] = str(Path.cwd() / "absolute.png")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_root = self._copy_prompt_package(root, manifest_transform=mutate)
            example_dir = root / "examples"
            self._write_example_files(example_dir)

            with self.assertRaisesRegex(ExampleImageResolutionError, "must be relative"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, example_dir)

    def test_parent_directory_traversal_fails(self):
        def mutate(manifest):
            manifest["examples"][0]["image_filename"] = "../outside.png"

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_root = self._copy_prompt_package(root, manifest_transform=mutate)
            example_dir = root / "examples"
            self._write_example_files(example_dir)

            with self.assertRaisesRegex(ExampleImageResolutionError, "image_filename is unsafe"):
                load_equipment_prompt_package(PROMPT_VERSION, prompt_root, example_dir)

    def test_resolved_path_escape_guard_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_dir = (root / "examples").resolve()
            outside_file = root / "outside.png"
            outside_file.write_bytes(b"outside")

            with self.assertRaisesRegex(ExampleImageResolutionError, "resolved outside"):
                equipment_prompts._ensure_path_under_root(
                    outside_file.resolve(),
                    example_dir,
                    "example image",
                )


if __name__ == "__main__":
    unittest.main()
