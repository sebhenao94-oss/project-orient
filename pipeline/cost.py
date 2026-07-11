"""Token-usage accounting and cost estimation for Claude runs.

The brief mandates per-run logging of token usage and cost (it feeds the W8
performance analysis). This module is the pure, reusable engine: a published
price table, batch + prompt-cache multipliers, a usage accumulator, and a
run-summary writer. It consumes plain usage objects/dicts so it stays decoupled
from the client classes. Unknown models (e.g. the free Qwen tier) cost 0.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

# USD per 1M tokens (input, output). Source: published Anthropic pricing.
PRICING_PER_MTOK: Dict[str, Tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

BATCH_DISCOUNT = 0.5
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + other.cache_creation_input_tokens,
        )


def rate_for_model(model: Optional[str]) -> Optional[Tuple[float, float]]:
    """(input, output) USD/MTok for a model id, tolerating date suffixes."""
    if not model:
        return None
    if model in PRICING_PER_MTOK:
        return PRICING_PER_MTOK[model]
    for key, rate in PRICING_PER_MTOK.items():
        if model.startswith(key):
            return rate
    return None


def usage_from(obj: Any) -> Usage:
    """Coerce an Anthropic usage object or dict into a Usage."""
    if obj is None:
        return Usage()

    def field(name: str) -> int:
        value = obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, 0)
        return int(value or 0)

    return Usage(
        input_tokens=field("input_tokens"),
        output_tokens=field("output_tokens"),
        cache_read_input_tokens=field("cache_read_input_tokens"),
        cache_creation_input_tokens=field("cache_creation_input_tokens"),
    )


def estimate_cost(usage: Usage, model: Optional[str], *, batch: bool = False) -> float:
    """Estimate USD cost for one Usage on a model. Unknown model -> 0.0."""
    rate = rate_for_model(model)
    if rate is None:
        return 0.0
    in_rate, out_rate = rate
    cost = (
        usage.input_tokens * in_rate
        + usage.cache_read_input_tokens * in_rate * CACHE_READ_MULTIPLIER
        + usage.cache_creation_input_tokens * in_rate * CACHE_WRITE_MULTIPLIER
        + usage.output_tokens * out_rate
    ) / 1_000_000.0
    return cost * (BATCH_DISCOUNT if batch else 1.0)


def summarize_batch_results(
    batch_results: Mapping[str, Any],
    model: str,
    *,
    batch: bool = True,
) -> Dict[str, Any]:
    """Aggregate token usage + estimated cost across a batch's item results.

    ``batch_results`` maps custom_id -> object with ``.status`` and ``.usage``
    (an Anthropic usage object/dict or None), as produced by
    AnthropicMessagesClient.collect_batch_results.
    """
    total = Usage()
    succeeded = 0
    errored = 0
    for item in batch_results.values():
        if getattr(item, "status", None) == "succeeded":
            succeeded += 1
        else:
            errored += 1
        total = total + usage_from(getattr(item, "usage", None))

    return {
        "model": model,
        "batch": batch,
        "items": len(batch_results),
        "succeeded": succeeded,
        "errored": errored,
        "input_tokens": total.input_tokens,
        "output_tokens": total.output_tokens,
        "cache_read_input_tokens": total.cache_read_input_tokens,
        "cache_creation_input_tokens": total.cache_creation_input_tokens,
        "estimated_cost_usd": round(estimate_cost(total, model, batch=batch), 6),
    }


def write_cost_log(path: Any, summary: Mapping[str, Any]) -> Path:
    """Write a run cost summary as JSON for the W8 performance analysis."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(dict(summary), handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


class UsageRecorder:
    """Run-scoped accumulator of token usage per (model, batch-mode).

    Every LLM call site records its response usage here (see ``record_usage``),
    so a pipeline run can report tokens per model and total tokens start to
    finish regardless of which stage — extraction, escalation tier, tiling,
    topics parsing, vision second pass — spent them. Thread-safe because the
    Anthropic client executes requests on executor threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: Dict[Tuple[str, bool], Dict[str, Any]] = {}

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def record(self, model: Optional[str], usage_obj: Any, *, batch: bool = False) -> None:
        usage = usage_from(usage_obj)
        key = (model or "unknown", bool(batch))
        with self._lock:
            bucket = self._buckets.setdefault(key, {"usage": Usage(), "calls": 0})
            bucket["usage"] = bucket["usage"] + usage
            bucket["calls"] += 1

    def snapshot(self) -> Dict[str, Any]:
        """Per-model token/cost breakdown plus run totals."""
        with self._lock:
            items = sorted(self._buckets.items())

        models: List[Dict[str, Any]] = []
        total = Usage()
        total_calls = 0
        total_cost = 0.0
        for (model, batch), bucket in items:
            usage: Usage = bucket["usage"]
            cost = estimate_cost(usage, model, batch=batch)
            models.append(
                {
                    "model": model,
                    "batch": batch,
                    "calls": bucket["calls"],
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_input_tokens": usage.cache_read_input_tokens,
                    "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                    "estimated_cost_usd": round(cost, 6),
                }
            )
            total = total + usage
            total_calls += bucket["calls"]
            total_cost += cost

        return {
            "models": models,
            "totals": {
                "calls": total_calls,
                "input_tokens": total.input_tokens,
                "output_tokens": total.output_tokens,
                "cache_read_input_tokens": total.cache_read_input_tokens,
                "cache_creation_input_tokens": total.cache_creation_input_tokens,
                "total_tokens": (
                    total.input_tokens
                    + total.output_tokens
                    + total.cache_read_input_tokens
                    + total.cache_creation_input_tokens
                ),
                "estimated_cost_usd": round(total_cost, 6),
            },
        }


# One recorder per process; pipeline CLIs reset it at run start and snapshot it
# into run_metrics.json at the end.
GLOBAL_USAGE = UsageRecorder()


def record_usage(model: Optional[str], usage_obj: Any, *, batch: bool = False) -> None:
    """Record one LLM response's usage into the run-global recorder."""
    GLOBAL_USAGE.record(model, usage_obj, batch=batch)


def write_run_metrics(
    path: Any,
    *,
    counts: Optional[Mapping[str, Any]] = None,
    run: Optional[Mapping[str, Any]] = None,
    recorder: Optional[UsageRecorder] = None,
) -> Path:
    """Write the end-to-end run metrics JSON (lead final-checklist 2b).

    ``run`` carries run identity (command, model, prompt version, timings);
    ``counts`` carries pipeline outcome counts (image statuses, confident vs
    review-flagged items); usage comes from the recorder snapshot.
    """
    payload = {
        "run": dict(run or {}),
        "counts": dict(counts or {}),
        "usage": (recorder or GLOBAL_USAGE).snapshot(),
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path
