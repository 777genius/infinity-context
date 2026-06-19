"""Asset upload and download API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response, status
from infinity_context_core.application import (
    CancelAssetExtractionCommand,
    CreateAssetCommand,
    DeleteAssetCommand,
    GetAssetExtractionQuery,
    GetAssetQuery,
    GetExtractionArtifactQuery,
    ListAssetExtractionsQuery,
    ListAssetsQuery,
    RequestAssetExtractionCommand,
    RetryAssetExtractionCommand,
)
from infinity_context_core.domain.assets import AssetStatus, MemoryAsset
from infinity_context_core.domain.errors import (
    MemoryIngressLimitError,
    MemoryQuotaExceededError,
    MemoryValidationError,
)
from infinity_context_core.domain.extraction import AssetExtractionJob, ExtractionArtifact

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.api.public_payload import safe_public_metadata, safe_public_text
from infinity_context_server.api.v1.scope_resolution import (
    resolve_existing_single_scope,
    resolve_single_scope,
)
from infinity_context_server.composition import Container

router = APIRouter(
    tags=["assets"],
    dependencies=[Depends(require_service_token)],
)


@router.post("/assets", status_code=status.HTTP_201_CREATED)
async def upload_asset(
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    filename: Annotated[str, Query(min_length=1, max_length=240)],
    content_type: Annotated[str | None, Query(max_length=120)] = None,
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    thread_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    thread_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    classification: Annotated[str, Query(max_length=40)] = "unknown",
    estimated_media_seconds: Annotated[int | None, Query(ge=1, le=24 * 3600)] = None,
    extract: bool = False,
    parser_profile: Annotated[str | None, Query(max_length=80)] = None,
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    content = await _read_limited_request_body(
        request,
        max_bytes=container.settings.max_asset_upload_bytes,
    )
    if not content:
        raise MemoryValidationError("Asset content is required")
    scope = await resolve_single_scope(
        container,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        thread_required=False,
    )
    result = await container.create_asset.execute(
        CreateAssetCommand(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            filename=filename,
            content_type=content_type or _request_content_type(request),
            content=content,
            classification=classification,
            metadata={
                "upload_content_type": _request_content_type(request),
                **(
                    {"estimated_media_seconds": estimated_media_seconds}
                    if estimated_media_seconds is not None
                    else {}
                ),
            },
        )
    )
    data: dict[str, Any] = {**asset_to_response(result.asset), "duplicate": result.duplicate}
    if extract:
        _ensure_extraction_enabled(container)
        try:
            extraction = await container.request_asset_extraction.execute(
                RequestAssetExtractionCommand(
                    asset_id=str(result.asset.id),
                    parser_profile=parser_profile,
                )
            )
            data["extraction"] = asset_extraction_to_response(
                extraction.job,
                now=container.clock.now(),
            )
        except MemoryQuotaExceededError as exc:
            data["extraction_error"] = {
                "code": exc.code,
                "message": _safe_public_error_message(exc),
                "retryable": exc.retryable,
            }
    return {"data": data}


@router.get("/assets")
async def list_assets(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    thread_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    thread_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = "stored",
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> dict[str, Any]:
    _validate_asset_status(status_filter)
    scope = await resolve_existing_single_scope(
        container,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        thread_required=False,
    )
    if scope is None:
        return {"data": []}
    assets = await container.list_assets.execute(
        ListAssetsQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            status=status_filter,
            limit=limit,
        )
    )
    return {"data": [asset_to_response(asset) for asset in assets]}


@router.get("/assets/{asset_id}")
async def get_asset(
    asset_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    asset = await container.get_asset.execute(GetAssetQuery(asset_id=asset_id))
    if asset is None:
        return {"data": None}
    return {"data": asset_to_response(asset)}


@router.delete("/assets/{asset_id}")
async def delete_asset(
    asset_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.delete_asset.execute(DeleteAssetCommand(asset_id=asset_id))
    return {"data": asset_to_response(result.asset)}


@router.post("/assets/{asset_id}/extractions", status_code=status.HTTP_202_ACCEPTED)
async def request_asset_extraction(
    asset_id: str,
    container: Annotated[Container, Depends(get_container)],
    parser_profile: Annotated[str | None, Query(max_length=80)] = None,
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    _ensure_extraction_enabled(container)
    result = await container.request_asset_extraction.execute(
        RequestAssetExtractionCommand(asset_id=asset_id, parser_profile=parser_profile)
    )
    return {
        "data": {
            **asset_extraction_to_response(result.job, now=container.clock.now()),
            "duplicate": result.duplicate,
            "indexing_status": result.indexing_status,
        }
    }


@router.get("/assets/{asset_id}/extractions")
async def list_asset_extractions(
    asset_id: str,
    container: Annotated[Container, Depends(get_container)],
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    result = await container.list_asset_extractions.execute(
        ListAssetExtractionsQuery(asset_id=asset_id, status=status_filter, limit=limit)
    )
    now = container.clock.now()
    return {"data": [asset_extraction_to_response(job, now=now) for job in result.jobs]}


@router.get("/asset-extractions")
async def list_scope_asset_extractions(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    thread_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    thread_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    scope = await resolve_existing_single_scope(
        container,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        thread_required=False,
    )
    if scope is None:
        return {"data": []}
    result = await container.list_asset_extractions.execute(
        ListAssetExtractionsQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            status=status_filter,
            limit=limit,
        )
    )
    now = container.clock.now()
    return {"data": [asset_extraction_to_response(job, now=now) for job in result.jobs]}


@router.get("/asset-extractions/{job_id}")
async def get_asset_extraction(
    job_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    result = await container.get_asset_extraction.execute(GetAssetExtractionQuery(job_id=job_id))
    return {
        "data": {
            **asset_extraction_to_response(result.job, now=container.clock.now()),
            "artifacts": [extraction_artifact_to_response(item) for item in result.artifacts],
        }
    }


@router.post("/asset-extractions/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_asset_extraction(
    job_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    _ensure_extraction_enabled(container)
    result = await container.retry_asset_extraction.execute(
        RetryAssetExtractionCommand(job_id=job_id)
    )
    return {"data": asset_extraction_to_response(result.job, now=container.clock.now())}


@router.post("/asset-extractions/{job_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_asset_extraction(
    job_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    _ensure_extraction_enabled(container)
    result = await container.cancel_asset_extraction.execute(
        CancelAssetExtractionCommand(job_id=job_id)
    )
    return {"data": asset_extraction_to_response(result.job, now=container.clock.now())}


@router.get("/extraction-artifacts/{artifact_id}/download")
async def download_extraction_artifact(
    artifact_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    result = await container.read_extraction_artifact_bytes.execute(
        GetExtractionArtifactQuery(artifact_id=artifact_id)
    )
    filename = _safe_download_filename(
        result.artifact.metadata.get("filename"),
        fallback=f"{result.artifact.artifact_type.value}.bin",
    )
    return Response(
        content=result.content,
        media_type=_artifact_content_type(result.artifact),
        headers=_download_headers(filename),
    )


@router.get("/assets/{asset_id}/download")
async def download_asset(
    asset_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    asset, content = await container.read_asset_bytes.execute(GetAssetQuery(asset_id=asset_id))
    filename = _safe_download_filename(asset.filename, fallback="asset.bin")
    return Response(
        content=content,
        media_type=asset.content_type,
        headers=_download_headers(filename),
    )


def asset_to_response(asset: MemoryAsset) -> dict[str, Any]:
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


def asset_extraction_to_response(
    job: AssetExtractionJob,
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


def _extraction_execution(
    job: AssetExtractionJob,
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


def _available_extraction_actions(job: AssetExtractionJob) -> list[str]:
    actions: list[str] = []
    if job.status.value in {"failed", "unsupported", "canceled", "stale"}:
        actions.append("retry")
    if job.status.value in {"pending", "running"} and job.cancellation_requested_at is None:
        actions.append("cancel")
    return actions


def _retry_state_reason(job: AssetExtractionJob, *, now: datetime | None) -> str:
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


def _cancel_state_reason(job: AssetExtractionJob) -> str:
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


def _lease_state(job: AssetExtractionJob, *, now: datetime | None) -> str:
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


def _lease_seconds_remaining(job: AssetExtractionJob, *, now: datetime | None) -> int | None:
    if job.status.value != "running" or job.lease_expires_at is None or now is None:
        return None
    delta = _comparable_datetime(job.lease_expires_at) - _comparable_datetime(now)
    return max(0, int(delta.total_seconds()))


def _lease_reclaimable(job: AssetExtractionJob, *, lease_state: str) -> bool:
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


def _extraction_progress(job: AssetExtractionJob) -> dict[str, Any]:
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


def _extraction_usage(job: AssetExtractionJob) -> dict[str, Any]:
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


def extraction_artifact_to_response(artifact: ExtractionArtifact) -> dict[str, Any]:
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


def _request_content_type(request: Request) -> str:
    return (request.headers.get("content-type") or "application/octet-stream").split(";")[0]


async def _read_limited_request_body(request: Request, *, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise MemoryValidationError("Invalid Content-Length header") from exc
        if declared_size > max_bytes:
            raise MemoryIngressLimitError("Asset exceeds configured upload limit")

    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise MemoryIngressLimitError("Asset exceeds configured upload limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _artifact_content_type(artifact: ExtractionArtifact) -> str:
    content_type = artifact.metadata.get("content_type")
    return content_type if isinstance(content_type, str) else "application/octet-stream"


def _safe_download_filename(value: Any, *, fallback: str) -> str:
    filename = value if isinstance(value, str) and value.strip() else fallback
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in filename.strip())[:240]
    return safe.strip("._") or fallback


def _download_headers(filename: str) -> dict[str, str]:
    return {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Content-Type-Options": "nosniff",
    }


def _validate_asset_status(status_value: str | None) -> None:
    if status_value:
        try:
            AssetStatus(status_value)
        except ValueError as exc:
            raise MemoryValidationError("Unknown asset status") from exc


def _ensure_extraction_enabled(container: Container) -> None:
    if not container.settings.extraction_enabled:
        raise MemoryValidationError("Asset extraction is disabled")


def _safe_metadata(metadata: Any) -> dict[str, Any]:
    return safe_public_metadata(metadata)


def _safe_public_error_message(error: Exception) -> str:
    return safe_public_text(str(error).strip() or error.__class__.__name__)
