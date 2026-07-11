"""Week 3 equipment extraction orchestration and snapshot utilities."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import os
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import ValidationError

if __package__:
    from .checkpoint import RunCheckpoint, checkpoint_key
    from .equipment_prompts import EquipmentPromptPackage, build_equipment_message_plan, load_equipment_prompt_package
    from .equipment_response_parser import (
        EquipmentResponseParseError,
        EquipmentResponseSchemaError,
        parse_equipment_extraction_response,
    )
    from .ingestion import check_image_quality
    from .llm_client import (
        LLMClientError,
        OpenAICompatibleClientProtocol,
        build_llm_client_from_environment,
        configured_llm_model,
        request_equipment_extraction,
        serialize_equipment_message_plan,
    )
    from .models import (
        AIReadyImageRecord,
        EquipmentExtractionCandidate,
        EquipmentExtractionResponse,
        EquipmentExtractionRunResult,
        RawDrawingEquipmentRecord,
        TopicsEquipmentSnapshotResult,
    )
    from .tiling import (
        DEFAULT_MAX_TILE_PX as TILING_DEFAULT_MAX_TILE_PX,
        DEFAULT_OVERLAP_PX as TILING_DEFAULT_OVERLAP_PX,
        tile_image,
    )
else:
    from checkpoint import RunCheckpoint, checkpoint_key
    from equipment_prompts import EquipmentPromptPackage, build_equipment_message_plan, load_equipment_prompt_package
    from equipment_response_parser import (
        EquipmentResponseParseError,
        EquipmentResponseSchemaError,
        parse_equipment_extraction_response,
    )
    from ingestion import check_image_quality
    from llm_client import (
        LLMClientError,
        OpenAICompatibleClientProtocol,
        build_llm_client_from_environment,
        configured_llm_model,
        request_equipment_extraction,
        serialize_equipment_message_plan,
    )
    from models import (
        AIReadyImageRecord,
        EquipmentExtractionCandidate,
        EquipmentExtractionResponse,
        EquipmentExtractionRunResult,
        RawDrawingEquipmentRecord,
        TopicsEquipmentSnapshotResult,
    )
    from tiling import (
        DEFAULT_MAX_TILE_PX as TILING_DEFAULT_MAX_TILE_PX,
        DEFAULT_OVERLAP_PX as TILING_DEFAULT_OVERLAP_PX,
        tile_image,
    )


RAW_DRAWING_EQUIPMENT_HEADERS = (
    "property_id",
    "floor",
    "source_file",
    "source_type",
    "raw_equipment_label",
    "raw_equipment_type",
    "evidence_detail",
    "confidence",
)

DRAWING_EQUIPMENT_SNAPSHOT_COLUMNS = (
    "snapshot_version",
    "property_name",
    "property_id",
    "floor",
    "source_filename",
    "source_relative_path",
    "source_sha256",
    "pdf_page_number",
    "prompt_version",
    "model_id",
    "raw_label",
    "llm_proposed_canonical_name",
    "equipment_type",
    "confidence",
    "run_status",
    "review_required",
    "review_reason",
)

TOPICS_EQUIPMENT_SNAPSHOT_COLUMNS = (
    "snapshot_version",
    "property_id",
    "property_name",
    "floor",
    "raw_equipment_context",
    "raw_label",
    "inferred_raw_type",
    "topic_count",
    "evidence_strength",
    "source_type",
    "review_required",
    "review_reason",
)

TOPIC_TYPE_PRECEDENCE = (
    "VAVRH",
    "EAVAV",
    "OAVAV",
    "FPTU",
    "FCU",
    "AHU",
    "VAV",
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_RAW_DRAWING_EQUIPMENT_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "snapshots"
    / "w03"
    / "equipment_from_drawings_raw.csv"
)


class RawSnapshotValidationError(ValueError):
    """Raised when a raw Week 3 snapshot fails read-only validation."""


class ExtractionArtifactError(ValueError):
    """Raised when extraction artifacts cannot be written safely."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_headers(fieldnames: Sequence[str], csv_path: Path) -> None:
    if not fieldnames:
        raise RawSnapshotValidationError(f"{csv_path}: missing CSV header row")

    expected_headers = set(RAW_DRAWING_EQUIPMENT_HEADERS)
    actual_headers = set(fieldnames)
    missing_headers = sorted(expected_headers - actual_headers)
    unexpected_headers = sorted(actual_headers - expected_headers)

    if not missing_headers and not unexpected_headers:
        return

    details = []
    if missing_headers:
        details.append(f"missing required header(s): {', '.join(missing_headers)}")
    if unexpected_headers:
        details.append(f"unexpected header(s): {', '.join(unexpected_headers)}")

    raise RawSnapshotValidationError(f"{csv_path}: invalid CSV headers; {'; '.join(details)}")


