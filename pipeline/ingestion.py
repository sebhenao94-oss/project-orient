import hashlib
import os
import warnings
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
from PIL import Image, UnidentifiedImageError

from models import LocalSourceFileManifestRecord, SourceFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


MIN_IMAGE_LONG_SIDE = 1000
MIN_IMAGE_SHORT_SIDE = 750
MAX_RECOMMENDED_PIXEL_COUNT = 100_000_000
# Legacy names retained for existing callers: width is now the long-side
# threshold, and height is now the short-side threshold.
MIN_IMAGE_WIDTH = MIN_IMAGE_LONG_SIDE
MIN_IMAGE_HEIGHT = MIN_IMAGE_SHORT_SIDE
SOURCE_SUBFOLDERS = ("screenshots/", "drawings/", "bms_exports/")
DEFAULT_DOWNLOAD_DIR = Path("/tmp/orient")
SHA256_CHUNK_SIZE = 1024 * 1024


class IngestionConfigError(RuntimeError):
    """Raised when ingestion configuration is missing."""


class LocalIngestionError(RuntimeError):
    """Raised when local source-file discovery cannot read an input file."""


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

def _sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with file_path.open("rb") as source_file:
            for chunk in iter(lambda: source_file.read(SHA256_CHUNK_SIZE), b""):
                digest.update(chunk)
    except OSError as exc:
        raise LocalIngestionError(f"Unable to read source file: {file_path}") from exc

    return digest.hexdigest()


def _file_size_bytes(file_path: Path) -> int:
    try:
        return file_path.stat().st_size
    except OSError as exc:
        raise LocalIngestionError(f"Unable to read source file metadata: {file_path}") from exc


def build_local_source_manifest(input_dir) -> List[LocalSourceFileManifestRecord]:
    """Discover local source files and return read-only manifest records."""
    input_root = Path(input_dir).resolve()

    if not input_root.exists():
        raise FileNotFoundError(f"Local input path does not exist: {input_root}")
    if not input_root.is_dir():
        raise NotADirectoryError(f"Local input path is not a directory: {input_root}")

    files = [path for path in input_root.rglob("*") if path.is_file()]
    files.sort(
        key=lambda path: (
            path.relative_to(input_root).as_posix().lower(),
            path.relative_to(input_root).as_posix(),
        )
    )

    records: List[LocalSourceFileManifestRecord] = []
    for file_path in files:
        resolved_path = file_path.resolve()
        relative_path = file_path.relative_to(input_root).as_posix()
        file_type = detect_file_type(file_path)
        ingestion_status = "skipped" if file_type == "unsupported" else "discovered"

        records.append(
            LocalSourceFileManifestRecord(
                local_path=str(resolved_path),
                relative_path=relative_path,
                source_filename=file_path.name,
                file_type=file_type,
                file_size_bytes=_file_size_bytes(file_path),
                sha256=_sha256_file(file_path),
                ingestion_status=ingestion_status,
            )
        )

    return records

def check_image_quality(file_path) -> dict:
    """Inspect image dimensions and flag files below the smoke-test threshold."""
    file_path = Path(file_path)
    captured_warnings = []

    try:
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always", Image.DecompressionBombWarning)
            with Image.open(file_path) as image:
                width, height = image.size

        captured_warnings = [
            str(caught_warning.message)
            for caught_warning in caught_warnings
            if issubclass(caught_warning.category, Image.DecompressionBombWarning)
        ]
    except (UnidentifiedImageError, OSError) as exc:
        reason = f"Unable to read image file {file_path}: {exc}"
        return {
            "width": None,
            "height": None,
            "pixel_count": None,
            "quality_flag": False,
            "is_quality_sufficient": False,
            "reason": reason,
            "warnings": captured_warnings,
        }

    pixel_count = width * height
    long_side = max(width, height)
    short_side = min(width, height)

    if long_side < MIN_IMAGE_LONG_SIDE or short_side < MIN_IMAGE_SHORT_SIDE:
        reason = (
            f"Image resolution {width}x{height} is below minimum threshold: "
            f"long side must be at least {MIN_IMAGE_LONG_SIDE}px and short side "
            f"must be at least {MIN_IMAGE_SHORT_SIDE}px"
        )
        quality_flag = False
    elif pixel_count > MAX_RECOMMENDED_PIXEL_COUNT:
        reason = (
            f"Image resolution {width}x{height} is valid but unusually large "
            f"({pixel_count} pixels) and may require resizing or tiling before LLM inference"
        )
        captured_warnings.append(
            f"Image pixel count {pixel_count} exceeds recommended maximum "
            f"{MAX_RECOMMENDED_PIXEL_COUNT}"
        )
        quality_flag = True
    else:
        reason = "Image meets minimum resolution threshold"
        quality_flag = True

    return {
        "width": width,
        "height": height,
        "pixel_count": pixel_count,
        "quality_flag": quality_flag,
        "is_quality_sufficient": quality_flag,
        "reason": reason,
        "warnings": captured_warnings,
    }


def convert_pdf_to_images(pdf_path, output_dir, dpi=300, poppler_path=None) -> List[Path]:
    """Convert each PDF page to a PNG image and return generated paths."""
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF source path does not exist: {pdf_path}")
    if not pdf_path.is_file():
        raise IsADirectoryError(f"PDF source path is not a file: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"PDF source path must have a .pdf extension: {pdf_path}")
    if dpi < 300:
        raise ValueError("PDF conversion DPI must be at least 300")

    target_dir = Path(output_dir) / pdf_path.stem
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Unable to create PDF output directory for {pdf_path}: {target_dir}"
        ) from exc

    try:
        pages = convert_from_path(
            str(pdf_path),
            dpi=dpi,
            poppler_path=poppler_path,
        )
    except PDFInfoNotInstalledError as exc:
        raise RuntimeError(
            "Poppler is required for PDF conversion but was not found. "
            "Install Poppler for Windows and make sure its bin folder is on PATH."
        ) from exc
    except PDFPageCountError as exc:
        raise RuntimeError(f"Unable to read page count from PDF: {pdf_path}") from exc
    except PDFSyntaxError as exc:
        raise RuntimeError(f"PDF appears to be invalid or unreadable: {pdf_path}") from exc
    except Exception as exc:
        raise RuntimeError(f"Unable to convert PDF to images: {pdf_path}") from exc

    generated_paths: List[Path] = []
    for page_number, page in enumerate(pages, start=1):
        image_path = target_dir / f"page_{page_number:03}.png"
        try:
            page.save(image_path, "PNG")
        except Exception as exc:
            raise RuntimeError(
                f"Unable to save converted PDF page {page_number} for {pdf_path}: {image_path}"
            ) from exc
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
