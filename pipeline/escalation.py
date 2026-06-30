"""Cheapest-first escalation orchestrator for equipment extraction.

Routes each image through a tier ladder (free Qwen L1 -> Haiku L2 -> Sonnet L3
-> Opus L4), escalating only when a STRUCTURAL gate fails -- never on the
model's self-reported confidence, which W4 showed is uncalibrated (~0.99 even
on errors). Image class sets the entry tier (drawings route straight to the
top tier, since L1-L3 cannot read them); a failed or unreachable cheaper tier
escalates automatically, so a down Colab L1 endpoint routes straight to Claude.

The per-image extraction call is injectable (``extract_fn``) so the ladder
logic is unit-testable without live models or real images. The default uses
``extraction.extract_equipment_from_image``.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence, Tuple

if __package__:
    from .extraction import extract_equipment_from_image
    from .llm_client import (
        OpenAICompatibleClientProtocol,
        UrllibOpenAICompatibleClient,
    )
    from .models import AIReadyImageRecord, EquipmentExtractionRunResult
    from .equipment_prompts import EquipmentPromptPackage
else:
    from extraction import extract_equipment_from_image
    from llm_client import (
        OpenAICompatibleClientProtocol,
        UrllibOpenAICompatibleClient,
    )
    from models import AIReadyImageRecord, EquipmentExtractionRunResult
    from equipment_prompts import EquipmentPromptPackage


# A drawing is large, dense line-work; screenshots are screen-resolution. The
# threshold only picks the *entry* tier -- escalation still corrects a misroute.
DRAWING_PIXEL_THRESHOLD = 8_000_000
_QWEN_BASE_URL_PLACEHOLDER = "your_vllm_endpoint_here"


@dataclass
class ExtractionTier:
    """One rung of the ladder: a client + model, cheapest first."""

    name: str
    client: OpenAICompatibleClientProtocol
    model: str


@dataclass
class EscalationOutcome:
    """The resolved result for one image plus the trail of attempts."""

    source_filename: Optional[str]
    image_class: str
    resolved_tier: Optional[str]
    result: Any  # EquipmentExtractionRunResult (or whatever extract_fn returns)
    attempts: List[Tuple[str, str]] = field(default_factory=list)  # (tier_name, status)


# --------------------------------------------------------------------------- #
# Structural gates: decide accept vs. escalate. Never confidence-based.        #
# --------------------------------------------------------------------------- #

def succeeded_gate(result: Any) -> bool:
    """Baseline structural gate: the strict-schema parse succeeded."""
    return getattr(result, "status", None) == "succeeded"


def minimum_equipment_gate(min_count: int = 1) -> Callable[[Any], bool]:
    """Accept only if parse succeeded AND at least ``min_count`` items came back.

    Catches the silent under-extraction case (valid JSON, but empty/short) that
    a parse-only gate would wave through.
    """

    def gate(result: Any) -> bool:
        if getattr(result, "status", None) != "succeeded":
            return False
        parsed = getattr(result, "parsed_response", None)
        equipment = getattr(parsed, "equipment", None) if parsed is not None else None
        return equipment is not None and len(equipment) >= min_count

    return gate


# --------------------------------------------------------------------------- #
# Routing                                                                      #
# --------------------------------------------------------------------------- #

def classify_image(image_record: AIReadyImageRecord) -> str:
    """Best-effort image class: 'drawing' (huge/dense) vs. 'screenshot'."""
    pixel_count = getattr(image_record, "pixel_count", None) or 0
    return "drawing" if pixel_count > DRAWING_PIXEL_THRESHOLD else "screenshot"


def default_entry_index(image_class: str, tiers: Sequence[ExtractionTier]) -> int:
    """Drawings start at the top tier (only it can read them); else cheapest."""
    if image_class == "drawing":
        return len(tiers) - 1
    return 0


def build_default_tiers(
    *,
    anthropic_client: Optional[OpenAICompatibleClientProtocol] = None,
    include_qwen: Optional[bool] = None,
    qwen_client: Optional[OpenAICompatibleClientProtocol] = None,
    qwen_model: Optional[str] = None,
    haiku_model: str = "claude-haiku-4-5",
    sonnet_model: str = "claude-sonnet-4-6",
    opus_model: str = "claude-opus-4-8",
) -> List[ExtractionTier]:
    """Construct the cheapest-first ladder from the environment.

    L1 (free Qwen) is included only when an OpenAI-compatible base URL is
    configured (i.e. the Colab tunnel is up); otherwise the ladder starts at
    Haiku and the free tier is simply skipped. L2-L4 share one Anthropic client,
    varying only the model.
    """
    tiers: List[ExtractionTier] = []

    if include_qwen is None:
        base_url = os.getenv("LLM_BASE_URL")
        include_qwen = bool(base_url) and base_url != _QWEN_BASE_URL_PLACEHOLDER
    if include_qwen:
        client = qwen_client or UrllibOpenAICompatibleClient.from_environment()
        model = qwen_model or os.getenv("QWEN_MODEL") or os.getenv("LLM_MODEL")
        if model:
            tiers.append(ExtractionTier("L1-qwen", client, model))

    if anthropic_client is None:
        if __package__:
            from .anthropic_client import AnthropicMessagesClient
        else:
            from anthropic_client import AnthropicMessagesClient
        anthropic_client = AnthropicMessagesClient.from_environment()

    tiers.append(ExtractionTier("L2-haiku", anthropic_client, haiku_model))
    tiers.append(ExtractionTier("L3-sonnet", anthropic_client, sonnet_model))
    tiers.append(ExtractionTier("L4-opus", anthropic_client, opus_model))
    return tiers


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #

async def _escalate_one(
    *,
    image_record: AIReadyImageRecord,
    prompt_package: EquipmentPromptPackage,
    tiers: Sequence[ExtractionTier],
    classify: Callable[[AIReadyImageRecord], str],
    entry_index_for: Callable[[str, Sequence[ExtractionTier]], int],
    gate: Callable[[Any], bool],
    extract_fn: Callable[..., Any],
) -> EscalationOutcome:
    image_class = classify(image_record)
    start = entry_index_for(image_class, tiers)
    attempts: List[Tuple[str, str]] = []
    last_result: Any = None

    for tier in tiers[start:]:
        result = await extract_fn(
            image_record=image_record,
            prompt_package=prompt_package,
            model=tier.model,
            client=tier.client,
        )
        last_result = result
        status = getattr(result, "status", "unknown")
        attempts.append((tier.name, status))
        if gate(result):
            return EscalationOutcome(
                source_filename=getattr(image_record, "source_filename", None),
                image_class=image_class,
                resolved_tier=tier.name,
                result=result,
                attempts=attempts,
            )

    # No tier satisfied the gate -- return the last (most capable) attempt.
    return EscalationOutcome(
        source_filename=getattr(image_record, "source_filename", None),
        image_class=image_class,
        resolved_tier=None,
        result=last_result,
        attempts=attempts,
    )


async def extract_equipment_with_escalation(
    *,
    image_records: Sequence[AIReadyImageRecord],
    prompt_package: EquipmentPromptPackage,
    tiers: Sequence[ExtractionTier],
    classify: Callable[[AIReadyImageRecord], str] = classify_image,
    entry_index_for: Callable[[str, Sequence[ExtractionTier]], int] = default_entry_index,
    gate: Callable[[Any], bool] = succeeded_gate,
    max_concurrency: int = 1,
    extract_fn: Optional[Callable[..., Any]] = None,
) -> List[EscalationOutcome]:
    """Run cheapest-first escalation over a batch of images, preserving order.

    Each image climbs its tier ladder until ``gate`` accepts a result (escalate
    on structural failure only). Images are processed with bounded concurrency;
    the per-image climb is sequential.
    """
    if not tiers:
        raise ValueError("tiers must not be empty")
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    runner = extract_fn or extract_equipment_from_image
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_one(record: AIReadyImageRecord) -> EscalationOutcome:
        async with semaphore:
            return await _escalate_one(
                image_record=record,
                prompt_package=prompt_package,
                tiers=tiers,
                classify=classify,
                entry_index_for=entry_index_for,
                gate=gate,
                extract_fn=runner,
            )

    tasks = [asyncio.create_task(run_one(record)) for record in image_records]
    if not tasks:
        return []
    return list(await asyncio.gather(*tasks))
