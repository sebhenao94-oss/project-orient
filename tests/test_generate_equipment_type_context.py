import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
PROMPT_DIR = PROJECT_ROOT / "prompts" / "equipment_extraction"
sys.path.insert(0, str(PIPELINE_DIR))

import generate_equipment_type_context as gen  # noqa: E402
from equipment_prompts import load_equipment_prompt_package  # noqa: E402
from equipment_vocab import LIBRARY_TYPE_KEYS  # noqa: E402


class TestEquipmentTypeContextGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definitions = gen.load_equipment_definitions(gen.DEFAULT_EQUIPMENT_DIR)

    def test_definitions_match_vocabulary_library_keys(self):
        self.assertEqual(set(self.definitions), set(LIBRARY_TYPE_KEYS))

    def test_simple_context_lists_type_names_only(self):
        text = gen.render_simple_context(self.definitions)
        for equipment_type in self.definitions:
            self.assertIn(f"- {equipment_type}", text)
        # The point-type payload must be stripped in simple mode.
        self.assertNotIn("Disc_airtemp", text)
        self.assertNotIn("Point types:", text)
        self.assertNotIn("Equip tags:", text)

    def test_full_context_carries_point_types_and_tags(self):
        text = gen.render_full_context(self.definitions)
        self.assertIn("## AHU", text)
        self.assertIn("Point types:", text)
        self.assertIn("Disc_airtemp", text)
        self.assertIn("Equip tags:", text)

    def test_committed_artifact_is_current_simple_output(self):
        committed = gen.DEFAULT_OUTPUT
        self.assertTrue(committed.exists(), "prompts/equipment_type_context.md must be committed")
        self.assertEqual(
            committed.read_text(encoding="utf-8"),
            gen.render_simple_context(self.definitions),
            "committed artifact is stale; regenerate with "
            "py -m pipeline.generate_equipment_type_context --simple",
        )

    def test_main_simple_writes_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "context.md"
            exit_code = gen.main(["--simple", "--output", str(output)])
            self.assertEqual(exit_code, 0)
            self.assertIn("- AHU", output.read_text(encoding="utf-8"))


class TestPromptPackageTypeContext(unittest.TestCase):
    EXAMPLE_FILENAMES = ["AHU_02A.png", "VAV_2_05.png", "VAVRH_2_1.png"]

    def _fixture_dirs(self, root: Path):
        prompt_root = root / "prompts"
        prompt_root.mkdir(parents=True)
        for filename in ("v4_system.md", "v4_user_template.md", "v4_few_shot_examples.json"):
            shutil.copyfile(PROMPT_DIR / filename, prompt_root / filename)
        example_dir = root / "examples"
        example_dir.mkdir(parents=True)
        for filename in self.EXAMPLE_FILENAMES:
            (example_dir / filename).write_bytes(b"not real image bytes")
        return prompt_root, example_dir

    def test_type_context_appended_to_system_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt_root, example_dir = self._fixture_dirs(root)
            context_path = root / "equipment_type_context.md"
            context_path.write_text("# Equipment Types\n\n- AHU\n- FCU\n", encoding="utf-8")

            without = load_equipment_prompt_package(
                "equipment_extraction_v4", prompt_root, example_dir
            )
            with_context = load_equipment_prompt_package(
                "equipment_extraction_v4",
                prompt_root,
                example_dir,
                type_context_path=context_path,
            )

        self.assertNotIn("# Equipment Types", without.system_prompt)
        self.assertTrue(with_context.system_prompt.startswith(without.system_prompt.rstrip()))
        self.assertIn("# Equipment Types", with_context.system_prompt)
        self.assertIn("- FCU", with_context.system_prompt)

    def test_missing_type_context_file_raises(self):
        from equipment_prompts import PromptPackageFileError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt_root, example_dir = self._fixture_dirs(root)
            with self.assertRaises(PromptPackageFileError):
                load_equipment_prompt_package(
                    "equipment_extraction_v4",
                    prompt_root,
                    example_dir,
                    type_context_path=root / "does_not_exist.md",
                )


if __name__ == "__main__":
    unittest.main()