def load_raw_drawing_equipment_snapshot(
    csv_path=DEFAULT_RAW_DRAWING_EQUIPMENT_SNAPSHOT,
) -> List[RawDrawingEquipmentRecord]:
    """Load raw drawing equipment records from a snapshot without modifying it."""
    csv_path = Path(csv_path)
    records: List[RawDrawingEquipmentRecord] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        _validate_headers(reader.fieldnames, csv_path)

        for row_number, row in enumerate(reader, start=2):
            try:
                records.append(RawDrawingEquipmentRecord(**row))
            except ValidationError as exc:
                raise RawSnapshotValidationError(
                    f"{csv_path}: CSV row {row_number} failed validation: {exc}"
                ) from exc

    return records



def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepared_image_records_from_dir(input_dir, floor: str = "unknown") -> List[AIReadyImageRecord]:
    input_root = Path(input_dir).resolve()
    if not input_root.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_root}")
    if not input_root.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_root}")

    supported_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    image_paths = [path for path in input_root.rglob("*") if path.is_file() and path.suffix.lower() in supported_suffixes]
    image_paths.sort(key=lambda path: (path.relative_to(input_root).as_posix().lower(), path.relative_to(input_root).as_posix()))

    records: List[AIReadyImageRecord] = []
    for image_path in image_paths:
        relative_path = image_path.relative_to(input_root).as_posix()
        quality = check_image_quality(image_path)
        quality_flag = bool(quality.get("quality_flag", quality.get("is_quality_sufficient", False)))
        mime_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        if image_path.suffix.lower() == ".webp":
            mime_type = "image/webp"
        records.append(
            AIReadyImageRecord(
                source_filename=image_path.name,
                source_relative_path=relative_path,
                source_file_type="image",
                source_sha256=_sha256_file(image_path),
                source_local_path=str(image_path),
                raw_s3_key=None,
                prepared_image_local_path=str(image_path),
                prepared_image_s3_key=None,
                prepared_image_filename=image_path.name,
                image_format=image_path.suffix.lower().lstrip(".").upper().replace("JPG", "JPEG"),
                image_mime_type=mime_type,
                source_page_number=None,
                width=quality.get("width"),
                height=quality.get("height"),
                pixel_count=quality.get("pixel_count"),
                quality_flag=quality_flag,
                quality_status="passed" if quality_flag else "failed",
                quality_reason=quality.get("reason", "Image quality check did not provide a reason"),
                warnings=list(quality.get("warnings") or []),
                extraction_eligible=quality_flag,
                preparation_status="prepared" if quality_flag else "quality_failed",
            )
        )
    return records


def _connect_readonly_database_from_env():
    try:
        import psycopg2  # type: ignore
    except ImportError as psycopg2_error:
        try:
            import psycopg  # type: ignore
        except ImportError as psycopg_error:
            raise RuntimeError(
                "No PostgreSQL driver is installed. Install psycopg or psycopg2 to use the topics CLI."
            ) from psycopg_error
        connection = psycopg.connect(
            host=os.getenv("DB_HOST"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            port=os.getenv("DB_PORT") or 5432,
        )
        connection.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        return connection

    connection = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT") or 5432,
    )
    connection.set_session(readonly=True)
    return connection

