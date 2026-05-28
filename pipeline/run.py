import json
from datetime import datetime, timezone
from pathlib import Path

from ingestion import check_image_quality, convert_pdf_to_images, detect_file_type
from s3_utils import (
    MissingEnvironmentVariableError,
    download_file,
    get_output_prefix,
    list_input_files,
    upload_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = PROJECT_ROOT / "tmp" / "orient"
PROCESSED_DIR = TEMP_DIR / "processed"
MANIFEST_PATH = TEMP_DIR / "manifest.json"


def build_output_key(output_prefix: str, *parts: str) -> str:
    clean_parts = [part.strip("/") for part in parts if part.strip("/")]
    return "/".join([output_prefix] + clean_parts)


def print_image_quality(image_path: Path) -> dict:
    quality = check_image_quality(image_path)
    print(f"Image dimensions: {quality['width']}x{quality['height']}")
    if quality["is_quality_sufficient"]:
        print("Image quality check: passed")
    else:
        print("Image quality check: failed")
    print(f"Reason: {quality['reason']}")
    return quality


def upload_processed_file(local_path: Path, s3_key: str, success_message: str) -> bool:
    try:
        uploaded_key = upload_file(local_path, s3_key)
    except RuntimeError as exc:
        print(f"Upload failed: {exc}")
        return False

    print(f"{success_message}: {uploaded_key}")
    return True


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def manifest_filename_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_manifest(records: list, manifest_path: Path) -> Path:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as manifest_file:
        json.dump(records, manifest_file, indent=2)
        manifest_file.write("\n")
    return manifest_path


def main() -> int:
    try:
        files = list_input_files()
        output_prefix = get_output_prefix()
    except MissingEnvironmentVariableError as exc:
        print(f"Configuration error: {exc}")
        return 1
    except RuntimeError as exc:
        print(f"S3 listing failed: {exc}")
        return 1

    print("Files found:")
    for file_key in files:
        print(file_key)

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    manifest_records = []

    if not files:
        print("No files found in the configured S3 prefix.")

    print("\nDownloaded files:")
    for file_key in files:
        local_path = TEMP_DIR / Path(file_key).name
        try:
            downloaded_path = download_file(file_key, local_path)
        except RuntimeError as exc:
            print(f"Download failed: {exc}")
            return 1

        file_type = detect_file_type(downloaded_path)
        manifest_record = {
            "source_s3_key": file_key,
            "local_path": str(downloaded_path),
            "file_type": file_type,
            "processed_status": "processed",
            "quality_status": "not_applicable",
            "quality_reason": "",
            "output_s3_keys": [],
            "timestamp_utc": utc_timestamp(),
        }

        if file_type == "unsupported":
            print(f"Skipping unsupported file: {downloaded_path}")
            manifest_record["processed_status"] = "skipped"
            manifest_record["quality_reason"] = "File type is unsupported"
            manifest_records.append(manifest_record)
            continue

        print(f"Ready for processing: {downloaded_path} ({file_type})")
        if file_type == "image":
            quality = print_image_quality(downloaded_path)
            manifest_record["quality_status"] = (
                "passed" if quality["is_quality_sufficient"] else "failed"
            )
            manifest_record["quality_reason"] = quality["reason"]
            if quality["is_quality_sufficient"]:
                s3_key = build_output_key(
                    output_prefix,
                    "processed",
                    "images",
                    downloaded_path.name,
                )
                success_message = "Uploaded passed-quality image to S3"
            else:
                s3_key = build_output_key(
                    output_prefix,
                    "review",
                    "failed_quality",
                    "images",
                    downloaded_path.name,
                )
                success_message = "Uploaded failed-quality image to review queue"

            if not upload_processed_file(downloaded_path, s3_key, success_message):
                return 1
            manifest_record["output_s3_keys"].append(s3_key)
        elif file_type == "pdf":
            try:
                generated_images = convert_pdf_to_images(downloaded_path, PROCESSED_DIR)
            except RuntimeError as exc:
                print(f"PDF conversion failed: {exc}")
                return 1

            print("Generated PDF page images:")
            page_quality_results = []
            for image_path in generated_images:
                print(image_path)
                quality = print_image_quality(image_path)
                page_quality_results.append((image_path, quality))
                if quality["is_quality_sufficient"]:
                    s3_key = build_output_key(
                        output_prefix,
                        "processed",
                        downloaded_path.stem,
                        image_path.name,
                    )
                    success_message = "Uploaded passed-quality image to S3"
                else:
                    s3_key = build_output_key(
                        output_prefix,
                        "review",
                        "failed_quality",
                        downloaded_path.stem,
                        image_path.name,
                    )
                    success_message = "Uploaded failed-quality image to review queue"

                if not upload_processed_file(image_path, s3_key, success_message):
                    return 1
                manifest_record["output_s3_keys"].append(s3_key)

            failed_pages = [
                f"{image_path.name}: {quality['reason']}"
                for image_path, quality in page_quality_results
                if not quality["is_quality_sufficient"]
            ]
            if failed_pages:
                manifest_record["quality_status"] = "failed"
                manifest_record["quality_reason"] = "; ".join(failed_pages)
            else:
                manifest_record["quality_status"] = "passed"
                manifest_record["quality_reason"] = (
                    "All generated page images meet minimum resolution threshold"
                )
        elif file_type == "dwg":
            print("DWG file detected; no conversion step is implemented in this smoke test.")
            manifest_record["quality_reason"] = "Quality check is not applicable for DWG files"

        manifest_records.append(manifest_record)

    local_manifest_path = write_manifest(manifest_records, MANIFEST_PATH)
    manifest_s3_key = build_output_key(
        output_prefix,
        "manifests",
        f"manifest_{manifest_filename_timestamp()}.json",
    )
    if not upload_processed_file(
        local_manifest_path,
        manifest_s3_key,
        "Uploaded manifest to S3",
    ):
        return 1

    print(f"Local manifest path: {local_manifest_path}")
    print(f"Uploaded S3 manifest path: {manifest_s3_key}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
