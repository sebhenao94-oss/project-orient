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


class LocalSourceFileManifestRecord(BaseModel):
    local_path: str
    relative_path: str
    source_filename: str
    file_type: str
    file_size_bytes: int = Field(..., ge=0)
    sha256: str
    ingestion_status: str

    @field_validator("local_path", "relative_path", "source_filename")
    @classmethod
    def required_local_text_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("required text fields must not be blank")
        return value

    @field_validator("file_type")
    @classmethod
    def file_type_must_be_known_manifest_value(cls, value: str) -> str:
        allowed_file_types = {"image", "pdf", "dwg", "unsupported"}
        if value not in allowed_file_types:
            raise ValueError("file_type must be image, pdf, dwg, or unsupported")
        return value

    @field_validator("sha256")
    @classmethod
    def sha256_must_be_lowercase_hex_digest(cls, value: str) -> str:
        if len(value) != 64 or value.lower() != value:
            raise ValueError("sha256 must be a lowercase hexadecimal SHA-256 digest")
        if any(character not in "0123456789abcdef" for character in value):
            raise ValueError("sha256 must be a lowercase hexadecimal SHA-256 digest")
        return value

    @field_validator("ingestion_status")
    @classmethod
    def ingestion_status_must_be_known_value(cls, value: str) -> str:
        if value not in {"discovered", "skipped"}:
            raise ValueError("ingestion_status must be discovered or skipped")
        return value

class RawSourceUploadResult(BaseModel):
    local_path: str
    relative_path: str
    source_filename: str
    file_type: str
    s3_key: Optional[str] = None
    sha256: str
    file_size_bytes: int = Field(..., ge=0)
    upload_status: str

    @field_validator("local_path", "relative_path", "source_filename")
    @classmethod
    def required_upload_text_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("required text fields must not be blank")
        return value

    @field_validator("file_type")
    @classmethod
    def upload_file_type_must_be_known_value(cls, value: str) -> str:
        allowed_file_types = {"image", "pdf", "dwg", "unsupported"}
        if value not in allowed_file_types:
            raise ValueError("file_type must be image, pdf, dwg, or unsupported")
        return value

    @field_validator("s3_key")
    @classmethod
    def optional_s3_key_must_not_be_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("s3_key must not be blank when present")
        return value

    @field_validator("sha256")
    @classmethod
    def upload_sha256_must_be_lowercase_hex_digest(cls, value: str) -> str:
        if len(value) != 64 or value.lower() != value:
            raise ValueError("sha256 must be a lowercase hexadecimal SHA-256 digest")
        if any(character not in "0123456789abcdef" for character in value):
            raise ValueError("sha256 must be a lowercase hexadecimal SHA-256 digest")
        return value

    @field_validator("upload_status")
    @classmethod
    def upload_status_must_be_known_value(cls, value: str) -> str:
        if value not in {"planned", "uploaded", "skipped", "conflict"}:
            raise ValueError("upload_status must be planned, uploaded, skipped, or conflict")
        return value

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
