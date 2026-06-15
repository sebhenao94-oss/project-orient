import asyncio
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import relationships  # noqa: E402
from relationship_prompts import RelationshipPromptPackage  # noqa: E402
from llm_client import LLMConnectionError  # noqa: E402
from models import AIReadyImageRecord, RelationshipExtractionResponse  # noqa: E402


SHA = "b" * 64


class FakeClient:
    def __init__(self, responses=None, error=None, delay=0):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.delay = delay

    async def chat_completions_create(self, *, model, messages, timeout_seconds=None):
        self.calls.append({"model": model, "messages": messages})
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.error:
                raise self.error
            content = self.responses.pop(0) if self.responses else '{"relationships":[]}'
            return {"choices": [{"message": {"role": "assistant", "content": content}}]}
        finally:
            self.active -= 1


def write_image(root: Path, filename="ahu.png") -> Path:
    path = root / filename
    path.write_bytes(b"image")
    return path


def image_record(root: Path, filename="ahu.png", eligible=True, sha=SHA):
    path = write_image(root, filename)
    return AIReadyImageRecord(
        source_filename=filename,
        source_relative_path=filename,
        source_file_type="image",
        source_sha256=sha,
        source_local_path=str(path),
        raw_s3_key="Team-4/raw/images/" + filename,
        prepared_image_local_path=str(path),
        prepared_image_filename=filename,
        image_format="PNG",
        image_mime_type="image/png",
        source_page_number=None,
        width=1200,
        height=800,
        pixel_count=960000,
        quality_flag=eligible,
        quality_status="passed" if eligible else "failed",
        quality_reason="ok" if eligible else "too small",
        warnings=[],
        extraction_eligible=eligible,
        preparation_status="prepared" if eligible else "quality_failed",
    )


def prompt_package():
    return RelationshipPromptPackage(
        prompt_version="relationship_mapping_v1",
        system_prompt="system",
        user_template="Equipment:\n<<EQUIPMENT_LIST>>\nReturn JSON.",
        examples=(),
    )


def success_json(child="VAVRH_2_01", parent="AHU_2_01", ref_type="airRef", confidence=0.95, conflict=False, reason=""):
    return json.dumps(
        {
            "relationships": [
                {
                    "child": child,
                    "parent": parent,
                    "ref_type": ref_type,
                    "confidence": confidence,
                    "conflict": conflict,
                    "conflict_reason": reason,
                }
            ]
        }
    )


async def run_image(tmp_dir, content, filename="ahu.png", eligible=True):
    return await relationships.extract_relationships_from_image(
        image_record=image_record(Path(tmp_dir), filename=filename, eligible=eligible),
        equipment_list_text="AHU_2_01\nVAVRH_2_01",
        prompt_package=prompt_package(),
        model="qwen-test",
        client=FakeClient(responses=[content]),
    )


