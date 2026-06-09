import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
PROMPT_DIR = PROJECT_ROOT / "prompts" / "equipment_extraction"
sys.path.insert(0, str(PIPELINE_DIR))

from models import EquipmentExtractionResponse  # noqa: E402


EXPECTED_FILENAMES = [
    "AHU_02A.png",
    "VAV_2_05.png",
    "VAVRH_2_1.png",
    "fptu_2_01.png",
    "fcu_02_1.png",
]

EXPECTED_LABELS = {
    "AHU_02A.png": ("AHU 02 A", "AHU_02A", "AHU"),
    "VAV_2_05.png": ("VAV_2_05", "VAV_2_05", "VAV"),
    "VAVRH_2_1.png": ("VAVRH_2_1", "VAVRH_2_1", "VAVRH"),
    "fptu_2_01.png": ("FPTU_2_01", "FPTU_2_01", "FPTU"),
    "fcu_02_1.png": ("FCU_02_1", "FCU_02_1", "FCU"),
}


class TestEquipmentExtractionPrompt(unittest.TestCase):
    def load_manifest(self):
        manifest_path = PROMPT_DIR / "v1_few_shot_examples.json"
        with manifest_path.open("r", encoding="utf-8") as manifest_file:
            return json.load(manifest_file)

    def test_manifest_loads_successfully(self):
        manifest = self.load_manifest()

        self.assertIsInstance(manifest, dict)

    def test_prompt_version_is_v1(self):
        manifest = self.load_manifest()

        self.assertEqual(manifest["prompt_version"], "equipment_extraction_v1")

    def test_exactly_five_examples_exist(self):
        manifest = self.load_manifest()

        self.assertEqual(len(manifest["examples"]), 5)

    def test_expected_filenames_are_exact_and_ordered(self):
        manifest = self.load_manifest()
        filenames = [example["image_filename"] for example in manifest["examples"]]

        self.assertEqual(filenames, EXPECTED_FILENAMES)

    def test_image_filenames_are_relative_and_safe(self):
        manifest = self.load_manifest()
        for example in manifest["examples"]:
            image_filename = example["image_filename"]
            normalized_parts = image_filename.replace("\\", "/").split("/")

            self.assertFalse(Path(image_filename).is_absolute())
            self.assertNotIn("..", normalized_parts)

    def test_expected_responses_validate_against_contract(self):
        manifest = self.load_manifest()
        for example in manifest["examples"]:
            response = EquipmentExtractionResponse(**example["expected_response"])

            self.assertEqual(len(response.equipment), 1)

    def test_few_shots_cover_expected_equipment_types(self):
        manifest = self.load_manifest()
        covered_types = set()
        for example in manifest["examples"]:
            response = EquipmentExtractionResponse(**example["expected_response"])
            covered_types.update(item.equipment_type.value for item in response.equipment)

        self.assertEqual(covered_types, {"AHU", "VAV", "VAVRH", "FPTU", "FCU"})

    def test_verified_labels_and_canonical_names_match(self):
        manifest = self.load_manifest()
        for example in manifest["examples"]:
            image_filename = example["image_filename"]
            response = EquipmentExtractionResponse(**example["expected_response"])
            item = response.equipment[0]
            expected_raw_label, expected_canonical_name, expected_type = EXPECTED_LABELS[
                image_filename
            ]

            self.assertEqual(item.raw_label, expected_raw_label)
            self.assertEqual(item.canonical_name, expected_canonical_name)
            self.assertEqual(item.equipment_type.value, expected_type)

    def test_example_order_is_preserved(self):
        manifest = self.load_manifest()
        ordered_raw_labels = [
            EquipmentExtractionResponse(**example["expected_response"]).equipment[0].raw_label
            for example in manifest["examples"]
        ]

        self.assertEqual(
            ordered_raw_labels,
            ["AHU 02 A", "VAV_2_05", "VAVRH_2_1", "FPTU_2_01", "FCU_02_1"],
        )

    def test_prompt_templates_are_non_empty(self):
        self.assertTrue((PROMPT_DIR / "v1_system.md").read_text(encoding="utf-8").strip())
        self.assertTrue(
            (PROMPT_DIR / "v1_user_template.md").read_text(encoding="utf-8").strip()
        )

    def test_system_prompt_requires_core_behavior(self):
        system_prompt = (PROMPT_DIR / "v1_system.md").read_text(encoding="utf-8")
        normalized_prompt = system_prompt.lower()

        required_phrases = [
            "valid json only",
            "exact visible raw label",
            "primary-page equipment",
            "ignore contextual/upstream labels",
            "allowed equipment_type values",
            "do not perform relationship inference",
            "point classification",
            "database writes",
        ]
        for phrase in required_phrases:
            self.assertIn(phrase, normalized_prompt)

    def test_no_binary_source_assets_are_committed_in_prompt_folder(self):
        forbidden_suffixes = {".png", ".jpg", ".jpeg", ".pdf", ".dwg"}
        binary_assets = [
            path
            for path in PROMPT_DIR.rglob("*")
            if path.is_file() and path.suffix.lower() in forbidden_suffixes
        ]

        self.assertEqual(binary_assets, [])


if __name__ == "__main__":
    unittest.main()
