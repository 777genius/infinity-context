"""Asset extraction job and artifact helpers for MemoryScope snapshots."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from hashlib import sha256
from typing import Any

from infinity_context_adapters.postgres.models import (
    MemoryAssetExtractionArtifactRow,
    MemoryAssetExtractionJobRow,
)
from infinity_context_core.application.asset_extraction_mapping import artifact_storage_key
from infinity_context_core.application.safe_payload import safe_metadata, safe_metadata_text
from infinity_context_core.ports.assets import BlobStoragePort
from sqlalchemy.ext.asyncio import AsyncSession

EXTRACTION_ARTIFACT_BLOB_ENCODING = "base64"
_NON_TERMINAL_STATUSES = {"pending", "running"}


class MemoryScopeExtractionArtifactBlobError(RuntimeError):
    def __init__(self, *, reason: str, artifact_id: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.artifact_id = artifact_id


def extraction_job_to_json(row: MemoryAssetExtractionJobRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "asset_id": row.asset_id,
        "thread_id": row.thread_id,
        "parser_profile": row.parser_profile,
        "parser_config_hash": row.parser_config_hash,
        "source_sha256_hex": row.source_sha256_hex,
        "parser_name": _safe_optional_str(row.parser_name, 120),
        "parser_version": _safe_optional_str(row.parser_version, 120),
        "model_version": _safe_optional_str(row.model_version, 120),
        "status": row.status,
        "attempt_count": row.attempt_count,
        "safe_error_code": row.safe_error_code,
        "safe_error_message": _safe_optional_str(row.safe_error_message, 500),
        "result_document_ids": list(row.result_document_ids_json or []),
        "metadata_json": safe_metadata(row.metadata_json),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "lease_owner": row.lease_owner,
        "lease_expires_at": row.lease_expires_at.isoformat() if row.lease_expires_at else None,
        "heartbeat_at": row.heartbeat_at.isoformat() if row.heartbeat_at else None,
        "retry_after_at": row.retry_after_at.isoformat() if row.retry_after_at else None,
        "cancellation_requested_at": (
            row.cancellation_requested_at.isoformat() if row.cancellation_requested_at else None
        ),
        "retry_disposition": row.retry_disposition,
    }


def extraction_job_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> MemoryAssetExtractionJobRow:
    return MemoryAssetExtractionJobRow(
        id=str(item["id"]),
        asset_id=str(item["asset_id"]),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=str(item["thread_id"]) if item.get("thread_id") else None,
        parser_profile=str(item.get("parser_profile") or "standard_local")[:80],
        parser_config_hash=str(item.get("parser_config_hash") or "imported")[:80],
        source_sha256_hex=str(item.get("source_sha256_hex") or "")[:80],
        parser_name=_safe_optional_str(item.get("parser_name"), 120),
        parser_version=_safe_optional_str(item.get("parser_version"), 120),
        model_version=_safe_optional_str(item.get("model_version"), 120),
        status=str(item.get("status") or "stale")[:40],
        attempt_count=int(item.get("attempt_count") or 0),
        safe_error_code=_optional_str(item.get("safe_error_code"), 120),
        safe_error_message=_safe_optional_str(item.get("safe_error_message"), 500),
        result_document_ids_json=[str(value) for value in item.get("result_document_ids") or []],
        metadata_json=safe_metadata(item.get("metadata_json") or item.get("metadata") or {}),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
        started_at=_parse_optional_dt(item.get("started_at")),
        finished_at=_parse_optional_dt(item.get("finished_at")),
        lease_owner=_optional_str(item.get("lease_owner"), 120),
        lease_expires_at=_parse_optional_dt(item.get("lease_expires_at")),
        heartbeat_at=_parse_optional_dt(item.get("heartbeat_at")),
        retry_after_at=_parse_optional_dt(item.get("retry_after_at")),
        cancellation_requested_at=_parse_optional_dt(item.get("cancellation_requested_at")),
        retry_disposition=_optional_str(item.get("retry_disposition"), 40),
    )


def extraction_artifact_to_json(row: MemoryAssetExtractionArtifactRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "asset_id": row.asset_id,
        "artifact_type": row.artifact_type,
        "storage_backend": row.storage_backend,
        "storage_key": row.storage_key,
        "sha256_hex": row.sha256_hex,
        "byte_size": row.byte_size,
        "metadata_json": safe_metadata(row.metadata_json),
        "created_at": row.created_at.isoformat(),
    }


def extraction_artifact_from_json(
    item: dict[str, Any],
    *,
    now: datetime,
) -> MemoryAssetExtractionArtifactRow:
    return MemoryAssetExtractionArtifactRow(
        id=str(item["id"]),
        job_id=str(item["job_id"]),
        asset_id=str(item["asset_id"]),
        artifact_type=str(item.get("artifact_type") or "extracted_json")[:80],
        storage_backend=str(item.get("storage_backend") or "local")[:80],
        storage_key=str(item.get("storage_key") or item["id"])[:500],
        sha256_hex=str(item.get("sha256_hex") or "")[:80],
        byte_size=int(item.get("byte_size") or 0),
        metadata_json=safe_metadata(item.get("metadata_json") or item.get("metadata") or {}),
        created_at=_parse_dt(item.get("created_at"), now),
    )


def remap_extraction_job(
    item: dict[str, Any],
    *,
    extraction_job_id_map: dict[str, str],
    asset_id_map: dict[str, str],
    document_id_map: dict[str, str],
    thread_id_map: dict[str, str],
) -> dict[str, Any]:
    job_id = str(item["id"])
    asset_id = str(item.get("asset_id") or "")
    thread_id = item.get("thread_id")
    mapped = {
        **item,
        "id": extraction_job_id_map.get(job_id, job_id),
        "asset_id": asset_id_map.get(asset_id, asset_id),
        "thread_id": (
            thread_id_map.get(str(thread_id), str(thread_id))
            if thread_id is not None
            else None
        ),
        "result_document_ids": [
            document_id_map.get(str(document_id), str(document_id))
            for document_id in item.get("result_document_ids") or []
        ],
    }
    if str(mapped.get("status") or "") in _NON_TERMINAL_STATUSES:
        metadata = safe_metadata(mapped.get("metadata_json") or mapped.get("metadata") or {})
        mapped.update(
            {
                "status": "stale",
                "safe_error_code": "asset_extraction.imported_non_terminal",
                "safe_error_message": "Imported snapshot had a non-terminal extraction job",
                "lease_owner": None,
                "lease_expires_at": None,
                "heartbeat_at": None,
                "retry_after_at": None,
                "cancellation_requested_at": None,
                "retry_disposition": "retryable",
                "metadata_json": {
                    **metadata,
                    "processing_stage": "stale",
                    "progress_percent": 0,
                    "progress_message": "Imported extraction needs retry",
                },
            }
        )
    return mapped


def remap_extraction_artifact(
    item: dict[str, Any],
    *,
    extraction_artifact_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str],
    asset_id_map: dict[str, str],
    space_id: str,
    memory_scope_id: str,
) -> dict[str, Any]:
    artifact_id = str(item["id"])
    job_id = str(item["job_id"])
    asset_id = str(item["asset_id"])
    mapped_job_id = extraction_job_id_map.get(job_id, job_id)
    metadata = dict(item.get("metadata_json") or item.get("metadata") or {})
    filename = str(metadata.get("filename") or f"{item.get('artifact_type') or 'artifact'}.bin")
    digest = str(item.get("sha256_hex") or "")
    return {
        **item,
        "id": extraction_artifact_id_map.get(artifact_id, artifact_id),
        "job_id": mapped_job_id,
        "asset_id": asset_id_map.get(asset_id, asset_id),
        "storage_backend": str(item.get("storage_backend") or "local"),
        "storage_key": artifact_storage_key(
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            job_id=mapped_job_id,
            digest=digest,
            filename=filename,
        ),
    }


async def import_extraction_rows(
    session: AsyncSession,
    *,
    jobs: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    artifact_blob_map: dict[str, dict[str, Any]],
    skipped: dict[str, set[str]],
    extraction_job_id_map: dict[str, str],
    extraction_artifact_id_map: dict[str, str],
    asset_id_map: dict[str, str],
    document_id_map: dict[str, str],
    thread_id_map: dict[str, str],
    space_id: str,
    memory_scope_id: str,
    now: datetime,
    blob_storage: BlobStoragePort | None,
) -> dict[str, object] | None:
    for job in jobs:
        if str(job["id"]) in skipped["asset_extraction_jobs"]:
            continue
        mapped_job = remap_extraction_job(
            job,
            extraction_job_id_map=extraction_job_id_map,
            asset_id_map=asset_id_map,
            document_id_map=document_id_map,
            thread_id_map=thread_id_map,
        )
        session.add(
            extraction_job_from_json(
                mapped_job,
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                now=now,
            )
        )
    for artifact in artifacts:
        if str(artifact["id"]) in skipped["extraction_artifacts"]:
            continue
        mapped_artifact = remap_extraction_artifact(
            artifact,
            extraction_artifact_id_map=extraction_artifact_id_map,
            extraction_job_id_map=extraction_job_id_map,
            asset_id_map=asset_id_map,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
        )
        if blob_storage is None:
            return {
                "status": "failed",
                "reason": "extraction_artifact_blob_storage_unavailable",
            }
        blob = artifact_blob_map.get(str(artifact["id"]))
        if blob is None:
            return {
                "status": "failed",
                "reason": "extraction_artifact_blob_missing",
                "artifact_id": str(artifact["id"]),
            }
        try:
            await write_imported_extraction_artifact_blob(
                artifact=mapped_artifact,
                blob=blob,
                blob_storage=blob_storage,
            )
        except MemoryScopeExtractionArtifactBlobError as exc:
            return {"status": "failed", "reason": exc.reason, "artifact_id": exc.artifact_id}
        session.add(extraction_artifact_from_json(mapped_artifact, now=now))
    return None


async def extraction_artifact_blobs_to_json(
    *,
    artifacts: list[MemoryAssetExtractionArtifactRow],
    blob_storage: BlobStoragePort | None,
    redacted: bool,
) -> list[dict[str, Any]]:
    if redacted or blob_storage is None:
        return []
    blobs: list[dict[str, Any]] = []
    for artifact in artifacts:
        try:
            content = await blob_storage.read_bytes(storage_key=artifact.storage_key)
        except (FileNotFoundError, OSError) as exc:
            raise MemoryScopeExtractionArtifactBlobError(
                reason="extraction_artifact_blob_unavailable",
                artifact_id=artifact.id,
            ) from exc
        digest = sha256(content).hexdigest()
        if digest != artifact.sha256_hex or len(content) != artifact.byte_size:
            raise MemoryScopeExtractionArtifactBlobError(
                reason="extraction_artifact_blob_integrity_mismatch",
                artifact_id=artifact.id,
            )
        blobs.append(
            {
                "artifact_id": artifact.id,
                "encoding": EXTRACTION_ARTIFACT_BLOB_ENCODING,
                "sha256_hex": digest,
                "byte_size": len(content),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    return blobs


def extraction_artifact_blob_by_id(
    artifact_blobs: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(blob.get("artifact_id")): blob
        for blob in artifact_blobs
        if blob.get("artifact_id") is not None
    }


async def write_imported_extraction_artifact_blob(
    *,
    artifact: dict[str, Any],
    blob: dict[str, Any],
    blob_storage: BlobStoragePort,
) -> None:
    content = decode_extraction_artifact_blob(artifact=artifact, blob=blob)
    await blob_storage.write_bytes(storage_key=str(artifact["storage_key"]), content=content)


def decode_extraction_artifact_blob(*, artifact: dict[str, Any], blob: dict[str, Any]) -> bytes:
    artifact_id = str(artifact["id"])
    if blob.get("encoding") != EXTRACTION_ARTIFACT_BLOB_ENCODING:
        raise MemoryScopeExtractionArtifactBlobError(
            reason="extraction_artifact_blob_encoding_unsupported",
            artifact_id=artifact_id,
        )
    try:
        content = base64.b64decode(str(blob.get("content_base64") or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MemoryScopeExtractionArtifactBlobError(
            reason="extraction_artifact_blob_invalid_base64",
            artifact_id=artifact_id,
        ) from exc
    digest = sha256(content).hexdigest()
    if digest != str(artifact.get("sha256_hex") or blob.get("sha256_hex") or ""):
        raise MemoryScopeExtractionArtifactBlobError(
            reason="extraction_artifact_blob_integrity_mismatch",
            artifact_id=artifact_id,
        )
    if len(content) != int(artifact.get("byte_size") or blob.get("byte_size") or 0):
        raise MemoryScopeExtractionArtifactBlobError(
            reason="extraction_artifact_blob_integrity_mismatch",
            artifact_id=artifact_id,
        )
    return content


def _optional_str(value: object, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _safe_optional_str(value: object, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return safe_metadata_text(text, limit=limit) if text else None


def _parse_dt(value: object, fallback: datetime) -> datetime:
    parsed = _parse_optional_dt(value)
    return parsed or fallback


def _parse_optional_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
