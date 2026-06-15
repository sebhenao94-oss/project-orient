import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
PROMPT_DIR = PROJECT_ROOT / "prompts" / "relationship_mapping"
sys.path.insert(0, str(PIPELINE_DIR))

from relationship_prompts import (  # noqa: E402
    EQUIPMENT_LIST_PLACEHOLDER,
    AssistantJsonMessage,
    PromptManifestError,
    PromptPackageFileError,
    RelationshipPromptPackage,
    SystemTextMessage,
    TargetImageResolutionError,
    UnsupportedPromptVersionError,
    UserImageTextMessage,
    UserTemplateError,
    UserTextMessage,
    build_relationship_message_plan,
    load_relationship_prompt_package,
)


PROMPT_VERSION = "relationship_mapping_v1"
PROMPT_FILENAMES = ["v1_system.md", "v1_user_template.md", "v1_few_shot_examples.json"]

DEFAULT_SYSTEM = "You are the relationship-mapping model. Return JSON only."
DEFAULT_TEMPLATE = (
    "Map relationships among:\n" + EQUIPMENT_LIST_PLACEHOLDER + "\nReturn JSON only."
)
DEFAULT_MANIFEST = {
    "prompt_version": PROMPT_VERSION,
    "examples": [
        {
            "user_text": "Demonstration only. Equipment: AHU_1-01, VAVRH_1-01.",
            "expected_response": {
                "relationships": [
                    {
                        "child": "VAVRH_1-01",
                        "parent": "AHU_1-01",
                        "ref_type": "airRef",
                        "confidence": 0.97,
                        "conflict": False,
                        "conflict_reason": "",
                    }
                ]
            },
        }
    ],
}


