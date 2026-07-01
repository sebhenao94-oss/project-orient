import re
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
LIBRARY_DIR = PROJECT_ROOT / "equipments_point_types"
sys.path.insert(0, str(PIPELINE_DIR))

import equipment_vocab  # noqa: E402
from equipment_vocab import (  # noqa: E402
    LIBRARY_TYPE_KEYS,
    OFFICIAL_TYPE_KEYS,
    canonical_name,
    classify,
    map_equipment_type,
)


class TestTypeMapping(unittest.TestCase):
    def test_confident_mappings(self):
        for raw in ("AHU", "VAV", "FCU", "OAVAV", "EAVAV"):
            mapping = map_equipment_type(raw)
            self.assertEqual(mapping.mapped_type, raw)
            self.assertFalse(mapping.review_required)

    def test_vavrh_maps_to_hot_water_reheat_with_flag(self):
        mapping = map_equipment_type("VAVRH")
        self.assertEqual(mapping.mapped_type, "VAV-RH-HW")
        self.assertTrue(mapping.review_required)
        self.assertIn("hot-water", mapping.review_reason)

    def test_fptu_is_family_placeholder_with_flag(self):
        mapping = map_equipment_type("FPTU")
        self.assertEqual(mapping.mapped_type, "FPTU")
        self.assertTrue(mapping.review_required)
        self.assertIn("subtype", mapping.review_reason)

    def test_unknown_type_flags_review(self):
        mapping = map_equipment_type("WIDGET")
        self.assertTrue(mapping.review_required)
        self.assertIn("unrecognized", mapping.review_reason)

    def test_case_insensitive(self):
        self.assertEqual(map_equipment_type("ahu").mapped_type, "AHU")


class TestCanonicalName(unittest.TestCase):
    def test_clean_name(self):
        result = canonical_name("AHU_2_1", "AHU")
        self.assertEqual(result.canonical_name, "AHU_2_01")
        self.assertFalse(result.review_required)

    def test_inline_floor_split_flags(self):
        result = canonical_name("AHU_02A", "AHU")
        self.assertEqual(result.canonical_name, "AHU_2_A")
        self.assertTrue(result.review_required)

    def test_qualifier_preserved_in_unit(self):
        result = canonical_name("FCU_PM_2_1", "FCU")
        self.assertEqual(result.canonical_name, "FCU_2_PM_01")

    def test_mapped_type_used_as_prefix(self):
        result = canonical_name("VAVRH_2_1", "VAV-RH-HW")
        self.assertEqual(result.canonical_name, "VAV-RH-HW_2_01")

    def test_classify_combines_type_and_name(self):
        mapped_type, name, review, reason = classify("VAVRH_2_1", "VAVRH")
        self.assertEqual(mapped_type, "VAV-RH-HW")
        self.assertEqual(name, "VAV-RH-HW_2_01")
        self.assertTrue(review)


class TestLibraryInSync(unittest.TestCase):
    """The declared LIBRARY_TYPE_KEYS must match the supervisor's library files."""

    def _library_keys(self):
        keys = set()
        for path in sorted(LIBRARY_DIR.glob("equip_*.py")):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"^\s{4}'([A-Z][A-Z0-9-]*)':\s*\{", text, re.MULTILINE):
                keys.add(match.group(1))
        return keys

    def test_library_keys_present_and_consistent(self):
        library_keys = self._library_keys()
        self.assertTrue(library_keys, "no equipment keys parsed from the library")
        # Every key defined in the library must be declared in LIBRARY_TYPE_KEYS.
        self.assertEqual(library_keys - LIBRARY_TYPE_KEYS, set())
        # And our declared library set should not invent keys absent from the files.
        self.assertEqual(LIBRARY_TYPE_KEYS - library_keys, set())

    def test_official_keys_superset_of_library(self):
        self.assertTrue(LIBRARY_TYPE_KEYS.issubset(OFFICIAL_TYPE_KEYS))


if __name__ == "__main__":
    unittest.main()
