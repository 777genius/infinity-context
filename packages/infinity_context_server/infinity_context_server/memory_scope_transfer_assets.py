"""Asset metadata and blob helpers for MemoryScope snapshot transfer."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from hashlib import sha256
from typing import Any

from infinity_context_adapters.postgres.models import MemoryAssetRow
from infinity_context_core.application.safe_payload import safe_metadata
from infinity_context_core.ports.assets import BlobStoragePort

from infinity_context_server.memory_scope_transfer_support import asset_storage_key

ASSET_BLOB_ENCODING = "base64"


class MemoryScopeAssetBlobError(RuntimeError):
    def __init__(self, *, reason: str, asset_id: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.asset_id = asset_id


def asset_to_json(row: MemoryAssetRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "filename": row.filename,
        "content_type": row.content_type,
        "byte_size": row.byte_size,
        "sha256_hex": row.sha256_hex,
        "storage_backend": row.storage_backend,
        "storage_key": row.storage_key,
        "status": row.status,
        "classification": row.classification,
        "metadata_json": safe_metadata(row.metadata_json),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def asset_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> MemoryAssetRow:
    return MemoryAssetRow(
        id=str(item["id"]),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=str(item["thread_id"]) if item.get("thread_id") else None,
        filename=str(item.get("filename") or item["id"])[:240],
        content_type=str(item.get("content_type") or "application/octet-stream")[:120],
        byte_size=int(item.get("byte_size") or 0),
        sha256_hex=str(item.get("sha256_hex") or ""),
        storage_backend=str(item.get("storage_backend") or "local")[:80],
        storage_key=str(item.get("storage_key") or item["id"])[:500],
        status=str(item.get("status", "stored")),
        classification=str(item.get("classification", "unknown"))[:40],
        metadata_json=safe_metadata(item.get("metadata_json") or item.get("metadata") or {}),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
    )


def remap_asset(
    item: dict[str, Any],
    *,
    asset_id_map: dict[str, str],
    thread_id_map: dict[str, str],
    space_id: str,
    memory_scope_id: str,
) -> dict[str, Any]:
    asset_id = str(item["id"])
    mapped_id = asset_id_map.get(asset_id, asset_id)
    thread_id = item.get("thread_id")
    mapped_thread_id = (
        thread_id_map.get(str(thread_id), str(thread_id)) if thread_id is not None else None
    )
    digest = str(item.get("sha256_hex") or "")
    filename = str(item.get("filename") or mapped_id)
    return {
        **item,
        "id": mapped_id,
        "thread_id": mapped_thread_id,
        "storage_backend": str(item.get("storage_backend") or "local"),
        "storage_key": asset_storage_key(
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            digest=digest,
            filename=filename,
        ),
    }


async def asset_blobs_to_json(
    *,
    assets: list[MemoryAssetRow],
    blob_storage: BlobStoragePort | None,
    redacted: bool,
) -> list[dict[str, Any]]:
    if redacted or blob_storage is None:
        return []
    blobs: list[dict[str, Any]] = []
    for asset in assets:
        if asset.status != "stored":
            continue
        try:
            content = await blob_storage.read_bytes(storage_key=asset.storage_key)
        except (FileNotFoundError, OSError) as exc:
            raise MemoryScopeAssetBlobError(
                reason="asset_blob_unavailable",
                asset_id=asset.id,
            ) from exc
        digest = sha256(content).hexdigest()
        if digest != asset.sha256_hex or len(content) != asset.byte_size:
            raise MemoryScopeAssetBlobError(
                reason="asset_blob_integrity_mismatch",
                asset_id=asset.id,
            )
        blobs.append(
            {
                "asset_id": asset.id,
                "encoding": ASSET_BLOB_ENCODING,
                "sha256_hex": digest,
                "byte_size": len(content),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    return blobs


def asset_blob_by_id(asset_blobs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(blob.get("asset_id")): blob for blob in asset_blobs if blob.get("asset_id") is not None
    }


def asset_blob_ids(asset_blobs: list[dict[str, Any]]) -> set[str]:
    return set(asset_blob_by_id(asset_blobs))


def decode_asset_blob(*, asset: dict[str, Any], blob: dict[str, Any]) -> bytes:
    asset_id = str(asset["id"])
    if blob.get("encoding") != ASSET_BLOB_ENCODING:
        raise MemoryScopeAssetBlobError(reason="asset_blob_encoding_unsupported", asset_id=asset_id)
    try:
        content = base64.b64decode(str(blob.get("content_base64") or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MemoryScopeAssetBlobError(
            reason="asset_blob_invalid_base64",
            asset_id=asset_id,
        ) from exc
    digest = sha256(content).hexdigest()
    if digest != str(asset.get("sha256_hex") or blob.get("sha256_hex") or ""):
        raise MemoryScopeAssetBlobError(reason="asset_blob_integrity_mismatch", asset_id=asset_id)
    if len(content) != int(asset.get("byte_size") or blob.get("byte_size") or 0):
        raise MemoryScopeAssetBlobError(reason="asset_blob_integrity_mismatch", asset_id=asset_id)
    return content


async def write_imported_asset_blob(
    *,
    asset: dict[str, Any],
    blob: dict[str, Any],
    blob_storage: BlobStoragePort,
) -> None:
    content = decode_asset_blob(asset=asset, blob=blob)
    await blob_storage.write_bytes(storage_key=str(asset["storage_key"]), content=content)


def _parse_dt(value: object, fallback: datetime) -> datetime:
    if not isinstance(value, str):
        return fallback
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return fallback
