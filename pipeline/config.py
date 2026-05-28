"""Shared project paths and environment helpers."""

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = PROJECT_ROOT / "tmp" / "orient"
PROCESSED_DIR = TEMP_DIR / "processed"
MANIFEST_PATH = TEMP_DIR / "manifest.json"

load_dotenv(PROJECT_ROOT / ".env")


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
