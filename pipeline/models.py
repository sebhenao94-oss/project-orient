"""Pydantic models for structured pipeline records."""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


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


class RawDrawingEquipmentRecord(BaseModel):
    property_id: str
    floor: str
    source_file: str
    source_type: str
    raw_equipment_label: str
    raw_equipment_type: str
    evidence_detail: str
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator(
        "property_id",
        "floor",
        "source_file",
        "source_type",
        "raw_equipment_label",
        "raw_equipment_type",
        "evidence_detail",
    )
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("required text fields must not be blank")
        return value

    @field_validator("floor")
    @classmethod
    def floor_must_be_floor_02(cls, value: str) -> str:
        if value != "Floor_02":
            raise ValueError("floor must equal Floor_02")
        return value
