"""Week 4 relationship-mapping orchestration and artifact utilities.

.. deprecated::
    Superseded by ``pipeline/graphics_relationships.py`` — the floor plans
    proved a weak serving-topology source (1 conflicted edge vs 44 from the
    BMS linked-widget pass; see ``docs/relationship_graphics_findings.md``).
    Retained runnable as the W4 floor-plan method for the final report's
    approach comparison; not part of the documented pipeline.

Infers equipment-to-equipment relationships from BMS graphics / drawings using
the relationship_mapping prompt package, parses them strictly, and writes a
versioned relationships JSON plus provenance JSONL. No database writes.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

if __package__:
    from .extraction import (
        _ensure_output_path_available,
        _prepared_image_records_from_dir,
    )
    from .llm_client import (
        LLMClientError,
        OpenAICompatibleClientProtocol,
        configured_llm_model,
        request_relationship_extraction,
    )
    from .relationship_prompts import (
        RelationshipPromptPackage,
        build_relationship_message_plan,
        load_relationship_prompt_package,
    )
    from .relationship_response_parser import (
        RelationshipResponseParseError,
        RelationshipResponseSchemaError,
        parse_relationship_extraction_response,
    )
    from .models import AIReadyImageRecord, RelationshipExtractionRunResult
else:
    from extraction import (
        _ensure_output_path_available,
        _prepared_image_records_from_dir,
    )
    from llm_client import (
        LLMClientError,
        OpenAICompatibleClientProtocol,
        configured_llm_model,
        request_relationship_extraction,
    )
    from relationship_prompts import (
        RelationshipPromptPackage,
        build_relationship_message_plan,
        load_relationship_prompt_package,
    )
    from relationship_response_parser import (
        RelationshipResponseParseError,
        RelationshipResponseSchemaError,
        parse_relationship_extraction_response,
    )
    from models import AIReadyImageRecord, RelationshipExtractionRunResult


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT_ROOT = PROJECT_ROOT / "prompts" / "relationship_mapping"
DEFAULT_RELATIONSHIPS_PATH = (
    PROJECT_ROOT / "data" / "extractions" / "w04" / "relationships_floor_02.json"
)
DEFAULT_RAW_RUNS_PATH = (
    PROJECT_ROOT / "data" / "extractions" / "w04" / "relationship_runs.jsonl"
)
DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.75


class RelationshipArtifactError(ValueError):
    """Raised when relationship inputs or artifacts cannot be handled safely."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _error_type(exc: Exception) -> str:
    return type(exc).__name__