def _base_result_fields(
    image_record: AIReadyImageRecord,
    prompt_package: EquipmentPromptPackage,
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


def _error_type(exc: Exception) -> str:
    return type(exc).__name__


def _skipped_result(
    image_record: AIReadyImageRecord,
    prompt_package: EquipmentPromptPackage,
    model: str,
    started_at: datetime,
) -> EquipmentExtractionRunResult:
    completed_at = _utc_now()
    return EquipmentExtractionRunResult(
        **_base_result_fields(image_record, prompt_package, model, started_at, completed_at),
        status="skipped",
        error_type="ImageNotEligibleForExtraction",
        error_message=image_record.quality_reason,
    )


def _result_from_raw_response(
    image_record: AIReadyImageRecord,
    prompt_package: EquipmentPromptPackage,
    model: str,
    started_at: datetime,
    raw_assistant_response: str,
) -> EquipmentExtractionRunResult:
    """Parse a raw assistant response into a result (shared by the real-time and
    Batch API paths)."""
    try:
        parsed_response = parse_equipment_extraction_response(raw_assistant_response)
    except EquipmentResponseSchemaError as exc:
        completed_at = _utc_now()
        return EquipmentExtractionRunResult(
            **_base_result_fields(image_record, prompt_package, model, started_at, completed_at),
            status="validation_failed",
            raw_assistant_response=raw_assistant_response,
            error_type=_error_type(exc),
            error_message=str(exc),
        )
    except EquipmentResponseParseError as exc:
        completed_at = _utc_now()
        return EquipmentExtractionRunResult(
            **_base_result_fields(image_record, prompt_package, model, started_at, completed_at),
            status="parse_failed",
            raw_assistant_response=raw_assistant_response,
            error_type=_error_type(exc),
            error_message=str(exc),
        )

    completed_at = _utc_now()
    return EquipmentExtractionRunResult(
        **_base_result_fields(image_record, prompt_package, model, started_at, completed_at),
        status="succeeded",
        raw_assistant_response=raw_assistant_response,
        parsed_response=parsed_response,
    )


async def extract_equipment_from_image(
    *,
    image_record: AIReadyImageRecord,
    prompt_package: EquipmentPromptPackage,
    model: str,
    client: Optional[OpenAICompatibleClientProtocol] = None,
) -> EquipmentExtractionRunResult:
    """Run one image extraction attempt and return a provenance-rich result."""
    started_at = _utc_now()
    if not image_record.extraction_eligible:
        return _skipped_result(image_record, prompt_package, model, started_at)

    message_plan = build_equipment_message_plan(
        prompt_package,
        Path(image_record.prepared_image_local_path),
    )

    try:
        raw_assistant_response = await request_equipment_extraction(
            message_plan=message_plan,
            model=model,
            client=client,
        )
    except LLMClientError as exc:
        completed_at = _utc_now()
        return EquipmentExtractionRunResult(
            **_base_result_fields(image_record, prompt_package, model, started_at, completed_at),
            status="transport_failed",
            error_type=_error_type(exc),
            error_message=str(exc),
        )

    return _result_from_raw_response(
        image_record, prompt_package, model, started_at, raw_assistant_response
    )


def _tile_has_ink(tile_path: str, *, ink_fraction_threshold: float = 0.0015) -> bool:
    """Cheap blank-tile pre-filter: True when the tile has enough dark pixels to
    plausibly hold line-work or labels. A near-white tile (blank floor area,
    margin, or title-block whitespace) is skipped before spending an LLM call.
    The threshold is deliberately conservative -- anything with visible line-work
    is kept, so the filter only removes genuinely empty regions."""
    from PIL import Image

    with Image.open(tile_path) as image:
        gray = image.convert("L")
        gray.thumbnail((160, 160))  # fast, resolution-independent ink estimate
        histogram = gray.histogram()
    dark_pixels = sum(histogram[:190])  # luminance < 190 counts as ink
    total = sum(histogram) or 1
    return (dark_pixels / total) >= ink_fraction_threshold


async def extract_equipment_from_drawing(
    *,
    image_record: AIReadyImageRecord,
    prompt_package: EquipmentPromptPackage,
    model: str,
    client: Optional[OpenAICompatibleClientProtocol] = None,
    max_tile_px: int = TILING_DEFAULT_MAX_TILE_PX,
    overlap_px: int = TILING_DEFAULT_OVERLAP_PX,
    max_concurrency: int = 4,
    prefilter: bool = True,
) -> EquipmentExtractionRunResult:
    """L4 drawing path: split a full-resolution mechanical drawing into
    overlapping tiles, run each non-blank tile through the model, and union the
    per-tile equipment into one result.

    Drawings (~12600x9000) exceed Claude's on-send resize limit, so a
    whole-image call downsamples away the fine line-work; tiling keeps each
    region full-resolution (the W4 unblock). A drawing that already fits in one
    tile is a no-op split, so every drawing routes through here uniformly."""
    started_at = _utc_now()
    if not image_record.extraction_eligible:
        return _skipped_result(image_record, prompt_package, model, started_at)

    source = Path(image_record.prepared_image_local_path)
    union: Dict[str, EquipmentExtractionCandidate] = {}
    failed_raw: List[str] = []
    transport_errors = 0
    parse_errors = 0
    any_success = False

    with tempfile.TemporaryDirectory(prefix="orient_tiles_") as tmp_dir:
        tiles = tile_image(source, tmp_dir, max_tile_px=max_tile_px, overlap_px=overlap_px)
        content_tiles = [t for t in tiles if not prefilter or _tile_has_ink(t.path)]
        tiles_run = len(content_tiles)

        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def run_tile(tile) -> tuple:
            async with semaphore:
                # Drawing tiles skip the screenshot few-shot: off-domain here and
                # costly to re-send per tile; v4's system prompt already covers
                # drawing-tile rules.
                message_plan = build_equipment_message_plan(
                    prompt_package, Path(tile.path), include_examples=False
                )
                try:
                    raw = await request_equipment_extraction(
                        message_plan=message_plan, model=model, client=client
                    )
                except LLMClientError as exc:
                    return ("transport", exc)
                return ("ok", raw)

        outcomes = (
            await asyncio.gather(*(run_tile(tile) for tile in content_tiles))
            if content_tiles
            else []
        )

    for kind, payload in outcomes:
        if kind == "transport":
            transport_errors += 1
            continue
        try:
            parsed = parse_equipment_extraction_response(payload)
        except (EquipmentResponseParseError, EquipmentResponseSchemaError):
            parse_errors += 1
            failed_raw.append(payload)
            continue
        any_success = True
        for candidate in parsed.equipment:
            # The same physical unit can surface in overlapping tiles with trivial
            # whitespace differences (e.g. "OAVAV 2-1" vs "OAVAV2-1"). Key the
            # union whitespace-insensitively so re-assembling the split drawing
            # collapses those into one, keeping the highest-confidence variant.
            # (This reassembles OUR tile split; full canonical normalization
            # remains downstream.)
            key = "".join(candidate.canonical_name.split())
            existing = union.get(key)
            if existing is None or candidate.confidence > existing.confidence:
                union[key] = candidate

    completed_at = _utc_now()
    base = _base_result_fields(image_record, prompt_package, model, started_at, completed_at)

    # Success when at least one tile parsed, or when there was simply nothing to
    # read (every tile blank) -- both yield a structurally valid, possibly-empty
    # union. Only when every content tile FAILED do we report a failure so the
    # escalation gate treats the drawing as unresolved.
    if any_success or tiles_run == 0:
        equipment = sorted(union.values(), key=lambda candidate: candidate.canonical_name)
        response = EquipmentExtractionResponse(equipment=equipment)
        return EquipmentExtractionRunResult(
            **base,
            status="succeeded",
            raw_assistant_response=response.model_dump_json(),
            parsed_response=response,
        )

    error_message = (
        f"All {tiles_run} drawing tiles failed "
        f"({transport_errors} transport, {parse_errors} parse)."
    )
    if transport_errors >= parse_errors:
        # Transport-dominant: no assistant response was received.
        return EquipmentExtractionRunResult(
            **base,
            status="transport_failed",
            error_type="LLMClientError",
            error_message=error_message,
        )
    # Parse-dominant: retain the unparsable tile responses for provenance
    # (the result schema requires it on parse failures).
    return EquipmentExtractionRunResult(
        **base,
        status="parse_failed",
        raw_assistant_response="\n---\n".join(failed_raw)[:4000] or "(no parsable tile output)",
        error_type="EquipmentResponseParseError",
        error_message=error_message,
    )


async def extract_equipment_batch(
    *,
    image_records: Sequence[AIReadyImageRecord],
    prompt_package: EquipmentPromptPackage,
    model: str,
    max_concurrency: int = 1,
    client: Optional[OpenAICompatibleClientProtocol] = None,
    on_result: Optional[Any] = None,
) -> List[EquipmentExtractionRunResult]:
    """Run bounded-concurrency extraction and preserve input order.

    ``on_result(record, result)`` is invoked as each image completes — the
    checkpoint hook, so an interrupted batch preserves every finished image."""
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_one(record: AIReadyImageRecord) -> EquipmentExtractionRunResult:
        async with semaphore:
            result = await extract_equipment_from_image(
                image_record=record,
                prompt_package=prompt_package,
                model=model,
                client=client,
            )
        if on_result is not None:
            on_result(record, result)
        return result

    tasks = [asyncio.create_task(run_one(record)) for record in image_records]
    if not tasks:
        return []
    return list(await asyncio.gather(*tasks))


def _batch_failed_result(
    image_record: AIReadyImageRecord,
    prompt_package: EquipmentPromptPackage,
    model: str,
    started_at: datetime,
    item: Any,
) -> EquipmentExtractionRunResult:
    completed_at = _utc_now()
    return EquipmentExtractionRunResult(
        **_base_result_fields(image_record, prompt_package, model, started_at, completed_at),
        status="transport_failed",
        error_type=f"batch_{item.status}",
        error_message=item.error_message or f"batch item {item.status}",
    )


def _batch_missing_result(
    image_record: AIReadyImageRecord,
    prompt_package: EquipmentPromptPackage,
    model: str,
    started_at: datetime,
    custom_id: str,
) -> EquipmentExtractionRunResult:
    completed_at = _utc_now()
    return EquipmentExtractionRunResult(
        **_base_result_fields(image_record, prompt_package, model, started_at, completed_at),
        status="transport_failed",
        error_type="batch_missing_result",
        error_message=f"No batch result returned for custom_id {custom_id}",
    )


def extract_equipment_batch_via_batch_api(
    *,
    image_records: Sequence[AIReadyImageRecord],
    prompt_package: EquipmentPromptPackage,
    model: str,
    client: Optional[OpenAICompatibleClientProtocol] = None,
    poll_interval_seconds: float = 30.0,
    timeout_seconds: float = 86400.0,
    on_poll: Optional[Any] = None,
    cost_log_path: Optional[Any] = None,
) -> List[EquipmentExtractionRunResult]:
    """Run equipment extraction through the Anthropic Message Batches API.

    Submits one batch of all extraction-eligible images (~50% cheaper than
    real-time, the brief's mandated production default), polls until the batch
    ends, and maps results back to EquipmentExtractionRunResult preserving input
    order. Ineligible images are skipped without a request, exactly as in the
    real-time path. Requires the Anthropic client (LLM_PROVIDER=anthropic).
    """
    if client is None:
        client = build_llm_client_from_environment()
    run_batch = getattr(client, "run_message_batch", None)
    build_request = getattr(client, "build_batch_request", None)
    if not callable(run_batch) or not callable(build_request):
        raise LLMClientError(
            "Batch extraction requires the Anthropic client; set LLM_PROVIDER=anthropic."
        )

    started_at = _utc_now()
    requests: List[Mapping[str, Any]] = []
    plan: List[tuple] = []  # (record, custom_id or None), preserving input order
    for index, record in enumerate(image_records):
        if not record.extraction_eligible:
            plan.append((record, None))
            continue
        custom_id = f"img{index}"
        message_plan = build_equipment_message_plan(
            prompt_package, Path(record.prepared_image_local_path)
        )
        messages = serialize_equipment_message_plan(message_plan)
        requests.append(build_request(custom_id=custom_id, model=model, messages=messages))
        plan.append((record, custom_id))

    batch_results: Dict[str, Any] = {}
    if requests:
        batch_results = run_batch(
            requests,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
            on_poll=on_poll,
        )

    if __package__:
        from .cost import record_usage
    else:
        from cost import record_usage

    for item in batch_results.values():
        record_usage(model, getattr(item, "usage", None), batch=True)

    if cost_log_path and batch_results:
        if __package__:
            from .cost import summarize_batch_results, write_cost_log
        else:
            from cost import summarize_batch_results, write_cost_log

        write_cost_log(
            cost_log_path, summarize_batch_results(batch_results, model, batch=True)
        )

    results: List[EquipmentExtractionRunResult] = []
    for record, custom_id in plan:
        if custom_id is None:
            results.append(_skipped_result(record, prompt_package, model, started_at))
            continue
        item = batch_results.get(custom_id)
        if item is None:
            results.append(_batch_missing_result(record, prompt_package, model, started_at, custom_id))
        elif item.status == "succeeded":
            results.append(
                _result_from_raw_response(record, prompt_package, model, started_at, item.content or "")
            )
        else:
            results.append(_batch_failed_result(record, prompt_package, model, started_at, item))
    return results


def _ensure_output_path_available(output_path: Path, overwrite: bool) -> None:
    if output_path.exists() and not overwrite:
        raise ExtractionArtifactError(f"Output path already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)


def write_extraction_run_jsonl(
    results: Sequence[EquipmentExtractionRunResult],
    output_path,
    overwrite: bool = False,
) -> Path:
    """Write complete extraction-run evidence as deterministic JSONL."""
    output_path = Path(output_path)
    _ensure_output_path_available(output_path, overwrite)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        for result in results:
            output_file.write(json.dumps(result.model_dump(mode="json"), sort_keys=True))
            output_file.write("\n")
    return output_path


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def write_drawing_equipment_snapshot(
    results: Sequence[EquipmentExtractionRunResult],
    output_path,
    *,
    snapshot_version: str,
    property_name: str,
    property_id: str,
    floor: str = "unknown",
    low_confidence_threshold: float = 0.75,
    overwrite: bool = False,
) -> Path:
    """Flatten successful extraction candidates into a W3 drawing snapshot CSV."""
    output_path = Path(output_path)
    _ensure_output_path_available(output_path, overwrite)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=DRAWING_EQUIPMENT_SNAPSHOT_COLUMNS)
        writer.writeheader()
        for result in results:
            if result.status != "succeeded" or result.parsed_response is None:
                continue
            for candidate in result.parsed_response.equipment:
                review_required = candidate.confidence < low_confidence_threshold
                writer.writerow(
                    {
                        "snapshot_version": snapshot_version,
                        "property_name": property_name,
                        "property_id": property_id,
                        "floor": floor,
                        "source_filename": result.source_filename,
                        "source_relative_path": result.source_relative_path,
                        "source_sha256": result.source_sha256,
                        "pdf_page_number": result.pdf_page_number or "",
                        "prompt_version": result.prompt_version,
                        "model_id": result.model_id,
                        "raw_label": candidate.raw_label,
                        "llm_proposed_canonical_name": candidate.canonical_name,
                        "equipment_type": candidate.equipment_type.value,
                        "confidence": candidate.confidence,
                        "run_status": result.status,
                        "review_required": _bool_text(review_required),
                        "review_reason": "low_confidence" if review_required else "",
                    }
                )
    return output_path


def _extract_topic_path(row: Any) -> str:
    if isinstance(row, Mapping):
        value = row.get("topic_name") or row.get("name") or row.get("path")
    else:
        value = row[0]
    if not isinstance(value, str):
        raise ValueError("topic query must return topic path strings")
    return value


def _fetch_topic_paths(connection: Any, property_id: str, floor_prefix: str) -> List[str]:
    query = (
        "SELECT topic_name FROM public.topics "
        "WHERE property_id = %s AND topic_name LIKE %s "
        "ORDER BY topic_name"
    )
    params = (str(property_id), f"{floor_prefix}/%")
    cursor = connection.cursor()
    try:
        cursor.execute(query, params)
        return [_extract_topic_path(row) for row in cursor.fetchall()]
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()


def _strip_device_prefix(raw_context: str) -> str:
    return re.sub(r"^DEV\d+_", "", raw_context)


def _classify_topic_equipment_type(raw_label: str) -> str:
    upper_label = raw_label.upper()
    for equipment_type in TOPIC_TYPE_PRECEDENCE:
        if equipment_type in upper_label:
            return equipment_type
    return "UNRESOLVED"


def _topic_context(topic_path: str, floor_prefix: str) -> Optional[str]:
    parts = topic_path.split("/")
    if len(parts) < 3 or parts[0] != floor_prefix or not parts[1]:
        return None
    return parts[1]


def export_topics_equipment_snapshot(
    *,
    connection: Any,
    property_id,
    property_name: str,
    floor_prefix: str,
    output_path,
    snapshot_version: str,
    overwrite: bool = False,
    expected_distinct_context_count: Optional[int] = None,
) -> TopicsEquipmentSnapshotResult:
    """Read topic names and export a deterministic Floor 02 equipment snapshot."""
    output_path = Path(output_path)
    _ensure_output_path_available(output_path, overwrite)
    topic_paths = _fetch_topic_paths(connection, str(property_id), floor_prefix)

    grouped: Dict[str, List[str]] = {}
    for topic_path in topic_paths:
        context = _topic_context(topic_path, floor_prefix)
        if context is None:
            continue
        grouped.setdefault(context, []).append(topic_path)

    if expected_distinct_context_count is not None and len(grouped) != expected_distinct_context_count:
        raise ExtractionArtifactError(
            f"Expected {expected_distinct_context_count} topic contexts, found {len(grouped)}"
        )

    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=TOPICS_EQUIPMENT_SNAPSHOT_COLUMNS)
        writer.writeheader()
        for context in sorted(grouped, key=lambda value: (value.lower(), value)):
            raw_label = _strip_device_prefix(context)
            topic_count = len(grouped[context])
            weak_evidence = topic_count == 1
            writer.writerow(
                {
                    "snapshot_version": snapshot_version,
                    "property_id": str(property_id),
                    "property_name": property_name,
                    "floor": floor_prefix,
                    "raw_equipment_context": context,
                    "raw_label": raw_label,
                    "inferred_raw_type": _classify_topic_equipment_type(raw_label),
                    "topic_count": topic_count,
                    "evidence_strength": "weak_topic_evidence" if weak_evidence else "multiple_point_evidence",
                    "source_type": "topics",
                    "review_required": _bool_text(weak_evidence),
                    "review_reason": "weak_topic_evidence" if weak_evidence else "",
                }
            )

    return TopicsEquipmentSnapshotResult(
        output_path=str(output_path),
        snapshot_version=snapshot_version,
        property_id=str(property_id),
        property_name=property_name,
        floor=floor_prefix,
        row_count=len(grouped),
        distinct_context_count=len(grouped),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project ORIENT W3 equipment extraction utilities."
    )
    subparsers = parser.add_subparsers(dest="command")

    extract_parser = subparsers.add_parser("extract", help="Run an opt-in W3 extraction pilot or batch.")
    extract_parser.add_argument("--input-dir", required=True)
    extract_parser.add_argument(
        "--prompt-root",
        default=str(PROJECT_ROOT / "prompts" / "equipment_extraction"),
    )
    extract_parser.add_argument("--example-image-dir", required=True)
    extract_parser.add_argument(
        "--type-context",
        default=str(PROJECT_ROOT / "prompts" / "equipment_type_context.md"),
        help="Simplified equipment-type context appended to the system prompt "
        "(generate with: py -m pipeline.generate_equipment_type_context --simple).",
    )
    extract_parser.add_argument(
        "--no-type-context",
        action="store_true",
        help="Run without the simplified equipment-type context.",
    )
    extract_parser.add_argument("--property-id", default="unknown")
    extract_parser.add_argument("--property-name", default="unknown")
    extract_parser.add_argument("--prompt-version", default="equipment_extraction_v4")
    extract_parser.add_argument("--snapshot-version", default="w03")
    extract_parser.add_argument("--floor", default="Floor_02")
    extract_parser.add_argument("--output-dir", default="data/extractions/w03")
    extract_parser.add_argument("--snapshot-path", default="data/snapshots/w03/drawing_equipment_floor_02.csv")
    extract_parser.add_argument("--model", default=None)
    extract_parser.add_argument("--run-live", action="store_true")
    extract_parser.add_argument("--max-concurrency", type=int, default=1)
    extract_parser.add_argument(
        "--batch",
        action="store_true",
        help="Use the Anthropic Message Batches API (~50%% cheaper; requires LLM_PROVIDER=anthropic).",
    )
    extract_parser.add_argument("--poll-interval", type=float, default=30.0)
    extract_parser.add_argument(
        "--cost-log",
        default=None,
        help="With --batch: write a token-usage + estimated-cost summary JSON to this path.",
    )
    extract_parser.add_argument("--raw-runs-path", default=None)
    extract_parser.add_argument(
        "--checkpoint-path",
        default=None,
        help="Run-checkpoint JSONL (default: <output-dir>/extraction_checkpoint.jsonl). "
        "Images already succeeded for this prompt+model are reused, not re-sent.",
    )
    extract_parser.add_argument(
        "--metrics-path",
        default=None,
        help="Run-metrics JSON path (default: <output-dir>/run_metrics.json).",
    )
    extract_parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Disable run checkpointing (every image is re-sent).",
    )
    extract_parser.add_argument("--overwrite", action="store_true")

    topics_parser = subparsers.add_parser("topics", help="Export the read-only topics-derived snapshot.")
    topics_parser.add_argument("--property-id", required=True)
    topics_parser.add_argument("--property-name", required=True)
    topics_parser.add_argument("--floor-prefix", default="Floor_02")
    topics_parser.add_argument("--output-path", required=True)
    topics_parser.add_argument("--snapshot-version", default="w03")
    topics_parser.add_argument("--expected-distinct-contexts", type=int, default=37)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "extract":
        if not args.run_live:
            print("Extraction CLI is dry by default. Re-run with --run-live to call the configured endpoint.")
            return 1
        try:
            if __package__:
                from .cost import GLOBAL_USAGE, write_run_metrics
            else:
                from cost import GLOBAL_USAGE, write_run_metrics

            GLOBAL_USAGE.reset()
            run_started_at = _utc_now()
            model = args.model or configured_llm_model()
            image_records = _prepared_image_records_from_dir(args.input_dir, floor=args.floor)
            type_context_path = None if args.no_type_context else Path(args.type_context)
            prompt_package = load_equipment_prompt_package(
                args.prompt_version,
                Path(args.prompt_root),
                Path(args.example_image_dir),
                type_context_path=type_context_path,
            )

            # Run checkpoint: reuse images already succeeded for this
            # prompt+model so a crash/restart only re-sends incomplete ones.
            checkpoint = None
            reused: Dict[int, EquipmentExtractionRunResult] = {}
            pending: List[tuple] = list(enumerate(image_records))
            if not args.no_checkpoint:
                checkpoint_path = (
                    Path(args.checkpoint_path)
                    if args.checkpoint_path
                    else Path(args.output_dir) / "extraction_checkpoint.jsonl"
                )
                checkpoint = RunCheckpoint(checkpoint_path)
                pending = []
                for index, record in enumerate(image_records):
                    stored = checkpoint.succeeded_result(
                        checkpoint_key(record, args.prompt_version, model)
                    )
                    if stored is not None:
                        reused[index] = stored
                    else:
                        pending.append((index, record))
                print(
                    f"Checkpoint {checkpoint_path}: reusing {len(reused)} succeeded "
                    f"image(s), running {len(pending)}."
                )

            pending_records = [record for _, record in pending]
            if args.batch:
                run_results = extract_equipment_batch_via_batch_api(
                    image_records=pending_records,
                    prompt_package=prompt_package,
                    model=model,
                    poll_interval_seconds=args.poll_interval,
                    cost_log_path=args.cost_log,
                    on_poll=lambda batch_id, status: print(f"Batch {batch_id}: {status}"),
                )
                if checkpoint is not None:
                    for record, result in zip(pending_records, run_results):
                        checkpoint.record(
                            checkpoint_key(record, args.prompt_version, model), result
                        )
            else:
                on_result = None
                if checkpoint is not None:
                    def on_result(record, result, _cp=checkpoint):
                        _cp.record(checkpoint_key(record, args.prompt_version, model), result)

                run_results = asyncio.run(
                    extract_equipment_batch(
                        image_records=pending_records,
                        prompt_package=prompt_package,
                        model=model,
                        max_concurrency=args.max_concurrency,
                        on_result=on_result,
                    )
                )

            merged: List[Optional[EquipmentExtractionRunResult]] = [None] * len(image_records)
            for index, stored in reused.items():
                merged[index] = stored
            for (index, _), result in zip(pending, run_results):
                merged[index] = result
            results = [result for result in merged if result is not None]

            # A resumed run legitimately rewrites its own artifacts.
            effective_overwrite = args.overwrite or bool(reused)
            raw_runs_path = Path(args.raw_runs_path) if args.raw_runs_path else Path(args.output_dir) / "equipment_extraction_runs.jsonl"
            write_extraction_run_jsonl(results, raw_runs_path, overwrite=effective_overwrite)
            write_drawing_equipment_snapshot(
                results,
                args.snapshot_path,
                snapshot_version=args.snapshot_version,
                property_name=args.property_name,
                property_id=args.property_id,
                floor=args.floor,
                overwrite=effective_overwrite,
            )

            run_finished_at = _utc_now()
            status_counts: Dict[str, int] = {}
            for result in results:
                status_counts[result.status] = status_counts.get(result.status, 0) + 1
            candidates = [
                candidate
                for result in results
                if result.parsed_response is not None
                for candidate in result.parsed_response.equipment
            ]
            confident = sum(1 for candidate in candidates if candidate.confidence >= 0.75)
            metrics_path = (
                Path(args.metrics_path)
                if args.metrics_path
                else Path(args.output_dir) / "run_metrics.json"
            )
            write_run_metrics(
                metrics_path,
                run={
                    "command": "extract",
                    "model": model,
                    "prompt_version": args.prompt_version,
                    "floor": args.floor,
                    "batch_mode": bool(args.batch),
                    "started_at": run_started_at.isoformat(),
                    "finished_at": run_finished_at.isoformat(),
                    "wall_seconds": round(
                        (run_finished_at - run_started_at).total_seconds(), 3
                    ),
                },
                counts={
                    "images_total": len(image_records),
                    "images_reused_from_checkpoint": len(reused),
                    "images_run": len(pending),
                    "image_status": status_counts,
                    "equipment_candidates_total": len(candidates),
                    "equipment_candidates_confident": confident,
                    "equipment_candidates_review_required": len(candidates) - confident,
                },
            )
        except Exception as exc:
            print(f"Extraction failed: {exc}")
            return 1
        print(f"Extraction results written: {raw_runs_path}")
        print(f"Drawing snapshot written: {args.snapshot_path}")
        print(f"Run metrics written: {metrics_path}")
        return 0
    if args.command == "topics":
        connection = None
        try:
            connection = _connect_readonly_database_from_env()
            result = export_topics_equipment_snapshot(
                connection=connection,
                property_id=args.property_id,
                property_name=args.property_name,
                floor_prefix=args.floor_prefix,
                output_path=args.output_path,
                snapshot_version=args.snapshot_version,
                expected_distinct_context_count=args.expected_distinct_contexts,
            )
        except Exception as exc:
            print(f"Topics snapshot export failed: {exc}")
            return 1
        finally:
            if connection is not None:
                close = getattr(connection, "close", None)
                if callable(close):
                    close()
        print(f"Topics snapshot written: {result.output_path}")
        print(f"Distinct contexts: {result.distinct_context_count}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
