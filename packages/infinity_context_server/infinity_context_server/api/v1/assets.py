"""Asset upload and download API."""

from __future__ import annotations

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
from infinity_context_core.domain.assets import AssetStatus
from infinity_context_core.domain.errors import (
    MemoryIngressLimitError,
    MemoryQuotaExceededError,
    MemoryValidationError,
)
from infinity_context_core.domain.extraction import ExtractionArtifact

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.api.v1.scope_resolution import (
    resolve_existing_single_scope,
    resolve_single_scope,
)
from infinity_context_server.composition import Container
from infinity_context_server.features.document_ingestion import public as document_ingestion_server

asset_extraction_to_response = document_ingestion_server.asset_extraction_to_response
asset_to_response = document_ingestion_server.asset_to_response
deduplication_to_response = document_ingestion_server.deduplication_to_response
extraction_artifact_to_response = document_ingestion_server.extraction_artifact_to_response

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
    data: dict[str, Any] = {
        **document_ingestion_server.asset_to_response(result.asset),
        "duplicate": result.duplicate,
        "deduplication": document_ingestion_server.deduplication_to_response(
            result.deduplication
        ),
    }
    if extract:
        _ensure_extraction_enabled(container)
        try:
            extraction = await container.request_asset_extraction.execute(
                RequestAssetExtractionCommand(
                    asset_id=str(result.asset.id),
                    parser_profile=parser_profile,
                )
            )
            data["extraction"] = document_ingestion_server.asset_extraction_to_response(
                extraction.job,
                now=container.clock.now(),
            )
            data["extraction"]["duplicate"] = extraction.duplicate
            data["extraction"]["indexing_status"] = extraction.indexing_status
            data["extraction"]["deduplication"] = (
                document_ingestion_server.deduplication_to_response(
                    extraction.deduplication
                )
            )
        except MemoryQuotaExceededError as exc:
            data["extraction_error"] = (
                document_ingestion_server.asset_extraction_error_to_response(exc)
            )
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
    return {
        "data": [
            document_ingestion_server.asset_to_response(asset) for asset in assets
        ]
    }


@router.get("/assets/{asset_id}")
async def get_asset(
    asset_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    asset = await container.get_asset.execute(GetAssetQuery(asset_id=asset_id))
    if asset is None:
        return {"data": None}
    return {"data": document_ingestion_server.asset_to_response(asset)}


@router.delete("/assets/{asset_id}")
async def delete_asset(
    asset_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.delete_asset.execute(DeleteAssetCommand(asset_id=asset_id))
    return {"data": document_ingestion_server.asset_to_response(result.asset)}


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
            **document_ingestion_server.asset_extraction_to_response(
                result.job,
                now=container.clock.now(),
            ),
            "duplicate": result.duplicate,
            "indexing_status": result.indexing_status,
            "deduplication": document_ingestion_server.deduplication_to_response(
                result.deduplication
            ),
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
    return {
        "data": [
            document_ingestion_server.asset_extraction_to_response(job, now=now)
            for job in result.jobs
        ]
    }


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
    return {
        "data": [
            document_ingestion_server.asset_extraction_to_response(job, now=now)
            for job in result.jobs
        ]
    }


@router.get("/asset-extractions/{job_id}")
async def get_asset_extraction(
    job_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    result = await container.get_asset_extraction.execute(GetAssetExtractionQuery(job_id=job_id))
    return {
        "data": {
            **document_ingestion_server.asset_extraction_to_response(
                result.job,
                now=container.clock.now(),
            ),
            "artifacts": [
                document_ingestion_server.extraction_artifact_to_response(item)
                for item in result.artifacts
            ],
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
    return {
        "data": document_ingestion_server.asset_extraction_to_response(
            result.job,
            now=container.clock.now(),
        )
    }


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
    return {
        "data": document_ingestion_server.asset_extraction_to_response(
            result.job,
            now=container.clock.now(),
        )
    }


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
