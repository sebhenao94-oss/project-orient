import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

from cost import (  # noqa: E402
    Usage,
    estimate_cost,
    rate_for_model,
    summarize_batch_results,
    usage_from,
)


class _UsageObj:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _Item:
    def __init__(self, status, usage):
        self.status = status
        self.usage = usage


class RateTests(unittest.TestCase):
    def test_exact_and_date_suffix(self):
        self.assertEqual(rate_for_model("claude-haiku-4-5"), (1.0, 5.0))
        self.assertEqual(rate_for_model("claude-haiku-4-5-20251001"), (1.0, 5.0))
        self.assertEqual(rate_for_model("claude-opus-4-8"), (5.0, 25.0))

    def test_unknown_is_none(self):
        self.assertIsNone(rate_for_model("qwen2.5-vl"))
        self.assertIsNone(rate_for_model(None))


class EstimateTests(unittest.TestCase):
    def test_basic_cost(self):
        usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
        self.assertAlmostEqual(estimate_cost(usage, "claude-haiku-4-5"), 6.0)  # 1 + 5

    def test_batch_halves_cost(self):
        usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
        self.assertAlmostEqual(estimate_cost(usage, "claude-haiku-4-5", batch=True), 3.0)

    def test_cache_read_is_cheap(self):
        usage = Usage(cache_read_input_tokens=1_000_000)
        self.assertAlmostEqual(estimate_cost(usage, "claude-haiku-4-5"), 0.1)  # 1.0 * 0.1

    def test_unknown_model_costs_zero(self):
        usage = Usage(input_tokens=10_000_000, output_tokens=10_000_000)
        self.assertEqual(estimate_cost(usage, "qwen2.5-vl"), 0.0)


class UsageFromTests(unittest.TestCase):
    def test_from_dict_and_object_and_none(self):
        d = usage_from({"input_tokens": 10, "output_tokens": 5})
        self.assertEqual((d.input_tokens, d.output_tokens), (10, 5))
        o = usage_from(_UsageObj(input_tokens=3, cache_read_input_tokens=7))
        self.assertEqual((o.input_tokens, o.cache_read_input_tokens), (3, 7))
        self.assertEqual(usage_from(None), Usage())

    def test_usage_addition(self):
        total = Usage(input_tokens=1, output_tokens=2) + Usage(input_tokens=4, output_tokens=8)
        self.assertEqual((total.input_tokens, total.output_tokens), (5, 10))


class SummarizeTests(unittest.TestCase):
    def test_summary_aggregates_and_prices(self):
        items = {
            "a": _Item("succeeded", {"input_tokens": 1000, "output_tokens": 500}),
            "b": _Item("succeeded", {"input_tokens": 2000, "output_tokens": 100}),
            "c": _Item("errored", None),
        }
        summary = summarize_batch_results(items, "claude-haiku-4-5", batch=True)
        self.assertEqual(summary["items"], 3)
        self.assertEqual(summary["succeeded"], 2)
        self.assertEqual(summary["errored"], 1)
        self.assertEqual(summary["input_tokens"], 3000)
        self.assertEqual(summary["output_tokens"], 600)
        self.assertTrue(summary["batch"])
        # (3000 * 1.0 + 600 * 5.0) / 1e6 * 0.5 batch discount
        self.assertAlmostEqual(summary["estimated_cost_usd"], (3000 * 1.0 + 600 * 5.0) / 1e6 * 0.5, places=6)


if __name__ == "__main__":
    unittest.main()
