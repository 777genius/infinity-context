"""S3-compatible blob storage adapter."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from infinity_context_core.domain.errors import MemoryNotFoundError, MemoryValidationError
from infinity_context_core.ports.assets import StoredBlob, StoredBlobObject, StoredBlobPage


class S3BlobStorage:
    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        session_token: str | None = None,
        force_path_style: bool = False,
        client: Any | None = None,
    ) -> None:
        safe_bucket = bucket.strip()
        if not safe_bucket:
            raise MemoryValidationError("S3 asset storage bucket is required")
        self._bucket = safe_bucket
        self._prefix = _normalize_prefix(prefix)
        self._client = client or _build_s3_client(
            endpoint_url=endpoint_url,
            region_name=region_name,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
            force_path_style=force_path_style,
        )

    async def write_bytes(self, *, storage_key: str, content: bytes) -> StoredBlob:
        object_key = self._object_key(storage_key)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=object_key,
            Body=content,
        )
        return StoredBlob(storage_key=storage_key, byte_size=len(content))

    async def read_bytes(self, *, storage_key: str) -> bytes:
        object_key = self._object_key(storage_key)
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._bucket,
                Key=object_key,
            )
        except Exception as exc:
            if _is_not_found_error(exc):
                raise MemoryNotFoundError("Asset blob not found") from exc
            raise
        body = response.get("Body")
        if body is None:
            raise MemoryNotFoundError("Asset blob not found")
        try:
            if isinstance(body, bytes):
                return body
            return await asyncio.to_thread(body.read)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    async def delete(self, *, storage_key: str) -> None:
        object_key = self._object_key(storage_key)
        await asyncio.to_thread(
            self._client.delete_object,
            Bucket=self._bucket,
            Key=object_key,
        )

    async def stat_object(self, *, storage_key: str) -> StoredBlobObject:
        object_key = self._object_key(storage_key)
        try:
            response = await asyncio.to_thread(
                self._client.head_object,
                Bucket=self._bucket,
                Key=object_key,
            )
        except Exception as exc:
            if _is_not_found_error(exc):
                raise MemoryNotFoundError("Asset blob not found") from exc
            raise
        return StoredBlobObject(
            storage_key=storage_key,
            byte_size=_optional_int(response.get("ContentLength")),
            updated_at=_optional_datetime(response.get("LastModified")),
        )

    async def list_objects(
        self,
        *,
        prefix: str = "",
        limit: int = 500,
        cursor: str | None = None,
    ) -> StoredBlobPage:
        request: dict[str, object] = {
            "Bucket": self._bucket,
            "Prefix": self._object_prefix(prefix),
            "MaxKeys": max(1, min(limit, 5_000)),
        }
        if cursor:
            request["ContinuationToken"] = cursor
        response = await asyncio.to_thread(self._client.list_objects_v2, **request)
        objects: list[StoredBlobObject] = []
        for item in response.get("Contents", ()):
            stored_object = self._stored_object_from_s3(item)
            if stored_object is not None:
                objects.append(stored_object)
        next_cursor = response.get("NextContinuationToken")
        return StoredBlobPage(
            objects=tuple(objects),
            next_cursor=str(next_cursor) if next_cursor else None,
        )

    def _object_key(self, storage_key: str) -> str:
        normalized = _normalize_storage_key(storage_key)
        return f"{self._prefix}/{normalized}" if self._prefix else normalized

    def _object_prefix(self, prefix: str) -> str:
        normalized = _normalize_list_prefix(prefix)
        if self._prefix and normalized:
            return f"{self._prefix}/{normalized}"
        if self._prefix:
            return f"{self._prefix}/"
        return normalized

    def _logical_storage_key(self, object_key: str) -> str | None:
        if not self._prefix:
            return object_key
        prefix = f"{self._prefix}/"
        if not object_key.startswith(prefix):
            return None
        logical = object_key[len(prefix) :]
        return logical or None

    def _stored_object_from_s3(self, item: object) -> StoredBlobObject | None:
        if not isinstance(item, dict):
            return None
        raw_key = item.get("Key")
        if not isinstance(raw_key, str):
            return None
        storage_key = self._logical_storage_key(raw_key)
        if storage_key is None:
            return None
        raw_size = item.get("Size")
        raw_updated_at = item.get("LastModified")
        return StoredBlobObject(
            storage_key=storage_key,
            byte_size=int(raw_size) if isinstance(raw_size, int) else None,
            updated_at=raw_updated_at if isinstance(raw_updated_at, datetime) else None,
        )


def _build_s3_client(
    *,
    endpoint_url: str | None,
    region_name: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
    session_token: str | None,
    force_path_style: bool,
) -> Any:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("Install infinity-context[s3] to use S3 asset storage") from exc

    config = Config(s3={"addressing_style": "path" if force_path_style else "auto"})
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or None,
        region_name=region_name or None,
        aws_access_key_id=access_key_id or None,
        aws_secret_access_key=secret_access_key or None,
        aws_session_token=session_token or None,
        config=config,
    )


def _normalize_prefix(prefix: str) -> str:
    normalized = prefix.strip().replace("\\", "/").strip("/")
    if not normalized:
        return ""
    if _unsafe_key_parts(normalized):
        raise MemoryValidationError("Invalid S3 asset storage prefix")
    return normalized


def _normalize_storage_key(storage_key: str) -> str:
    normalized = storage_key.strip().replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or "\x00" in normalized
        or any(ord(char) < 32 for char in normalized)
        or _unsafe_key_parts(normalized)
    ):
        raise MemoryValidationError("Invalid storage key")
    return normalized


def _normalize_list_prefix(prefix: str) -> str:
    normalized = prefix.strip().replace("\\", "/").strip("/")
    if not normalized:
        return ""
    return _normalize_storage_key(normalized)


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _optional_datetime(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _unsafe_key_parts(value: str) -> bool:
    return any(part in {"", ".", ".."} for part in value.split("/"))


def _is_not_found_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error")
    if not isinstance(error, dict):
        return False
    code = str(error.get("Code") or "").strip()
    return code in {"NoSuchKey", "NotFound", "404"}
