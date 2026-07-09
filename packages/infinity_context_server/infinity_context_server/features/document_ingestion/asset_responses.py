"""Asset response mappers owned by the document_ingestion server seam."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from infinity_context_server.api.public_payload import (
    safe_public_metadata,
    safe_public_text,
)


def asset_to_response(asset: Any) -> dict[str, Any]:
    return {
        "id": str(asset.id),
        "space_id": str(asset.space_id),
        "memory_scope_id": str(asset.memory_scope_id),
        "thread_id": str(asset.thread_id) if asset.thread_id else None,
        "filename": asset.filename,
        "content_type": asset.content_type,
        "byte_size": asset.byte_size,
        "sha256_hex": asset.sha256_hex,
        "storage_backend": asset.storage_backend,
        "status": asset.status.value,
        "classification": asset.classification,
        "metadata": _safe_metadata(asset.metadata),
        "created_at": asset.created_at.isoformat(),
        "updated_at": asset.updated_at.isoformat(),
    }


def deduplication_to_response(info: Any | None) -> dict[str, Any] | None:
    if info is None:
        return None
    data: dict[str, Any] = {
        "duplicate": info.duplicate,
        "status": info.status,
        "reason_code": info.reason_code,
        "scope": info.scope,
    }
    optional_fields = {
        "match_type": info.match_type,
        "reason_codes": list(info.reason_codes) if info.reason_codes else None,
        "recommended_action": info.recommended_action,
        "source_label": info.source_label,
        "target_label": info.target_label,
        "duplicate_of_asset_id": info.duplicate_of_asset_id,
        "duplicate_of_job_id": info.duplicate_of_job_id,
        "suggestion_id": info.suggestion_id,
        "suggestion_status": info.suggestion_status,
        "storage_key_reused": info.storage_key_reused,
        "blob_written": info.blob_written,
        "temporary_blob_cleaned_up": info.temporary_blob_cleaned_up,
        "artifact_count": info.artifact_count,
    }
    data.update({key: value for key, value in optional_fields.items() if value is not None})
    return data


def asset_extraction_to_response(
    job: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "asset_id": str(job.asset_id),
        "space_id": str(job.space_id),
        "memory_scope_id": str(job.memory_scope_id),
        "thread_id": str(job.thread_id) if job.thread_id else None,
        "parser_profile": job.parser_profile,
        "parser_config_hash": job.parser_config_hash,
        "source_sha256_hex": job.source_sha256_hex,
        "status": job.status.value,
        "attempt_count": job.attempt_count,
        "safe_error_code": job.safe_error_code,
        "safe_error_message": safe_public_text(job.safe_error_message)
        if job.safe_error_message
        else None,
        "parser_name": job.parser_name,
        "parser_version": job.parser_version,
        "model_version": job.model_version,
        "result_document_ids": list(job.result_document_ids),
        "metadata": _safe_metadata(job.metadata),
        "progress": _extraction_progress(job),
        "execution": _extraction_execution(job, now=now),
        "usage": _extraction_usage(job),
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def asset_extraction_error_to_response(error: Any) -> dict[str, Any]:
    return {
        "code": error.code,
        "message": _safe_public_error_message(error),
        "retryable": error.retryable,
    }


def _extraction_execution(
    job: Any,
    *,
    now: datetime | None,
) -> dict[str, Any]:
    lease_state = _lease_state(job, now=now)
    available_actions = _available_extraction_actions(job)
    return {
        "lease_owner": job.lease_owner,
        "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "retry_after_at": job.retry_after_at.isoformat() if job.retry_after_at else None,
        "retry_disposition": job.retry_disposition.value if job.retry_disposition else None,
        "cancellation_requested_at": job.cancellation_requested_at.isoformat()
        if job.cancellation_requested_at
        else None,
        "lease_state": lease_state,
        "lease_seconds_remaining": _lease_seconds_remaining(job, now=now),
        "reclaimable": _lease_reclaimable(job, lease_state=lease_state),
        "retry_actionable": "retry" in available_actions,
        "cancel_actionable": "cancel" in available_actions,
        "available_actions": available_actions,
        "retry_state_reason": _retry_state_reason(job, now=now),
        "cancel_state_reason": _cancel_state_reason(job),
    }


def _available_extraction_actions(job: Any) -> list[str]:
    actions: list[str] = []
    if job.status.value in {"failed", "unsupported", "canceled", "stale"}:
        actions.append("retry")
    if job.status.value in {"pending", "running"} and job.cancellation_requested_at is None:
        actions.append("cancel")
    return actions


def _retry_state_reason(job: Any, *, now: datetime | None) -> str:
    status = job.status.value
    if status in {"pending", "running"}:
        return "job_not_terminal"
    if status == "succeeded":
        return "already_succeeded"
    if status == "failed":
        if job.retry_disposition and job.retry_disposition.value == "permanent":
            return "failed_permanent_requires_fix"
        if (
            job.retry_after_at is not None
            and now is not None
            and _datetime_after(job.retry_after_at, now)
        ):
            return "failed_retryable_backoff_active"
        return "failed_retryable"
    if status == "unsupported":
        return "unsupported_after_provider_or_parser_fix"
    if status == "canceled":
        return "canceled_manual_retry_available"
    if status == "stale":
        return "stale_manual_retry_available"
    return "unknown_status"


def _cancel_state_reason(job: Any) -> str:
    status = job.status.value
    if status == "pending":
        return "pending_cancel_available"
    if status == "running":
        if job.cancellation_requested_at is not None:
            return "cancel_already_requested"
        return "running_cancel_available"
    if status in {"succeeded", "failed", "unsupported", "canceled", "stale"}:
        return "terminal_job"
    return "unknown_status"


def _lease_state(job: Any, *, now: datetime | None) -> str:
    if job.status.value != "running":
        return "none"
    if job.cancellation_requested_at is not None:
        return "cancel_requested"
    if job.lease_expires_at is None:
        return "missing"
    if now is None:
        return "unknown"
    if _datetime_after(job.lease_expires_at, now):
        return "active"
    return "expired"


def _lease_seconds_remaining(job: Any, *, now: datetime | None) -> int | None:
    if job.status.value != "running" or job.lease_expires_at is None or now is None:
        return None
    delta = _comparable_datetime(job.lease_expires_at) - _comparable_datetime(now)
    return max(0, int(delta.total_seconds()))


def _lease_reclaimable(job: Any, *, lease_state: str) -> bool:
    return (
        job.status.value == "running"
        and job.cancellation_requested_at is None
        and lease_state in {"missing", "expired"}
    )


def _datetime_after(left: datetime, right: datetime) -> bool:
    return _comparable_datetime(left) > _comparable_datetime(right)


def _comparable_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.replace(tzinfo=None)


def _extraction_progress(job: Any) -> dict[str, Any]:
    metadata = job.metadata
    fallback_percent = {
        "pending": 0,
        "running": 10,
        "succeeded": 100,
        "failed": 100,
        "unsupported": 100,
        "canceled": 100,
        "stale": 0,
    }.get(job.status.value, 0)
    percent = _progress_int(metadata.get("progress_percent"), fallback=fallback_percent)
    stage = safe_public_text(str(metadata.get("processing_stage") or job.status.value), limit=120)
    message = safe_public_text(
        str(metadata.get("progress_message") or _progress_message(job.status.value))
    )
    return {
        "stage": stage,
        "percent": percent,
        "message": message,
        "terminal": job.status.value in {"succeeded", "failed", "unsupported", "canceled", "stale"},
    }


def _extraction_usage(job: Any) -> dict[str, Any]:
    metadata = job.metadata
    requested = _non_negative_int(
        metadata.get("usage_media_analysis_seconds_requested"),
        fallback=0,
    )
    actual = _non_negative_int(
        metadata.get("usage_media_analysis_seconds_actual"),
        fallback=0,
    )
    final = _non_negative_int(
        metadata.get("usage_media_analysis_seconds_final"),
        fallback=requested,
    )
    return {
        "plan_tier": metadata.get("usage_plan_tier"),
        "media_analysis_seconds_requested": requested,
        "media_analysis_seconds_actual": actual,
        "media_analysis_seconds_delta": _signed_int(
            metadata.get("usage_media_analysis_seconds_delta"),
            fallback=0,
        ),
        "media_analysis_seconds_final": final,
        "reconciled": _bool_value(metadata.get("usage_reconciled"), fallback=False),
        "media_analysis_seconds_limit": _non_negative_int(
            metadata.get("usage_media_analysis_seconds_limit"),
            fallback=0,
        ),
        "media_analysis_seconds_used_before_request": _non_negative_int(
            metadata.get("usage_media_analysis_seconds_used"),
            fallback=0,
        ),
        "media_analysis_seconds_remaining_before_request": _non_negative_int(
            metadata.get("usage_media_analysis_seconds_remaining"),
            fallback=0,
        ),
        "window_start": metadata.get("usage_window_start"),
        "window_end": metadata.get("usage_window_end"),
    }


def _progress_int(value: object, *, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        number = int(float(str(value)))
    except (TypeError, ValueError):
        return fallback
    return max(0, min(number, 100))


def _non_negative_int(value: object, *, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        number = int(float(str(value)))
    except (TypeError, ValueError):
        return fallback
    return max(0, number)


def _signed_int(value: object, *, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return fallback


def _bool_value(value: object, *, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return fallback


def _progress_message(status_value: str) -> str:
    return {
        "pending": "Waiting for extraction worker",
        "running": "Extraction is running",
        "succeeded": "Extraction complete",
        "failed": "Extraction failed",
        "unsupported": "Asset type is unsupported",
        "canceled": "Extraction was canceled",
        "stale": "Extraction is stale",
    }.get(status_value, "Extraction status is unknown")


def extraction_artifact_to_response(artifact: Any) -> dict[str, Any]:
    artifact_id = str(artifact.id)
    return {
        "id": artifact_id,
        "job_id": str(artifact.job_id),
        "asset_id": str(artifact.asset_id),
        "artifact_type": artifact.artifact_type.value,
        "storage_backend": artifact.storage_backend,
        "download_path": f"/v1/extraction-artifacts/{artifact_id}/download",
        "sha256_hex": artifact.sha256_hex,
        "byte_size": artifact.byte_size,
        "metadata": _safe_metadata(artifact.metadata),
        "created_at": artifact.created_at.isoformat(),
    }


def _safe_metadata(metadata: Any) -> dict[str, Any]:
    return safe_public_metadata(metadata)


def _safe_public_error_message(error: Exception) -> str:
    return safe_public_text(str(error).strip() or error.__class__.__name__)


__all__ = (
    "asset_extraction_error_to_response",
    "asset_extraction_to_response",
    "asset_to_response",
    "deduplication_to_response",
    "extraction_artifact_to_response",
)
