from __future__ import annotations

import os
from pathlib import Path

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    PartialCredentialsError,
)
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


class MissingEnvironmentVariableError(RuntimeError):
    """Raised when required pipeline configuration is missing."""


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise MissingEnvironmentVariableError(
            f"Missing required environment variable: {name}"
        )
    return value


def list_input_objects() -> list[dict]:
    """Return non-folder S3 objects under S3_INPUT_PREFIX as {key, size} dicts."""
    bucket = _required_env("S3_BUCKET")
    prefix = _required_env("S3_INPUT_PREFIX")
    output_prefix = get_output_prefix()
    output_prefix_filter = f"{output_prefix}/" if output_prefix else ""

    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    objects: list[dict] = []
    try:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # Prevent the ingestion pipeline from recursively processing its own outputs.
                if key.endswith("/") or key.startswith(output_prefix_filter):
                    continue
                objects.append({"key": key, "size": int(obj.get("Size", 0))})
    except (NoCredentialsError, PartialCredentialsError) as exc:
        raise RuntimeError(
            "AWS credentials were not found or are incomplete. "
            "Set temporary credentials in your PowerShell session and try again."
        ) from exc
    except ClientError as exc:
        message = exc.response.get("Error", {}).get("Message", str(exc))
        raise RuntimeError(f"Unable to list S3 input files: {message}") from exc
    except BotoCoreError as exc:
        raise RuntimeError(f"Unable to list S3 input files: {exc}") from exc

    return objects


def list_input_files() -> list[str]:
    """Return all non-folder S3 object keys under S3_INPUT_PREFIX."""
    return [obj["key"] for obj in list_input_objects()]


def download_file(s3_key: str, local_path: Path) -> Path:
    """Download one S3 object to a local path and return that path."""
    bucket = _required_env("S3_BUCKET")
    local_path.parent.mkdir(parents=True, exist_ok=True)

    s3 = boto3.client("s3")
    try:
        s3.download_file(bucket, s3_key, str(local_path))
    except (NoCredentialsError, PartialCredentialsError) as exc:
        raise RuntimeError(
            "AWS credentials were not found or are incomplete. "
            "Set temporary credentials in your PowerShell session and try again."
        ) from exc
    except ClientError as exc:
        message = exc.response.get("Error", {}).get("Message", str(exc))
        raise RuntimeError(f"Unable to download {s3_key}: {message}") from exc
    except BotoCoreError as exc:
        raise RuntimeError(f"Unable to download {s3_key}: {exc}") from exc

    return local_path


def upload_file(local_path: Path, s3_key: str) -> str:
    """Upload a local file to one S3 object key and return that key."""
    bucket = _required_env("S3_BUCKET")

    s3 = boto3.client("s3")
    try:
        s3.upload_file(str(local_path), bucket, s3_key)
    except (NoCredentialsError, PartialCredentialsError) as exc:
        raise RuntimeError(
            "AWS credentials were not found or are incomplete. "
            "Set temporary credentials in your PowerShell session and try again."
        ) from exc
    except ClientError as exc:
        message = exc.response.get("Error", {}).get("Message", str(exc))
        raise RuntimeError(f"Unable to upload {local_path}: {message}") from exc
    except BotoCoreError as exc:
        raise RuntimeError(f"Unable to upload {local_path}: {exc}") from exc

    return s3_key


def get_output_prefix() -> str:
    """Return the configured S3 output prefix without a trailing slash."""
    return _required_env("S3_OUTPUT_PREFIX").rstrip("/")
