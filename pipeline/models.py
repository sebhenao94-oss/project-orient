"""Pydantic models for structured pipeline records."""

from enum import Enum
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


class AIReadyImageRecord(BaseModel):
    source_filename: str
    source_relative_path: str
    source_file_type: str
    source_sha256: str
    source_local_path: Optional[str] = None
    raw_s3_key: Optional[str] = None
    prepared_image_local_path: str
    prepared_image_s3_key: Optional[str] = None
    prepared_image_filename: str
    image_format: Optional[str] = None
    image_mime_type: Optional[str] = None
    source_page_number: Optional[int] = Field(default=None, ge=1)
    width: Optional[int] = Field(default=None, ge=0)
    height: Optional[int] = Field(default=None, ge=0)
    pixel_count: Optional[int] = Field(default=None, ge=0)
    quality_flag: bool
    quality_status: str
    quality_reason: str
    warnings: List[str] = Field(default_factory=list)
    extraction_eligible: bool
    preparation_status: str

    @field_validator(
        "source_filename",
        "source_relative_path",
        "source_file_type",
        "source_sha256",
        "prepared_image_local_path",
        "prepared_image_filename",
        "quality_status",
        "quality_reason",
        "preparation_status",
    )
    @classmethod
    def required_ai_ready_text_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("required text fields must not be blank")
        return value

    @field_validator("source_file_type")
    @classmethod
    def ai_ready_source_file_type_must_be_supported(cls, value: str) -> str:
        if value not in {"image", "pdf"}:
            raise ValueError("source_file_type must be image or pdf")
        return value

    @field_validator("source_sha256")
    @classmethod
    def ai_ready_sha256_must_be_lowercase_hex_digest(cls, value: str) -> str:
        if len(value) != 64 or value.lower() != value:
            raise ValueError("source_sha256 must be a lowercase hexadecimal SHA-256 digest")
        if any(character not in "0123456789abcdef" for character in value):
            raise ValueError("source_sha256 must be a lowercase hexadecimal SHA-256 digest")
        return value

    @field_validator("source_local_path", "raw_s3_key", "prepared_image_s3_key")
    @classmethod
    def optional_ai_ready_text_must_not_be_blank(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("optional text fields must not be blank when present")
        return value

    @field_validator("quality_status")
    @classmethod
    def quality_status_must_be_known_value(cls, value: str) -> str:
        if value not in {"passed", "failed"}:
            raise ValueError("quality_status must be passed or failed")
        return value

    @field_validator("preparation_status")
    @classmethod
    def preparation_status_must_be_known_value(cls, value: str) -> str:
        if value not in {"prepared", "quality_failed"}:
            raise ValueError("preparation_status must be prepared or quality_failed")
        return value


class IngestionPreparationResult(BaseModel):
    source_manifest_records: List[LocalSourceFileManifestRecord] = Field(default_factory=list)
    raw_upload_results: List[RawSourceUploadResult] = Field(default_factory=list)
    prepared_image_records: List[AIReadyImageRecord] = Field(default_factory=list)
    deferred_source_records: List[LocalSourceFileManifestRecord] = Field(default_factory=list)
    failures: List[str] = Field(default_factory=list)

class EquipmentType(str, Enum):
    AHU = "AHU"
    VAV = "VAV"
    VAVRH = "VAVRH"
    FPTU = "FPTU"
    OAVAV = "OAVAV"
    FCU = "FCU"
    UNKNOWN = "unknown"


class EquipmentExtractionCandidate(BaseModel):
    raw_label: str
    canonical_name: str
    equipment_type: EquipmentType
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("raw_label", "canonical_name")
    @classmethod
    def extraction_text_must_not_be_blank(cls, value: str) -> str:
        trimmed_value = value.strip()
        if not trimmed_value:
            raise ValueError("required text fields must not be blank")
        return trimmed_value


class EquipmentExtractionResponse(BaseModel):
    equipment: List[EquipmentExtractionCandidate]

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
