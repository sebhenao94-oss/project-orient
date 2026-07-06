"""Run one live vision-model extraction and print the parsed output.

Example:
python -m pipeline.test_vision_model_output \
  --image path/to/AHU_02A.png \
  --example-image-dir path/to/few_shot_images \
  --source-document-type bms_screenshot \
  --image-complexity simple
"""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .config import PROJECT_ROOT
    from .equipment_prompts import load_equipment_prompt_package
    from .escalation import evaluate_equipment_candidate, evaluate_extraction_run
    from .extraction import extract_equipment_from_image
    from .ingestion import classify_image_complexity
    from .llm_client import configured_llm_model
    from .models import AIReadyImageRecord
else:
    from config import PROJECT_ROOT
    from equipment_prompts import load_equipment_prompt_package
    from escalation import evaluate_equipment_candidate, evaluate_extraction_run
    from extraction import extract_equipment_from_image
    from ingestion import classify_image_complexity
    from llm_client import configured_llm_model
    from models import AIReadyImageRecord


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _image_record(args) -> AIReadyImageRecord:
    image_path = Path(args.image).resolve()
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    if args.image_complexity == "auto":
        image_complexity, image_complexity_reason = classify_image_complexity(
            {
                "width": args.width,
                "height": args.height,
                "pixel_count": args.width * args.height if args.width and args.height else None,
            }
        )
    else:
        image_complexity = args.image_complexity
        image_complexity_reason = "provided by CLI"

    extraction_route = {
        "bms_screenshot": "standard_screenshot_extraction",
        "mechanical_drawing": "mechanical_drawing_second_pass",
        "unknown": "needs_source_type_review",
    }[args.source_document_type]

    return AIReadyImageRecord(
        source_filename=image_path.name,
        source_relative_path=image_path.name,
        source_file_type="image",
        source_sha256=_sha256_file(image_path),
        source_local_path=str(image_path),
        raw_s3_key=None,
        prepared_image_local_path=str(image_path),
        prepared_image_s3_key=None,
        prepared_image_filename=image_path.name,
        image_format=image_path.suffix.lstrip(".").upper() or None,
        image_mime_type=_mime_type(image_path),
        source_document_type=args.source_document_type,
        source_document_reason="provided by CLI",
        image_complexity=image_complexity,
        image_complexity_reason=image_complexity_reason,
        extraction_route=extraction_route,
        source_page_number=args.page,
        width=args.width,
        height=args.height,
        pixel_count=args.width * args.height if args.width and args.height else None,
        quality_flag=True,
        quality_status="passed",
        quality_reason="manual smoke-test input",
        warnings=[],
        extraction_eligible=True,
        preparation_status="prepared",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test one vision-model equipment extraction.")
    parser.add_argument("--image", required=True, help="Target image to send to the vision model.")
    parser.add_argument(
        "--example-image-dir",
        required=True,
        help="Directory containing the few-shot image files referenced by the v3 manifest.",
    )
    parser.add_argument(
        "--prompt-root",
        default=str(PROJECT_ROOT / "prompts" / "equipment_extraction"),
    )
    parser.add_argument("--prompt-version", default="equipment_extraction_v3")
    parser.add_argument("--model", default=None, help="Override LLM_MODEL from .env.")
    parser.add_argument(
        "--source-document-type",
        choices=["bms_screenshot", "mechanical_drawing", "unknown"],
        default="bms_screenshot",
    )
    parser.add_argument(
        "--image-complexity",
        choices=["simple", "moderate", "complex", "unknown", "auto"],
        default="unknown",
    )
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--page", type=int, default=None)
    parser.add_argument("--output-json", default=None, help="Optional path for full run result JSON.")
    return parser


async def _run(args) -> int:
    prompt_package = load_equipment_prompt_package(
        args.prompt_version,
        Path(args.prompt_root),
        Path(args.example_image_dir),
    )
    model = args.model or configured_llm_model()
    result = await extract_equipment_from_image(
        image_record=_image_record(args),
        prompt_package=prompt_package,
        model=model,
    )

    print("\n=== status ===")
    print(result.status)
    if result.error_type or result.error_message:
        print(f"{result.error_type}: {result.error_message}")

    print("\n=== raw assistant response ===")
    print(result.raw_assistant_response or "")

    print("\n=== parsed response ===")
    if result.parsed_response is None:
        print("null")
    else:
        print(json.dumps(result.parsed_response.model_dump(mode="json"), indent=2))

    print("\n=== escalation ===")
    run_decision = evaluate_extraction_run(result)
    if run_decision is not None:
        print(
            json.dumps(
                {
                    "review_required": run_decision.review_required,
                    "review_reason": run_decision.review_reason_text,
                    "escalation_action": run_decision.next_action,
                    "escalation_model": run_decision.model_for_action(model),
                },
                indent=2,
            )
        )
    elif result.parsed_response is None:
        print("null")
    else:
        decisions = [
            {
                "raw_label": candidate.raw_label,
                "canonical_name": candidate.canonical_name,
                "review_required": decision.review_required,
                "review_reason": decision.review_reason_text,
                "escalation_action": decision.next_action,
                "escalation_model": decision.model_for_action(model),
            }
            for candidate in result.parsed_response.equipment
            for decision in [evaluate_equipment_candidate(result, candidate)]
        ]
        print(json.dumps(decisions, indent=2))

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"\nWrote full run result: {output_path}")

    return 0 if result.status == "succeeded" else 1


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
