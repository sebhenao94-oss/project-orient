"""Pydantic models for structured pipeline records."""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

if __package__:
    from .equipment_vocab import LIBRARY_TYPE_KEYS
else:
    from equipment_vocab import LIBRARY_TYPE_KEYS


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
    """Manifest entry for one locally discovered raw source file.

    "Local" means the file was found on disk before upload/preparation.
    "SourceFile" means it is an original project input such as a screenshot,
    drawing PDF, DWG, or unsupported file. "ManifestRecord" means this object is
    one row in the ingestion manifest used for provenance, checksums, file type
    routing, and skip/discovery status before extraction starts.
    """

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
    source_document_type: str = "unknown"
    source_document_reason: str = "not classified"
    image_complexity: str = "unknown"
    image_complexity_reason: str = "not classified"
    extraction_route: str = "needs_source_type_review"
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
        "image_complexity",
        "image_complexity_reason",
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

    @field_validator("source_document_type")
    @classmethod
    def source_document_type_must_be_known_value(cls, value: str) -> str:
        allowed_values = {"bms_screenshot", "mechanical_drawing", "unknown"}
        if value not in allowed_values:
            raise ValueError("source_document_type must be bms_screenshot, mechanical_drawing, or unknown")
        return value

    @field_validator("extraction_route")
    @classmethod
    def extraction_route_must_be_known_value(cls, value: str) -> str:
        allowed_values = {
            "standard_screenshot_extraction",
            "mechanical_drawing_second_pass",
            "needs_source_type_review",
        }
        if value not in allowed_values:
            raise ValueError("extraction_route must be a known extraction route")
        return value

    @field_validator("image_complexity")
    @classmethod
    def image_complexity_must_be_known_value(cls, value: str) -> str:
        allowed_values = {"simple", "moderate", "complex", "unknown"}
        if value not in allowed_values:
            raise ValueError("image_complexity must be simple, moderate, complex, or unknown")
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

UNKNOWN_EQUIPMENT_CLASS = "unknown class"
ALLOWED_EQUIPMENT_TYPES = frozenset(LIBRARY_TYPE_KEYS | {UNKNOWN_EQUIPMENT_CLASS})


class EquipmentExtractionCandidate(BaseModel):
    raw_label: str
    canonical_name: str
    equipment_type: str
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("raw_label", "canonical_name")
    @classmethod
    def extraction_text_must_not_be_blank(cls, value: str) -> str:
        trimmed_value = value.strip()
        if not trimmed_value:
            raise ValueError("required text fields must not be blank")
        return trimmed_value

    @field_validator("equipment_type")
    @classmethod
    def equipment_type_must_match_current_library(cls, value: str) -> str:
        if value not in ALLOWED_EQUIPMENT_TYPES:
            raise ValueError("equipment_type must be in equipments_point_types or unknown class")
        return value


class EquipmentExtractionResponse(BaseModel):
    equipment: List[EquipmentExtractionCandidate]


