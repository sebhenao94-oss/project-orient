import argparse
import os
from pathlib import Path

if __package__:
    from .ingestion import IngestionConfigError, prepare_sources_for_extraction
else:
    from ingestion import IngestionConfigError, prepare_sources_for_extraction


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_DIR = PROJECT_ROOT / "tmp" / "orient"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Project ORIENT Stage 1 local ingestion preparation flow."
    )
    parser.add_argument(
        "source_dir",
        nargs="?",
        help="Local folder containing PNG, JPG, JPEG, PDF, and DWG source files.",
    )
    parser.add_argument(
        "--work-dir",
        default=str(DEFAULT_WORK_DIR),
        help="Local working folder for generated PDF page images.",
    )
    parser.add_argument(
        "--raw-prefix",
        default=None,
        help="S3 raw prefix for planning or uploading original source files.",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Perform raw S3 uploads. Without this flag, the command runs as a dry run.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow raw S3 uploads to overwrite existing objects when --upload is used.",
    )
    parser.add_argument(
        "--pdf-dpi",
        type=int,
        default=300,
        help="PDF conversion DPI. Must be at least 300.",
    )
    parser.add_argument(
        "--poppler-path",
        default=None,
        help="Optional Poppler bin path for pdf2image on Windows.",
    )
    return parser


def _print_result_summary(result, dry_run: bool) -> None:
    print("Stage 1 ingestion preparation complete.")
    print(f"Dry run: {'yes' if dry_run else 'no'}")
    print(f"Source manifest records: {len(result.source_manifest_records)}")
    print(f"Raw upload results: {len(result.raw_upload_results)}")
    print(f"Prepared image records: {len(result.prepared_image_records)}")
    print(f"Deferred raw-only sources: {len(result.deferred_source_records)}")
    print(f"Failures: {len(result.failures)}")

    for raw_result in result.raw_upload_results:
        print(
            f"Raw {raw_result.upload_status}: {raw_result.relative_path} -> "
            f"{raw_result.s3_key or 'no S3 key'}"
        )

    for prepared_record in result.prepared_image_records:
        print(
            f"Prepared {prepared_record.preparation_status}: "
            f"{prepared_record.prepared_image_local_path} "
            f"eligible={prepared_record.extraction_eligible} "
            f"quality={prepared_record.quality_status}"
        )

    for deferred_record in result.deferred_source_records:
        print(f"Deferred raw-only source: {deferred_record.relative_path} ({deferred_record.file_type})")

    for failure in result.failures:
        print(f"Failure: {failure}")


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    source_dir = args.source_dir or os.getenv("LOCAL_SOURCE_DIR")
    if not source_dir:
        print(
            "Provide a local source directory argument or set LOCAL_SOURCE_DIR. "
            "Example: py -m pipeline.run C:\\path\\to\\Screenshots --raw-prefix Team-4/raw/"
        )
        return 1

    dry_run = not args.upload
    try:
        result = prepare_sources_for_extraction(
            source_dir,
            work_dir=args.work_dir,
            raw_prefix=args.raw_prefix,
            dry_run=dry_run,
            overwrite=args.overwrite,
            pdf_dpi=args.pdf_dpi,
            poppler_path=args.poppler_path,
        )
    except (
        FileNotFoundError,
        NotADirectoryError,
        IngestionConfigError,
        IsADirectoryError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"Stage 1 ingestion failed: {exc}")
        return 1

    _print_result_summary(result, dry_run=dry_run)
    return 1 if result.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())