def _write_package(root, system=DEFAULT_SYSTEM, template=DEFAULT_TEMPLATE, manifest=DEFAULT_MANIFEST):
    root.mkdir(parents=True, exist_ok=True)
    if system is not None:
        (root / "v1_system.md").write_text(system, encoding="utf-8")
    if template is not None:
        (root / "v1_user_template.md").write_text(template, encoding="utf-8")
    if manifest is not None:
        (root / "v1_few_shot_examples.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
    return root


class TestRelationshipPromptPackageLoading(unittest.TestCase):
    def test_real_committed_package_loads(self):
        package = load_relationship_prompt_package(PROMPT_VERSION, PROMPT_DIR)

        self.assertIsInstance(package, RelationshipPromptPackage)
        self.assertTrue(package.system_prompt.strip())
        self.assertIn(EQUIPMENT_LIST_PLACEHOLDER, package.user_template)
        self.assertEqual(len(package.examples), 1)
        self.assertEqual(len(package.examples[0].expected_response.relationships), 5)

    def test_unsupported_version_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UnsupportedPromptVersionError):
                load_relationship_prompt_package("relationship_mapping_v999", Path(tmp))

    def test_missing_system_prompt_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_package(Path(tmp) / "p", system=None)
            with self.assertRaises(PromptPackageFileError):
                load_relationship_prompt_package(PROMPT_VERSION, root)

    def test_missing_user_template_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_package(Path(tmp) / "p", template=None)
            with self.assertRaises(PromptPackageFileError):
                load_relationship_prompt_package(PROMPT_VERSION, root)

    def test_missing_manifest_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_package(Path(tmp) / "p", manifest=None)
            with self.assertRaises(PromptPackageFileError):
                load_relationship_prompt_package(PROMPT_VERSION, root)

    def test_template_without_placeholder_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_package(Path(tmp) / "p", template="No placeholder here.")
            with self.assertRaises(UserTemplateError):
                load_relationship_prompt_package(PROMPT_VERSION, root)

    def test_blank_system_prompt_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_package(Path(tmp) / "p", system="   \n  ")
            with self.assertRaises(PromptPackageFileError):
                load_relationship_prompt_package(PROMPT_VERSION, root)

    def test_manifest_version_mismatch_fails(self):
        manifest = dict(DEFAULT_MANIFEST, prompt_version="relationship_mapping_v2")
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_package(Path(tmp) / "p", manifest=manifest)
            with self.assertRaises(PromptManifestError):
                load_relationship_prompt_package(PROMPT_VERSION, root)

    def test_manifest_examples_not_list_fails(self):
        manifest = dict(DEFAULT_MANIFEST, examples={})
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_package(Path(tmp) / "p", manifest=manifest)
            with self.assertRaises(PromptManifestError):
                load_relationship_prompt_package(PROMPT_VERSION, root)

    def test_manifest_empty_examples_fails(self):
        manifest = dict(DEFAULT_MANIFEST, examples=[])
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_package(Path(tmp) / "p", manifest=manifest)
            with self.assertRaises(PromptManifestError):
                load_relationship_prompt_package(PROMPT_VERSION, root)

    def test_manifest_example_missing_user_text_fails(self):
        manifest = {
            "prompt_version": PROMPT_VERSION,
            "examples": [{"expected_response": {"relationships": []}}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_package(Path(tmp) / "p", manifest=manifest)
            with self.assertRaises(PromptManifestError):
                load_relationship_prompt_package(PROMPT_VERSION, root)

    def test_manifest_example_missing_expected_response_fails(self):
        manifest = {
            "prompt_version": PROMPT_VERSION,
            "examples": [{"user_text": "x"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_package(Path(tmp) / "p", manifest=manifest)
            with self.assertRaises(PromptManifestError):
                load_relationship_prompt_package(PROMPT_VERSION, root)

    def test_manifest_example_invalid_expected_response_fails(self):
        manifest = {
            "prompt_version": PROMPT_VERSION,
            "examples": [
                {
                    "user_text": "x",
                    "expected_response": {
                        "relationships": [
                            {
                                "child": "VAVRH_1-01",
                                "parent": "AHU_1-01",
                                "ref_type": "waterRef",
                                "confidence": 0.9,
                            }
                        ]
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_package(Path(tmp) / "p", manifest=manifest)
            with self.assertRaises(PromptManifestError):
                load_relationship_prompt_package(PROMPT_VERSION, root)


class TestRelationshipMessagePlan(unittest.TestCase):
    def _package(self):
        return load_relationship_prompt_package(PROMPT_VERSION, PROMPT_DIR)

    def _target_image(self, tmp):
        image_path = Path(tmp) / "Floor_02_target.png"
        image_path.write_bytes(b"not real image bytes")
        return image_path

    def test_message_roles_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_relationship_message_plan(
                self._package(),
                "AHU_2_01\nVAVRH_2_01",
                self._target_image(tmp),
            )

        self.assertEqual(
            [message.role for message in plan.messages],
            ["system", "user", "assistant", "user"],
        )
        self.assertIsInstance(plan.messages[0], SystemTextMessage)
        self.assertIsInstance(plan.messages[1], UserTextMessage)
        self.assertIsInstance(plan.messages[2], AssistantJsonMessage)
        self.assertIsInstance(plan.messages[3], UserImageTextMessage)

    def test_assistant_json_is_compact_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_relationship_message_plan(
                self._package(), "AHU_2_01", self._target_image(tmp)
            )

        assistant = plan.messages[2]
        payload = json.loads(assistant.json_text)
        self.assertIn("relationships", payload)
        self.assertNotIn(" ", assistant.json_text.split('"relationships"')[0])

    def test_equipment_list_injected_and_placeholder_removed(self):
        equipment_list = "AHU_2_01\nVAVRH_2_01\nVAVRH_2_02"
        with tempfile.TemporaryDirectory() as tmp:
            image_path = self._target_image(tmp)
            plan = build_relationship_message_plan(
                self._package(), equipment_list, image_path
            )

        target = plan.messages[-1]
        self.assertIsInstance(target, UserImageTextMessage)
        self.assertEqual(target.image_path, image_path.resolve())
        self.assertIn("VAVRH_2_02", target.text)
        self.assertNotIn(EQUIPMENT_LIST_PLACEHOLDER, target.text)

    def test_missing_target_image_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.png"
            with self.assertRaises(TargetImageResolutionError):
                build_relationship_message_plan(self._package(), "AHU_2_01", missing)

    def test_blank_equipment_list_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UserTemplateError):
                build_relationship_message_plan(
                    self._package(), "   ", self._target_image(tmp)
                )


if __name__ == "__main__":
    unittest.main()
