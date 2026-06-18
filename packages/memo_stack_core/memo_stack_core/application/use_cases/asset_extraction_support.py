"""Support helpers for asset extraction orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from math import ceil

from memo_stack_core.application.safe_payload import safe_metadata_text
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.domain.extraction import (
    AssetExtractionJob,
    AssetExtractionStatus,
    ExtractionRetryDisposition,
)
from memo_stack_core.ports.extraction import ExtractionResult

DEFAULT_PARSER_CONFIG_VERSION = "v1"
NON_RUNNABLE_EXTRACTION_STATUSES = {
    AssetExtractionStatus.SUCCEEDED,
    AssetExtractionStatus.UNSUPPORTED,
    AssetExtractionStatus.CANCELED,
    AssetExtractionStatus.STALE,
}


class ActiveAssetExtractionLeaseError(RuntimeError):
    diagnostic_code = "asset_extraction.lease_active"

    def __init__(
        self,
        *,
        job_id: str,
        lease_owner: str | None,
        retry_after_at: datetime | None,
    ) -> None:
        super().__init__("Asset extraction is already running with an active lease")
        self.job_id = job_id
        self.lease_owner = lease_owner
        self.retry_after_at = retry_after_at


class DeferredAssetExtractionRetryError(RuntimeError):
    diagnostic_code = "asset_extraction.retry_not_ready"

    def __init__(
        self,
        *,
        job_id: str,
        retry_after_at: datetime,
    ) -> None:
        super().__init__("Asset extraction retry is waiting for retry_after_at")
        self.job_id = job_id
        self.retry_after_at = retry_after_at


class ExtractionRetryPolicy:
    def __init__(
        self,
        *,
        max_attempts: int = 5,
        base_delay_seconds: int = 30,
        max_delay_seconds: int = 900,
    ) -> None:
        self.max_attempts = max(1, max_attempts)
        self.base_delay_seconds = max(1, base_delay_seconds)
        self.max_delay_seconds = max(self.base_delay_seconds, max_delay_seconds)

    def disposition_for_code(self, code: str) -> ExtractionRetryDisposition:
        if is_permanent_error_code(code):
            return ExtractionRetryDisposition.PERMANENT
        return ExtractionRetryDisposition.RETRYABLE

    def retry_after(
        self,
        *,
        now: datetime,
        attempt_count: int,
        code: str,
    ) -> datetime | None:
        if attempt_count >= self.max_attempts:
            return None
        if self.disposition_for_code(code) != ExtractionRetryDisposition.RETRYABLE:
            return None
        exponent = max(0, attempt_count - 1)
        delay_seconds = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2**exponent),
        )
        return now + timedelta(seconds=delay_seconds)


def asset_extract_event(job: AssetExtractionJob) -> OutboxEvent:
    return OutboxEvent(
        event_type="asset.extract",
        aggregate_type="asset_extraction_job",
        aggregate_id=str(job.id),
        workload_class="extraction",
        fairness_key=f"{job.space_id}:{job.memory_scope_id}",
        payload={
            "job_id": str(job.id),
            "asset_id": str(job.asset_id),
            "parser_profile": job.parser_profile,
        },
    )


def parser_config_hash(parser_profile: str) -> str:
    raw = f"{parser_profile}:{DEFAULT_PARSER_CONFIG_VERSION}"
    return sha256(raw.encode("utf-8")).hexdigest()


def usage_idempotency_key(
    *,
    asset_id: str,
    parser_profile: str,
    parser_config_hash: str,
    source_sha256_hex: str,
) -> str:
    return (
        "asset_extraction_media:"
        f"{asset_id}:{parser_profile}:{parser_config_hash}:{source_sha256_hex}"
    )


def usage_reconciliation_idempotency_key(*, job_id: str, actual_seconds: int) -> str:
    return f"asset_extraction_media_reconcile:{job_id}:{actual_seconds}"


def estimated_media_analysis_seconds(
    asset,
    *,
    default_unknown_media_seconds: int,
) -> int:
    content_type = asset.content_type.lower()
    if not (content_type.startswith("audio/") or content_type.startswith("video/")):
        return 0
    for key in (
        "media_duration_seconds",
        "estimated_media_seconds",
        "duration_seconds",
    ):
        parsed = positive_int(asset.metadata.get(key))
        if parsed is not None:
            return parsed
    return default_unknown_media_seconds


def actual_media_analysis_seconds(result: ExtractionResult) -> int | None:
    if result.status == "unsupported":
        return 0
    if result.status != "succeeded":
        return None

    metadata = result.technical_metadata
    for key in (
        "usage_media_analysis_seconds_actual",
        "media_analysis_seconds_actual",
        "media_duration_seconds",
        "duration_seconds",
        "estimated_media_seconds",
    ):
        parsed = positive_duration_seconds(metadata.get(key))
        if parsed is not None:
            return parsed

    duration_ms = positive_number(metadata.get("duration_ms"))
    if duration_ms is not None:
        return max(1, int(ceil(duration_ms / 1000)))
    return None


def positive_duration_seconds(value: object) -> int | None:
    number = positive_number(value)
    if number is None:
        return None
    return max(1, int(ceil(number)))


def positive_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number > 0 else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return number if number > 0 else None
    return None


def positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 0 else None
    if isinstance(value, str):
        try:
            number = int(float(value.strip()))
        except ValueError:
            return None
        return number if number > 0 else None
    return None


def indexing_status(status: AssetExtractionStatus) -> str:
    return {
        AssetExtractionStatus.PENDING: "pending",
        AssetExtractionStatus.RUNNING: "running",
        AssetExtractionStatus.SUCCEEDED: "indexed_or_pending",
        AssetExtractionStatus.FAILED: "failed",
        AssetExtractionStatus.UNSUPPORTED: "unsupported",
        AssetExtractionStatus.CANCELED: "canceled",
        AssetExtractionStatus.STALE: "stale",
    }[status]


def is_non_runnable_extraction_job(job: AssetExtractionJob) -> bool:
    return job.status in NON_RUNNABLE_EXTRACTION_STATUSES or (
        job.status == AssetExtractionStatus.FAILED
        and job.retry_disposition == ExtractionRetryDisposition.PERMANENT
    )


def safe_exception_code(exc: Exception) -> str:
    name = exc.__class__.__name__.lower()
    return f"asset_extraction.{name[:80]}"


def safe_exception_message(exc: Exception) -> str:
    return safe_error_text(str(exc).strip() or exc.__class__.__name__)


def safe_error_text(text: str) -> str:
    return safe_metadata_text(text.strip() or "Unexpected extraction error")


def is_permanent_error_code(code: str) -> bool:
    normalized = code.lower()
    permanent_markers = (
        "unsupported",
        "too_long",
        "too_large",
        "encrypted",
        "dependency_missing",
        "not_installed",
        "missing_api_key",
        "external_ai_disabled",
        "empty_text",
        "empty_output",
        "no_text",
        "no_speech",
    )
    return any(marker in normalized for marker in permanent_markers)
