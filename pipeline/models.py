"""Pydantic models for structured pipeline records."""

from typing import List, Optional

from pydantic import BaseModel, Field


class SourceFile(BaseModel):
    local_path: str
    s3_key: str
    file_type: str
    quality_flag: Optional[bool] = None
    processed_status: str


class SourceFileManifestRecord(BaseModel):
    source_s3_key: str
    local_path: str
    file_type: str
    processed_status: str
    quality_status: str
    quality_reason: str
    output_s3_keys: List[str] = Field(default_factory=list)
    timestamp_utc: str
