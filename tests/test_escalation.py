import asyncio
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from escalation import (  # noqa: E402
    ExtractionTier,
    build_default_tiers,
    classify_image,
    extract_equipment_with_escalation,
    minimum_equipment_gate,
    succeeded_gate,
)


class _FakeParsed:
    def __init__(self, n):
        self.equipment = list(range(n))


class _FakeResult:
    def __init__(self, status, equipment_count=None):
        self.status = status
        self.parsed_response = _FakeParsed(equipment_count) if equipment_count is not None else None


class _FakeRecord:
    def __init__(self, source_filename, pixel_count):
        self.source_filename = source_filename
        self.pixel_count = pixel_count


def _make_extract(by_model):
    calls = []

    async def extract(*, image_record, prompt_package, model, client):
        calls.append(model)
        return by_model[model]

    return extract, calls


def _tiers(*pairs):
    sentinel = object()
    return [ExtractionTier(name, sentinel, model) for name, model in pairs]


SCREENSHOT = _FakeRecord("shot.png", 1_000_000)
DRAWING = _FakeRecord("drawing.png", 12_000_000)


class GateTests(unittest.TestCase):
    def test_succeeded_gate(self):
        self.assertTrue(succeeded_gate(_FakeResult("succeeded", 2)))
        self.assertFalse(succeeded_gate(_FakeResult("validation_failed")))

    def test_minimum_equipment_gate_rejects_empty(self):
        gate = minimum_equipment_gate(1)
        self.assertFalse(gate(_FakeResult("succeeded", 0)))
        self.assertTrue(gate(_FakeResult("succeeded", 1)))
        self.assertFalse(gate(_FakeResult("succeeded")))  # parsed_response is None

    def test_classify_image(self):
        self.assertEqual(classify_image(SCREENSHOT), "screenshot")
        self.assertEqual(classify_image(DRAWING), "drawing")


class EscalationTests(unittest.TestCase):
    def test_resolves_at_first_tier_without_escalating(self):
        extract, calls = _make_extract({"qwen": _FakeResult("succeeded", 3)})
        outcomes = asyncio.run(
            extract_equipment_with_escalation(
                image_records=[SCREENSHOT],
                prompt_package=None,
                tiers=_tiers(("L1", "qwen"), ("L2", "haiku")),
                extract_fn=extract,
            )
        )
        self.assertEqual(calls, ["qwen"])  # never escalated
        self.assertEqual(outcomes[0].resolved_tier, "L1")
        self.assertEqual(outcomes[0].attempts, [("L1", "succeeded")])

    def test_escalates_on_structural_failure(self):
        extract, calls = _make_extract(
            {"qwen": _FakeResult("validation_failed"), "haiku": _FakeResult("succeeded", 2)}
        )
        outcomes = asyncio.run(
            extract_equipment_with_escalation(
                image_records=[SCREENSHOT],
                prompt_package=None,
                tiers=_tiers(("L1", "qwen"), ("L2", "haiku")),
                extract_fn=extract,
            )
        )
        self.assertEqual(calls, ["qwen", "haiku"])
        self.assertEqual(outcomes[0].resolved_tier, "L2")
        self.assertEqual(
            outcomes[0].attempts, [("L1", "validation_failed"), ("L2", "succeeded")]
        )

    def test_transport_failure_escalates(self):
        # A down Colab L1 surfaces as transport_failed -> climb to Claude.
        extract, calls = _make_extract(
            {"qwen": _FakeResult("transport_failed"), "haiku": _FakeResult("succeeded", 1)}
        )
        outcomes = asyncio.run(
            extract_equipment_with_escalation(
                image_records=[SCREENSHOT],
                prompt_package=None,
                tiers=_tiers(("L1", "qwen"), ("L2", "haiku")),
                extract_fn=extract,
            )
        )
        self.assertEqual(calls, ["qwen", "haiku"])
        self.assertEqual(outcomes[0].resolved_tier, "L2")

    def test_drawing_routes_straight_to_top_tier(self):
        extract, calls = _make_extract({"opus": _FakeResult("succeeded", 5)})
        outcomes = asyncio.run(
            extract_equipment_with_escalation(
                image_records=[DRAWING],
                prompt_package=None,
                tiers=_tiers(("L1", "qwen"), ("L2", "haiku"), ("L3", "sonnet"), ("L4", "opus")),
                extract_fn=extract,
            )
        )
        self.assertEqual(calls, ["opus"])  # skipped L1-L3
        self.assertEqual(outcomes[0].image_class, "drawing")
        self.assertEqual(outcomes[0].resolved_tier, "L4")

    def test_all_tiers_fail_returns_last_attempt(self):
        extract, _ = _make_extract(
            {"qwen": _FakeResult("transport_failed"), "haiku": _FakeResult("parse_failed")}
        )
        outcomes = asyncio.run(
            extract_equipment_with_escalation(
                image_records=[SCREENSHOT],
                prompt_package=None,
                tiers=_tiers(("L1", "qwen"), ("L2", "haiku")),
                extract_fn=extract,
            )
        )
        self.assertIsNone(outcomes[0].resolved_tier)
        self.assertEqual(outcomes[0].result.status, "parse_failed")
        self.assertEqual(len(outcomes[0].attempts), 2)

    def test_minimum_equipment_gate_drives_escalation(self):
        extract, calls = _make_extract(
            {"qwen": _FakeResult("succeeded", 0), "haiku": _FakeResult("succeeded", 3)}
        )
        outcomes = asyncio.run(
            extract_equipment_with_escalation(
                image_records=[SCREENSHOT],
                prompt_package=None,
                tiers=_tiers(("L1", "qwen"), ("L2", "haiku")),
                gate=minimum_equipment_gate(1),
                extract_fn=extract,
            )
        )
        self.assertEqual(calls, ["qwen", "haiku"])  # empty L1 escalated
        self.assertEqual(outcomes[0].resolved_tier, "L2")

    def test_preserves_order_across_images(self):
        extract, _ = _make_extract({"haiku": _FakeResult("succeeded", 1)})
        records = [_FakeRecord(f"{i}.png", 1000) for i in range(5)]
        outcomes = asyncio.run(
            extract_equipment_with_escalation(
                image_records=records,
                prompt_package=None,
                tiers=_tiers(("L2", "haiku")),
                max_concurrency=3,
                extract_fn=extract,
            )
        )
        self.assertEqual([o.source_filename for o in outcomes], [f"{i}.png" for i in range(5)])


class TierBuilderTests(unittest.TestCase):
    def test_default_tiers_without_qwen(self):
        sentinel = object()
        tiers = build_default_tiers(anthropic_client=sentinel, include_qwen=False)
        self.assertEqual([t.name for t in tiers], ["L2-haiku", "L3-sonnet", "L4-opus"])
        self.assertTrue(all(t.client is sentinel for t in tiers))
        self.assertEqual(tiers[-1].model, "claude-opus-4-8")

    def test_default_tiers_with_qwen(self):
        anthropic_sentinel = object()
        qwen_sentinel = object()
        tiers = build_default_tiers(
            anthropic_client=anthropic_sentinel,
            include_qwen=True,
            qwen_client=qwen_sentinel,
            qwen_model="qwen2.5-vl",
        )
        self.assertEqual(
            [t.name for t in tiers], ["L1-qwen", "L2-haiku", "L3-sonnet", "L4-opus"]
        )
        self.assertIs(tiers[0].client, qwen_sentinel)
        self.assertEqual(tiers[0].model, "qwen2.5-vl")


if __name__ == "__main__":
    unittest.main()
