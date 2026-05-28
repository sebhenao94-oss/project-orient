import os
from pathlib import Path
from typing import List

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from pdf2image import convert_from_path
from pdf2image.exceptions import (
    PDFInfoNotInstalledError,
    PDFPageCountError,
    PDFSyntaxError,
)
from PIL import Image

from models import SourceFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


MIN_IMAGE_WIDTH = 1000
MIN_IMAGE_HEIGHT = 1000
SOURCE_SUBFOLDERS = ("screenshots/", "drawings/", "bms_exports/")
DEFAULT_DOWNLOAD_DIR = Path("/tmp/orient")


class IngestionConfigError(RuntimeError):
    """Raised when ingestion configuration is missing."""


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise IngestionConfigError(f"Missing required environment variable: {name}")
    return value


def _normalize_prefix(prefix: str) -> str:
    prefix = prefix.strip("/")
    return f"{prefix}/" if prefix else ""


def _join_s3_prefix(base_prefix: str, subfolder: str) -> str:
    return f"{_normalize_prefix(base_prefix)}{subfolder.strip('/')}/"


def _is_output_key(s3_key: str, output_prefix: str) -> bool:
    output_prefix = output_prefix.strip("/")
    return bool(output_prefix) and (
        s3_key == output_prefix or s3_key.startswith(f"{output_prefix}/")
    )


def _local_path_for_s3_key(s3_key: str, input_prefix: str, download_dir: Path) -> Path:
    normalized_input_prefix = _normalize_prefix(input_prefix)
    if normalized_input_prefix and s3_key.startswith(normalized_input_prefix):
        relative_key = s3_key[len(normalized_input_prefix):]
    else:
        relative_key = Path(s3_key).name

    return download_dir.joinpath(*relative_key.split("/"))


def detect_file_type(file_path) -> str:
    """Classify a local file path by extension for the ingestion smoke test."""
    extension = Path(file_path).suffix.lower()

    if extension in {".png", ".jpg", ".jpeg"}:
        return "image"
    if extension == ".pdf":
        return "pdf"
    if extension == ".dwg":
        return "dwg"

    return "unsupported"


def check_image_quality(file_path) -> dict:
    """Inspect image dimensions and flag files below the smoke-test threshold."""
    with Image.open(file_path) as image:
        width, height = image.size

    is_quality_sufficient = (
        width >= MIN_IMAGE_WIDTH and height >= MIN_IMAGE_HEIGHT
    )

    if is_quality_sufficient:
        reason = "Image meets minimum resolution threshold"
    else:
        reason = (
            f"Image resolution {width}x{height} is below minimum threshold "
            f"{MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT}"
        )

    return {
        "width": width,
        "height": height,
        "is_quality_sufficient": is_quality_sufficient,
        "reason": reason,
    }


def convert_pdf_to_images(pdf_path, output_dir, dpi=300) -> List[Path]:
    """Convert each PDF page to a PNG image and return generated paths."""
    pdf_path = Path(pdf_path)
    target_dir = Path(output_dir) / pdf_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        pages = convert_from_path(str(pdf_path), dpi=dpi)
    except PDFInfoNotInstalledError as exc:
        raise RuntimeError(
            "Poppler is required for PDF conversion but was not found. "
            "Install Poppler for Windows and make sure its bin folder is on PATH."
        ) from exc
    except PDFPageCountError as exc:
        raise RuntimeError(f"Unable to read page count from PDF: {pdf_path}") from exc
    except PDFSyntaxError as exc:
        raise RuntimeError(f"PDF appears to be invalid or unreadable: {pdf_path}") from exc

    generated_paths: List[Path] = []
    for page_number, page in enumerate(pages, start=1):
        image_path = target_dir / f"page_{page_number:03}.png"
        page.save(image_path, "PNG")
        generated_paths.append(image_path)

    return generated_paths


def list_source_s3_keys(s3_client=None) -> List[str]:
    """List source files from the expected ORIENT input subfolders."""
    bucket = _required_env("S3_BUCKET")
    input_prefix = _required_env("S3_INPUT_PREFIX")
    output_prefix = _required_env("S3_OUTPUT_PREFIX")
    client = s3_client or boto3.client("s3")

    keys: List[str] = []
    try:
        for subfolder in SOURCE_SUBFOLDERS:
            prefix = _join_s3_prefix(input_prefix, subfolder)
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/") or _is_output_key(key, output_prefix):
                        continue
                    keys.append(key)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"Unable to list source files from S3: {exc}") from exc

    return keys


def ingest_source_files(
    download_dir=DEFAULT_DOWNLOAD_DIR,
    s3_client=None,
) -> List[SourceFile]:
    """Download and prepare source files, returning SourceFile records."""
    bucket = _required_env("S3_BUCKET")
    input_prefix = _required_env("S3_INPUT_PREFIX")
    _required_env("S3_OUTPUT_PREFIX")

    client = s3_client or boto3.client("s3")
    download_dir = Path(download_dir)
    source_files: List[SourceFile] = []

    for s3_key in list_source_s3_keys(s3_client=client):
        local_path = _local_path_for_s3_key(s3_key, input_prefix, download_dir)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            client.download_file(bucket, s3_key, str(local_path))
        except (BotoCoreError, ClientError) as exc:
            raise RuntimeError(f"Unable to download {s3_key}: {exc}") from exc

        file_type = detect_file_type(local_path)
        processed_status = "processed"
        quality_flag = None

        if file_type == "unsupported":
            processed_status = "skipped"
        elif file_type == "image":
            quality = check_image_quality(local_path)
            quality_flag = quality["is_quality_sufficient"]
        elif file_type == "pdf":
            generated_images = convert_pdf_to_images(
                local_path,
                download_dir / "processed",
                dpi=300,
            )
            page_quality_flags = [
                check_image_quality(image_path)["is_quality_sufficient"]
                for image_path in generated_images
            ]
            quality_flag = all(page_quality_flags) if page_quality_flags else False

        source_files.append(
            SourceFile(
                local_path=str(local_path),
                s3_key=s3_key,
                file_type=file_type,
                quality_flag=quality_flag,
                processed_status=processed_status,
            )
        )

    return source_files
