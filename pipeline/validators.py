"""Validation helpers for pipeline outputs."""


PROCESSED_STATUSES = {"processed", "skipped"}
QUALITY_STATUSES = {"passed", "failed", "not_applicable"}


def is_valid_processed_status(status: str) -> bool:
    return status in PROCESSED_STATUSES


def is_valid_quality_status(status: str) -> bool:
    return status in QUALITY_STATUSES