class EquipmentExtractionRunResult(BaseModel):
    source_filename: str
    source_relative_path: str
    source_sha256: str
    source_file_type: str
    source_document_type: str = "unknown"
    source_document_reason: str = "not classified"
    image_complexity: str = "unknown"
    image_complexity_reason: str = "not classified"
    extraction_route: str = "needs_source_type_review"
    prepared_image_path: str
    prepared_image_filename: str
    image_mime_type: Optional[str] = None
    pdf_page_number: Optional[int] = Field(default=None, ge=1)
    prompt_version: str
    model_id: str
    started_at: datetime
    completed_at: datetime
    status: str
    raw_assistant_response: Optional[str] = None
    parsed_response: Optional[EquipmentExtractionResponse] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    @field_validator(
        "source_filename",
        "source_relative_path",
        "source_sha256",
        "source_file_type",
        "source_document_type",
        "source_document_reason",
        "image_complexity",
        "image_complexity_reason",
        "extraction_route",
        "prepared_image_path",
        "prepared_image_filename",
        "prompt_version",
        "model_id",
        "status",
    )
    @classmethod
    def required_extraction_text_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("required text fields must not be blank")
        return value

    @field_validator("source_document_type")
    @classmethod
    def extraction_source_document_type_must_be_known_value(cls, value: str) -> str:
        allowed_values = {"bms_screenshot", "mechanical_drawing", "unknown"}
        if value not in allowed_values:
            raise ValueError("source_document_type must be bms_screenshot, mechanical_drawing, or unknown")
        return value

    @field_validator("extraction_route")
    @classmethod
    def extraction_route_must_be_known_value(cls, value: str) -> str:
        allowed_values = {
            "standard_screenshot_extraction",
            "mechanical_drawing_second_pass",
            "needs_source_type_review",
        }
        if value not in allowed_values:
            raise ValueError("extraction_route must be a known extraction route")
        return value

    @field_validator("image_complexity")
    @classmethod
    def extraction_image_complexity_must_be_known_value(cls, value: str) -> str:
        allowed_values = {"simple", "moderate", "complex", "unknown"}
        if value not in allowed_values:
            raise ValueError("image_complexity must be simple, moderate, complex, or unknown")
        return value

    @field_validator("source_sha256")
    @classmethod
    def extraction_sha256_must_be_lowercase_hex_digest(cls, value: str) -> str:
        if len(value) != 64 or value.lower() != value:
            raise ValueError("source_sha256 must be a lowercase hexadecimal SHA-256 digest")
        if any(character not in "0123456789abcdef" for character in value):
            raise ValueError("source_sha256 must be a lowercase hexadecimal SHA-256 digest")
        return value

    @field_validator("status")
    @classmethod
    def extraction_status_must_be_known_value(cls, value: str) -> str:
        if value not in {"succeeded", "transport_failed", "parse_failed", "validation_failed", "skipped"}:
            raise ValueError("status must be succeeded, transport_failed, parse_failed, validation_failed, or skipped")
        return value

    @field_validator("started_at", "completed_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def extraction_state_must_be_consistent(self):
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not be earlier than started_at")
        if self.status == "succeeded":
            if self.parsed_response is None:
                raise ValueError("successful extraction requires parsed_response")
            if self.error_type is not None or self.error_message is not None:
                raise ValueError("successful extraction must not include errors")
        else:
            if self.parsed_response is not None:
                raise ValueError("failed or skipped extraction must not include parsed_response")
            if not self.error_type or not self.error_message:
                raise ValueError("failed or skipped extraction requires error_type and error_message")
        if self.status in {"parse_failed", "validation_failed"} and not self.raw_assistant_response:
            raise ValueError("parse and validation failures must retain raw_assistant_response")
        return self


class TopicsEquipmentSnapshotResult(BaseModel):
    output_path: str
    snapshot_version: str
    property_id: str
    property_name: str
    floor: str
    row_count: int = Field(..., ge=0)
    distinct_context_count: int = Field(..., ge=0)

    @field_validator("output_path", "snapshot_version", "property_id", "property_name", "floor")
    @classmethod
    def required_topics_result_text_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("required text fields must not be blank")
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


class NormalizationStatus(str, Enum):
    """Disposition of a canonical equipment unit after W4 normalization.

    `settled` units are agreed-upon and need no human action. `review_required`
    units carry a discrepancy worth a human look (e.g. present on only one
    source, or a type disagreement). `floor_ambiguous` is reserved for the units
    flagged in the W4 floor-ambiguity handoff: their floor is genuinely contested
    and a supervisor clarification is pending, so they are always routed to review
    and never silently treated as settled Floor-2 equipment.
    """

    SETTLED = "settled"
    REVIEW_REQUIRED = "review_required"
    FLOOR_AMBIGUOUS = "floor_ambiguous"


class DiscrepancyCategory(str, Enum):
    """How the topics-derived and drawing-derived W3 snapshots relate for a unit.

    `matched` means the same canonical unit appears in both sources with a
    consistent equipment type. `type_mismatch` means it appears in both but the
    inferred types disagree. `topics_only` / `drawing_only` are the gap cases:
    documented in the BMS topics but absent from the drawings, or extracted from
    the drawings but absent from the BMS topics. `floor_ambiguous` overrides the
    others for the contested-floor units.
    """

    MATCHED = "matched"
    TYPE_MISMATCH = "type_mismatch"
    TOPICS_ONLY = "topics_only"
    DRAWING_ONLY = "drawing_only"
    FLOOR_AMBIGUOUS = "floor_ambiguous"


class NormalizedEquipmentRecord(BaseModel):
    """One canonical Floor-02 equipment unit after reconciling the W3 snapshots.

    Produced by `pipeline/normalization.py` by matching the immutable
    topics-derived and drawing-derived W3 snapshots on a normalised canonical
    key. `canonical_key` is the separator/zero-padding-insensitive key used for
    matching; `canonical_name` is the human-facing label. Provenance booleans
    (`in_topics`, `in_drawings`) record which sources contributed the unit, and
    the raw labels from each source are retained for review.
    """

    snapshot_version: str
    property_id: str
    property_name: str
    floor: str
    canonical_name: str
    canonical_key: str
    equipment_type: str
    discrepancy_category: DiscrepancyCategory
    status: NormalizationStatus
    in_topics: bool
    in_drawings: bool
    topics_raw_label: str = ""
    topics_inferred_type: str = ""
    drawing_raw_label: str = ""
    drawing_equipment_type: str = ""
    review_required: bool
    review_reason: str = ""

    @field_validator(
        "snapshot_version",
        "property_id",
        "property_name",
        "floor",
        "canonical_name",
        "canonical_key",
        "equipment_type",
    )
    @classmethod
    def required_normalized_text_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("required text fields must not be blank")
        return value

    @field_validator("floor")
    @classmethod
    def normalized_floor_must_be_floor_02(cls, value: str) -> str:
        if value != "Floor_02":
            raise ValueError("floor must equal Floor_02")
        return value

    @model_validator(mode="after")
    def normalized_state_must_be_consistent(self):
        if not self.in_topics and not self.in_drawings:
            raise ValueError("a normalized unit must originate from at least one source")
        if self.status == NormalizationStatus.SETTLED:
            if self.review_required:
                raise ValueError("settled units must not require review")
        else:
            if not self.review_required:
                raise ValueError("non-settled units must require review")
            if not self.review_reason or not self.review_reason.strip():
                raise ValueError("units routed to review require a review_reason")
        if self.status == NormalizationStatus.FLOOR_AMBIGUOUS:
            if self.discrepancy_category != DiscrepancyCategory.FLOOR_AMBIGUOUS:
                raise ValueError(
                    "floor_ambiguous status requires floor_ambiguous discrepancy_category"
                )
        return self


class NormalizationSummary(BaseModel):
    """Aggregate counts for a normalization run, for the W4 gap report."""

    snapshot_version: str
    property_id: str
    property_name: str
    floor: str
    total_units: int = Field(..., ge=0)
    matched_count: int = Field(..., ge=0)
    type_mismatch_count: int = Field(..., ge=0)
    topics_only_count: int = Field(..., ge=0)
    drawing_only_count: int = Field(..., ge=0)
    floor_ambiguous_count: int = Field(..., ge=0)
    review_required_count: int = Field(..., ge=0)


class RelationshipRefType(str, Enum):
    """Haystack relationship reference types, aligned to equipment_details columns.

    Values mirror the live `equipment_details` reference columns observed in the
    bas_data database: airRef plus the three specific water references and the
    generic systemRef parent. spaceRef/floorRef are included for forward
    compatibility with later zone work, but the W4 extraction prompt does not
    emit them. There is intentionally no generic "waterRef".
    """

    AIR_REF = "airRef"
    CHILLED_WATER_REF = "chilledWaterRef"
    HOT_WATER_REF = "hotWaterRef"
    CONDENSER_WATER_REF = "condenserWaterRef"
    SYSTEM_REF = "systemRef"
    SPACE_REF = "spaceRef"
    FLOOR_REF = "floorRef"


class RelationshipEdge(BaseModel):
    """One inferred equipment-to-equipment relationship edge.

    `child` is the served/owned unit and `parent` is the serving unit, both
    given as canonical names that must already be present in the equipment list
    supplied to the model. Provenance (source drawing, page) is added by the
    orchestration layer, not by the model response, matching the equipment
    extraction convention.
    """

    child: str
    parent: str
    ref_type: RelationshipRefType
    confidence: float = Field(..., ge=0.0, le=1.0)
    conflict: bool = False
    conflict_reason: str = ""

    @field_validator("child", "parent")
    @classmethod
    def relationship_endpoint_must_not_be_blank(cls, value: str) -> str:
        trimmed_value = value.strip()
        if not trimmed_value:
            raise ValueError("relationship endpoints must not be blank")
        return trimmed_value


class RelationshipExtractionResponse(BaseModel):
    relationships: List[RelationshipEdge]


class RelationshipExtractionRunResult(BaseModel):
    source_filename: str
    source_relative_path: str
    source_sha256: str
    source_file_type: str
    prepared_image_path: str
    prepared_image_filename: str
    image_mime_type: Optional[str] = None
    pdf_page_number: Optional[int] = Field(default=None, ge=1)
    prompt_version: str
    model_id: str
    started_at: datetime
    completed_at: datetime
    status: str
    raw_assistant_response: Optional[str] = None
    parsed_response: Optional[RelationshipExtractionResponse] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    @field_validator(
        "source_filename",
        "source_relative_path",
        "source_sha256",
        "source_file_type",
        "prepared_image_path",
        "prepared_image_filename",
        "prompt_version",
        "model_id",
        "status",
    )
    @classmethod
    def required_relationship_run_text_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("required text fields must not be blank")
        return value

    @field_validator("source_sha256")
    @classmethod
    def relationship_run_sha256_must_be_lowercase_hex_digest(cls, value: str) -> str:
        if len(value) != 64 or value.lower() != value:
            raise ValueError("source_sha256 must be a lowercase hexadecimal SHA-256 digest")
        if any(character not in "0123456789abcdef" for character in value):
            raise ValueError("source_sha256 must be a lowercase hexadecimal SHA-256 digest")
        return value

    @field_validator("status")
    @classmethod
    def relationship_run_status_must_be_known_value(cls, value: str) -> str:
        if value not in {"succeeded", "transport_failed", "parse_failed", "validation_failed", "skipped"}:
            raise ValueError("status must be succeeded, transport_failed, parse_failed, validation_failed, or skipped")
        return value

    @field_validator("started_at", "completed_at")
    @classmethod
    def relationship_run_timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def relationship_run_state_must_be_consistent(self):
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not be earlier than started_at")
        if self.status == "succeeded":
            if self.parsed_response is None:
                raise ValueError("successful run requires parsed_response")
            if self.error_type is not None or self.error_message is not None:
                raise ValueError("successful run must not include errors")
        else:
            if self.parsed_response is not None:
                raise ValueError("failed or skipped run must not include parsed_response")
            if not self.error_type or not self.error_message:
                raise ValueError("failed or skipped run requires error_type and error_message")
        if self.status in {"parse_failed", "validation_failed"} and not self.raw_assistant_response:
            raise ValueError("parse and validation failures must retain raw_assistant_response")
        return self
