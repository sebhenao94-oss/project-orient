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
]
EXPECTED_COUNTS = {
    "AHU_02A.png": 1,
    "VAV_2_05.png": 2,
    "VAVRH_2_1.png": 1,
}

EXPECTED_LABELS = {
    "AHU_02A.png": ("AHU 02 A", "AHU_02A", "AHU"),
    "VAV_2_05.png": ("VAV_2_05", "VAV_2_05", "VAV"),
    "VAVRH_2_1.png": ("VAVRH_2_1", "VAVRH_2_1", "VAV-RH-HW"),
}

EXPECTED_ITEMS = {
    "AHU_02A.png": [
        ("AHU 02 A", "AHU_02A", "AHU", 0.98),
    ],
    "VAV_2_05.png": [
        ("VAV_2_05", "VAV_2_05", "VAV", 0.99),
        ("AHU 02 A", "AHU_02A", "AHU", 0.99),
    ],
    "VAVRH_2_1.png": [
        ("VAVRH_2_1", "VAVRH_2_1", "VAV-RH-HW", 0.99),
    ],
}


class TestEquipmentExtractionPrompt(unittest.TestCase):
    def load_manifest(self):
        manifest_path = PROMPT_DIR / "v3_few_shot_examples.json"
        with manifest_path.open("r", encoding="utf-8") as manifest_file:
            return json.load(manifest_file)

    def test_manifest_loads_successfully(self):
        manifest = self.load_manifest()

        self.assertIsInstance(manifest, dict)

    def test_prompt_version_is_current(self):
        manifest = self.load_manifest()

        self.assertEqual(manifest["prompt_version"], "equipment_extraction_v3")

    def test_exactly_three_examples_exist(self):
        manifest = self.load_manifest()

        self.assertEqual(len(manifest["examples"]), 3)

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

            self.assertEqual(len(response.equipment), EXPECTED_COUNTS[example["image_filename"]])

    def test_few_shots_cover_expected_equipment_types(self):
        manifest = self.load_manifest()
        covered_types = set()
        for example in manifest["examples"]:
            response = EquipmentExtractionResponse(**example["expected_response"])
            covered_types.update(item.equipment_type for item in response.equipment)

        self.assertEqual(covered_types, {"AHU", "VAV", "VAV-RH-HW"})

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
            self.assertEqual(item.equipment_type, expected_type)

    def test_exact_items_and_order_match_ground_truth(self):
        manifest = self.load_manifest()
        for example in manifest["examples"]:
            filename = example["image_filename"]
            response = EquipmentExtractionResponse(**example["expected_response"])
            actual_items = [
                (
                    item.raw_label,
                    item.canonical_name,
                    item.equipment_type,
                    item.confidence,
                )
                for item in response.equipment
            ]

            self.assertEqual(actual_items, EXPECTED_ITEMS[filename])

    def test_example_order_is_preserved(self):
        manifest = self.load_manifest()
        ordered_raw_labels = [
            EquipmentExtractionResponse(**example["expected_response"]).equipment[0].raw_label
            for example in manifest["examples"]
        ]

        self.assertEqual(
            ordered_raw_labels,
            ["AHU 02 A", "VAV_2_05", "VAVRH_2_1"],
        )

    def test_every_expected_item_has_valid_confidence(self):
        manifest = self.load_manifest()
        for example in manifest["examples"]:
            response = EquipmentExtractionResponse(**example["expected_response"])
            for item in response.equipment:
                self.assertIsInstance(item.confidence, float)
                self.assertGreaterEqual(item.confidence, 0.0)
                self.assertLessEqual(item.confidence, 1.0)

    def test_no_exact_raw_label_repeats_within_one_response(self):
        manifest = self.load_manifest()
        for example in manifest["examples"]:
            response = EquipmentExtractionResponse(**example["expected_response"])
            raw_labels = [item.raw_label for item in response.equipment]

            self.assertEqual(len(raw_labels), len(set(raw_labels)))

    def test_held_out_oavav_image_is_not_in_manifest(self):
        manifest = self.load_manifest()
        filenames = [example["image_filename"] for example in manifest["examples"]]

        self.assertNotIn("OAVAV_02_01.png", filenames)

    def test_prompt_templates_are_non_empty(self):
        self.assertTrue((PROMPT_DIR / "v3_system.md").read_text(encoding="utf-8").strip())
        self.assertTrue(
            (PROMPT_DIR / "v3_user_template.md").read_text(encoding="utf-8").strip()
        )

    def test_system_prompt_requires_core_behavior(self):
        system_prompt = (PROMPT_DIR / "v3_system.md").read_text(encoding="utf-8")
        normalized_prompt = system_prompt.lower()

        required_phrases = [
            "raw json only",
            "complete visible raw label",
            "direct visual",
            "include clearly visible contextual",
            "generated equipment type context",
            "do not infer relationships",
            "point classification",
            "database writes",
        ]
        for phrase in required_phrases:
            self.assertIn(phrase, normalized_prompt)

    def test_system_prompt_includes_all_visible_equipment_behavior(self):
        prompt = (PROMPT_DIR / "v3_system.md").read_text(encoding="utf-8").lower()

        self.assertIn("every distinct clearly visible", prompt)
        self.assertIn("not limited to the page title", prompt)
        self.assertIn("contextual, upstream, and neighboring", prompt)

    def test_system_prompt_excludes_points_and_statuses_from_candidates_only(self):
        prompt = (PROMPT_DIR / "v3_system.md").read_text(encoding="utf-8").lower()

        self.assertIn("equipment candidate list", prompt)
        self.assertIn("measurements", prompt)
        self.assertIn("statuses", prompt)
        self.assertIn("setpoints", prompt)
        self.assertIn("alarms", prompt)
        self.assertIn("not deleted from the source image", prompt)
        self.assertIn("point-classification", prompt)
        self.assertIn("relationship-mapping", prompt)
        self.assertIn("zone-orientation", prompt)
        self.assertIn("fan, filter, damper, or coil", prompt)

    def test_system_prompt_requires_one_result_per_distinct_identifier(self):
        prompt = (PROMPT_DIR / "v3_system.md").read_text(encoding="utf-8").lower()

        self.assertIn("return it once", prompt)
        self.assertIn("within-image repeated-label suppression", prompt)

    def test_system_prompt_says_cross_image_deduplication_is_downstream(self):
        prompt = (PROMPT_DIR / "v3_system.md").read_text(encoding="utf-8").lower()

        self.assertIn("cross-image deduplication is downstream work", prompt)

    def test_system_prompt_requires_all_four_output_fields(self):
        prompt = (PROMPT_DIR / "v3_system.md").read_text(encoding="utf-8").lower()

        self.assertIn("raw_label", prompt)
        self.assertIn("canonical_name", prompt)
        self.assertIn("equipment_type", prompt)
        self.assertIn("confidence", prompt)

    def test_system_prompt_limits_normalization_to_candidate(self):
        prompt = (PROMPT_DIR / "v3_system.md").read_text(encoding="utf-8").lower()

        self.assertIn("conservative canonical_name candidate", prompt)
        self.assertIn("do not perform final canonical-name approval", prompt)
        self.assertIn("downstream normalization beyond", prompt)
        self.assertIn("later pipeline and human-review", prompt)

    def test_user_template_excludes_non_equipment_from_candidate_list_only(self):
        prompt = (PROMPT_DIR / "v3_user_template.md").read_text(encoding="utf-8").lower()

        self.assertIn("equipment candidate", prompt)
        self.assertIn("must not become equipment candidates", prompt)
        self.assertIn("original full image", prompt)
        self.assertIn("preserved for later", prompt)
        self.assertIn("contextual", prompt)
        self.assertIn("upstream", prompt)
        self.assertIn("neighboring", prompt)
        self.assertIn("fan, filter, damper, or coil", prompt)

    def test_system_prompt_prohibits_bare_arrays_and_markdown_fences(self):
        prompt = (PROMPT_DIR / "v3_system.md").read_text(encoding="utf-8").lower()

        self.assertIn("never return a", prompt)
        self.assertIn("bare array", prompt)
        self.assertIn("without markdown fences", prompt)

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
