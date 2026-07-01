"""Token-usage accounting and cost estimation for Claude runs.

The brief mandates per-run logging of token usage and cost (it feeds the W8
performance analysis). This module is the pure, reusable engine: a published
price table, batch + prompt-cache multipliers, a usage accumulator, and a
run-summary writer. It consumes plain usage objects/dicts so it stays decoupled
from the client classes. Unknown models (e.g. the free Qwen tier) cost 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

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