def load_equipment_list(csv_path, name_column: str = "canonical_name") -> List[str]:
    """Read a distinct, order-preserving equipment-name list from a CSV column."""
    csv_path = Path(csv_path)
    names: List[str] = []
    seen = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None or name_column not in reader.fieldnames:
            raise RelationshipArtifactError(
                f"{csv_path}: missing equipment name column '{name_column}'"
            )
        for row in reader:
            value = (row.get(name_column) or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            names.append(value)
    if not names:
        raise RelationshipArtifactError(
            f"{csv_path}: no equipment names found in column '{name_column}'"
        )
    return names


def equipment_list_to_text(names: Sequence[str]) -> str:
    return "\n".join(names)


def _base_run_fields(
    image_record: AIReadyImageRecord,
    prompt_package: RelationshipPromptPackage,
    model: str,
    started_at: datetime,
    completed_at: datetime,
) -> Dict[str, Any]:
    return {
        "source_filename": image_record.source_filename,
        "source_relative_path": image_record.source_relative_path,
        "source_sha256": image_record.source_sha256,
        "source_file_type": image_record.source_file_type,
        "prepared_image_path": image_record.prepared_image_local_path,
        "prepared_image_filename": image_record.prepared_image_filename,
        "image_mime_type": image_record.image_mime_type,
        "pdf_page_number": image_record.source_page_number,
        "prompt_version": prompt_package.prompt_version,
        "model_id": model,
        "started_at": started_at,
        "completed_at": completed_at,
    }


async def extract_relationships_from_image(
    *,
    image_record: AIReadyImageRecord,
    equipment_list_text: str,
    prompt_package: RelationshipPromptPackage,
    model: str,
    client: Optional[OpenAICompatibleClientProtocol] = None,
) -> RelationshipExtractionRunResult:
    """Run one image relationship attempt and return a provenance-rich result."""
    started_at = _utc_now()
    if not image_record.extraction_eligible:
        completed_at = _utc_now()
        return RelationshipExtractionRunResult(
            **_base_run_fields(image_record, prompt_package, model, started_at, completed_at),
            status="skipped",
            error_type="ImageNotEligibleForExtraction",
            error_message=image_record.quality_reason,
        )

    message_plan = build_relationship_message_plan(
        prompt_package,
        equipment_list_text,
        Path(image_record.prepared_image_local_path),
    )

    raw_assistant_response: Optional[str] = None
    try:
        raw_assistant_response = await request_relationship_extraction(
            message_plan=message_plan,
            model=model,
            client=client,
        )
    except LLMClientError as exc:
        completed_at = _utc_now()
        return RelationshipExtractionRunResult(
            **_base_run_fields(image_record, prompt_package, model, started_at, completed_at),
            status="transport_failed",
            error_type=_error_type(exc),
            error_message=str(exc),
        )

    try:
        parsed_response = parse_relationship_extraction_response(raw_assistant_response)
    except RelationshipResponseSchemaError as exc:
        completed_at = _utc_now()
        return RelationshipExtractionRunResult(
            **_base_run_fields(image_record, prompt_package, model, started_at, completed_at),
            status="validation_failed",
            raw_assistant_response=raw_assistant_response,
            error_type=_error_type(exc),
            error_message=str(exc),
        )
    except RelationshipResponseParseError as exc:
        completed_at = _utc_now()
        return RelationshipExtractionRunResult(
            **_base_run_fields(image_record, prompt_package, model, started_at, completed_at),
            status="parse_failed",
            raw_assistant_response=raw_assistant_response,
            error_type=_error_type(exc),
            error_message=str(exc),
        )

    completed_at = _utc_now()
    return RelationshipExtractionRunResult(
        **_base_run_fields(image_record, prompt_package, model, started_at, completed_at),
        status="succeeded",
        raw_assistant_response=raw_assistant_response,
        parsed_response=parsed_response,
    )


async def extract_relationships_batch(
    *,
    image_records: Sequence[AIReadyImageRecord],
    equipment_list_text: str,
    prompt_package: RelationshipPromptPackage,
    model: str,
    max_concurrency: int = 1,
    client: Optional[OpenAICompatibleClientProtocol] = None,
) -> List[RelationshipExtractionRunResult]:
    """Run bounded-concurrency relationship inference and preserve input order."""
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_one(record: AIReadyImageRecord) -> RelationshipExtractionRunResult:
        async with semaphore:
            return await extract_relationships_from_image(
                image_record=record,
                equipment_list_text=equipment_list_text,
                prompt_package=prompt_package,
                model=model,
                client=client,
            )

    tasks = [asyncio.create_task(run_one(record)) for record in image_records]
    if not tasks:
        return []
    return list(await asyncio.gather(*tasks))


def write_relationship_runs_jsonl(
    results: Sequence[RelationshipExtractionRunResult],
    output_path,
    overwrite: bool = False,
) -> Path:
    """Write complete relationship-run evidence as deterministic JSONL."""
    output_path = Path(output_path)
    _ensure_output_path_available(output_path, overwrite)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        for result in results:
            output_file.write(json.dumps(result.model_dump(mode="json"), sort_keys=True))
            output_file.write("\n")
    return output_path


def build_relationships_document(
    results: Sequence[RelationshipExtractionRunResult],
    *,
    snapshot_version: str,
    property_id: str,
    property_name: str,
    floor: str,
    model_id: str,
    prompt_version: str,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> Dict[str, Any]:
    """Aggregate successful edges into a provenance-rich relationships document."""
    edges: List[Dict[str, Any]] = []
    for result in results:
        if result.status != "succeeded" or result.parsed_response is None:
            continue
        for edge in result.parsed_response.relationships:
            below_threshold = edge.confidence < low_confidence_threshold
            review_required = below_threshold or edge.conflict
            reasons = []
            if below_threshold:
                reasons.append("low_confidence")
            if edge.conflict:
                reasons.append("conflict")
            edges.append(
                {
                    "child": edge.child,
                    "parent": edge.parent,
                    "ref_type": edge.ref_type.value,
                    "confidence": edge.confidence,
                    "conflict": edge.conflict,
                    "conflict_reason": edge.conflict_reason,
                    "source_drawing": result.source_filename,
                    "source_sha256": result.source_sha256,
                    "review_required": review_required,
                    "review_reason": ";".join(reasons),
                }
            )
    return {
        "snapshot_version": snapshot_version,
        "property_id": property_id,
        "property_name": property_name,
        "floor": floor,
        "prompt_version": prompt_version,
        "model_id": model_id,
        "relationship_count": len(edges),
        "relationships": edges,
    }


def write_relationships_json(
    results: Sequence[RelationshipExtractionRunResult],
    output_path,
    *,
    snapshot_version: str,
    property_id: str,
    property_name: str,
    floor: str,
    model_id: str,
    prompt_version: str,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    overwrite: bool = False,
) -> Path:
    """Write the aggregated relationships document as a JSON file."""
    output_path = Path(output_path)
    _ensure_output_path_available(output_path, overwrite)
    document = build_relationships_document(
        results,
        snapshot_version=snapshot_version,
        property_id=property_id,
        property_name=property_name,
        floor=floor,
        model_id=model_id,
        prompt_version=prompt_version,
        low_confidence_threshold=low_confidence_threshold,
    )
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        json.dump(document, output_file, indent=2)
        output_file.write("\n")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project ORIENT W4 relationship mapping (no database writes)."
    )
    parser.add_argument("--equipment-csv", required=True)
    parser.add_argument("--equipment-name-column", default="canonical_name")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--prompt-root", default=str(DEFAULT_PROMPT_ROOT))
    parser.add_argument("--prompt-version", default="relationship_mapping_v2")
    parser.add_argument("--property-id", default="unknown")
    parser.add_argument("--property-name", default="unknown")
    parser.add_argument("--floor", default="Floor_02")
    parser.add_argument("--snapshot-version", default="w04")
    parser.add_argument("--relationships-path", default=str(DEFAULT_RELATIONSHIPS_PATH))
    parser.add_argument("--raw-runs-path", default=str(DEFAULT_RAW_RUNS_PATH))
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    prompt_package = load_relationship_prompt_package(
        args.prompt_version, Path(args.prompt_root)
    )
    names = load_equipment_list(args.equipment_csv, args.equipment_name_column)
    equipment_list_text = equipment_list_to_text(names)
    image_records = _prepared_image_records_from_dir(args.input_dir, floor=args.floor)
    eligible = [record for record in image_records if record.extraction_eligible]

    print(f"Equipment list: {len(names)} distinct names from {args.equipment_csv}")
    print(f"Prepared images: {len(image_records)} ({len(eligible)} eligible)")

    if not args.run_live:
        print("Dry run (no --run-live): skipping LLM calls and artifact writes.")
        return 0

    model = args.model or configured_llm_model()
    results = asyncio.run(
        extract_relationships_batch(
            image_records=image_records,
            equipment_list_text=equipment_list_text,
            prompt_package=prompt_package,
            model=model,
            max_concurrency=args.max_concurrency,
        )
    )

    runs_path = write_relationship_runs_jsonl(
        results, args.raw_runs_path, overwrite=args.overwrite
    )
    json_path = write_relationships_json(
        results,
        args.relationships_path,
        snapshot_version=args.snapshot_version,
        property_id=args.property_id,
        property_name=args.property_name,
        floor=args.floor,
        model_id=model,
        prompt_version=prompt_package.prompt_version,
        overwrite=args.overwrite,
    )

    succeeded = sum(1 for result in results if result.status == "succeeded")
    edge_count = sum(
        len(result.parsed_response.relationships)
        for result in results
        if result.status == "succeeded" and result.parsed_response is not None
    )
    print(f"Run evidence written: {runs_path}")
    print(f"Relationships written: {json_path}")
    print(f"Succeeded: {succeeded}/{len(results)} images; {edge_count} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