class TestSingleImageRelationship(unittest.IsolatedAsyncioTestCase):
    async def test_success_preserves_raw_and_parsed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            raw = success_json()
            result = await run_image(tmp_dir, raw)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.raw_assistant_response, raw)
        self.assertIsInstance(result.parsed_response, RelationshipExtractionResponse)
        self.assertEqual(result.parsed_response.relationships[0].child, "VAVRH_2_01")
        self.assertEqual(result.source_sha256, SHA)
        self.assertEqual(result.prompt_version, "relationship_mapping_v1")

    async def test_transport_failure_returns_result(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = await relationships.extract_relationships_from_image(
                image_record=image_record(Path(tmp_dir)),
                equipment_list_text="AHU_2_01",
                prompt_package=prompt_package(),
                model="qwen-test",
                client=FakeClient(error=LLMConnectionError("offline")),
            )

        self.assertEqual(result.status, "transport_failed")
        self.assertIsNone(result.parsed_response)
        self.assertTrue(result.error_message)

    async def test_parse_failure_retains_raw(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = await run_image(tmp_dir, "AHU serves the VAVs.")

        self.assertEqual(result.status, "parse_failed")
        self.assertEqual(result.raw_assistant_response, "AHU serves the VAVs.")

    async def test_validation_failure_on_bad_ref_type(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            raw = success_json(ref_type="waterRef")
            result = await run_image(tmp_dir, raw)

        self.assertEqual(result.status, "validation_failed")
        self.assertEqual(result.raw_assistant_response, raw)

    async def test_ineligible_image_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = await relationships.extract_relationships_from_image(
                image_record=image_record(Path(tmp_dir), eligible=False),
                equipment_list_text="AHU_2_01",
                prompt_package=prompt_package(),
                model="qwen-test",
                client=FakeClient(responses=[success_json()]),
            )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.error_type, "ImageNotEligibleForExtraction")


class TestRelationshipBatch(unittest.IsolatedAsyncioTestCase):
    async def test_batch_preserves_order_and_bounds_concurrency(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            records = [
                image_record(Path(tmp_dir), filename=f"img_{index}.png")
                for index in range(4)
            ]
            client = FakeClient(
                responses=[success_json(child=f"VAVRH_2_0{index}") for index in range(4)],
                delay=0.01,
            )
            results = await relationships.extract_relationships_batch(
                image_records=records,
                equipment_list_text="AHU_2_01",
                prompt_package=prompt_package(),
                model="qwen-test",
                max_concurrency=1,
                client=client,
            )

        self.assertEqual([r.source_filename for r in results], [f"img_{i}.png" for i in range(4)])
        self.assertEqual(client.max_active, 1)

    async def test_empty_batch_returns_empty(self):
        results = await relationships.extract_relationships_batch(
            image_records=[],
            equipment_list_text="AHU_2_01",
            prompt_package=prompt_package(),
            model="qwen-test",
            client=FakeClient(),
        )
        self.assertEqual(results, [])


class TestEquipmentListLoading(unittest.TestCase):
    def _write_csv(self, path, rows, column="canonical_name"):
        with path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=[column])
            writer.writeheader()
            for value in rows:
                writer.writerow({column: value})

    def test_distinct_order_preserving(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "eq.csv"
            self._write_csv(path, ["AHU_2_01", "VAVRH_2_01", "AHU_2_01", "VAV_2_01"])
            names = relationships.load_equipment_list(path)

        self.assertEqual(names, ["AHU_2_01", "VAVRH_2_01", "VAV_2_01"])

    def test_missing_column_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "eq.csv"
            self._write_csv(path, ["AHU_2_01"], column="name")
            with self.assertRaises(relationships.RelationshipArtifactError):
                relationships.load_equipment_list(path, name_column="canonical_name")

    def test_empty_names_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "eq.csv"
            self._write_csv(path, ["", "  "])
            with self.assertRaises(relationships.RelationshipArtifactError):
                relationships.load_equipment_list(path)

    def test_custom_column(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "eq.csv"
            self._write_csv(path, ["AHU 02 A"], column="llm_proposed_canonical_name")
            names = relationships.load_equipment_list(
                path, name_column="llm_proposed_canonical_name"
            )
        self.assertEqual(names, ["AHU 02 A"])


class TestRelationshipArtifacts(unittest.IsolatedAsyncioTestCase):
    async def _results(self, tmp_dir):
        ok = await run_image(tmp_dir, success_json(confidence=0.95), filename="a.png")
        low = await run_image(
            tmp_dir, success_json(child="VAV_2_02", confidence=0.4), filename="b.png"
        )
        conflicted = await run_image(
            tmp_dir,
            success_json(child="VAV_2_03", confidence=0.9, conflict=True, reason="two AHUs"),
            filename="c.png",
        )
        failed = await run_image(tmp_dir, "prose only", filename="d.png")
        return [ok, low, conflicted, failed]

    async def test_document_aggregates_edges_with_provenance(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            results = await self._results(tmp_dir)
            document = relationships.build_relationships_document(
                results,
                snapshot_version="w04",
                property_id="pid",
                property_name="msa_orient_building_1",
                floor="Floor_02",
                model_id="qwen-test",
                prompt_version="relationship_mapping_v1",
            )

        # The failed run contributes no edge.
        self.assertEqual(document["relationship_count"], 3)
        by_child = {edge["child"]: edge for edge in document["relationships"]}
        self.assertEqual(by_child["VAVRH_2_01"]["source_drawing"], "a.png")
        self.assertFalse(by_child["VAVRH_2_01"]["review_required"])
        self.assertTrue(by_child["VAV_2_02"]["review_required"])
        self.assertEqual(by_child["VAV_2_02"]["review_reason"], "low_confidence")
        self.assertTrue(by_child["VAV_2_03"]["review_required"])
        self.assertEqual(by_child["VAV_2_03"]["review_reason"], "conflict")

    async def test_write_json_and_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            results = await self._results(tmp_dir)
            json_path = Path(tmp_dir) / "rel.json"
            jsonl_path = Path(tmp_dir) / "runs.jsonl"

            relationships.write_relationships_json(
                results,
                json_path,
                snapshot_version="w04",
                property_id="pid",
                property_name="msa_orient_building_1",
                floor="Floor_02",
                model_id="qwen-test",
                prompt_version="relationship_mapping_v1",
            )
            relationships.write_relationship_runs_jsonl(results, jsonl_path)

            document = json.loads(json_path.read_text(encoding="utf-8"))
            lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()

        self.assertEqual(document["relationship_count"], 3)
        self.assertEqual(len(lines), 4)

    async def test_no_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            results = await self._results(tmp_dir)
            json_path = Path(tmp_dir) / "rel.json"
            json_path.write_text("existing", encoding="utf-8")
            with self.assertRaises(Exception):
                relationships.write_relationships_json(
                    results,
                    json_path,
                    snapshot_version="w04",
                    property_id="pid",
                    property_name="msa_orient_building_1",
                    floor="Floor_02",
                    model_id="qwen-test",
                    prompt_version="relationship_mapping_v1",
                    overwrite=False,
                )


if __name__ == "__main__":
    unittest.main()
