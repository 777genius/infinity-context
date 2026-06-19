"""Local filesystem blob storage adapter."""

from __future__ import annotations

import os
from bisect import bisect_right
from datetime import UTC, datetime
from pathlib import Path

from infinity_context_core.domain.errors import MemoryNotFoundError, MemoryValidationError
from infinity_context_core.ports.assets import StoredBlob, StoredBlobObject, StoredBlobPage


class LocalBlobStorage:
    def __init__(self, *, root_dir: str | Path) -> None:
        self._root = Path(root_dir).expanduser().resolve()

    async def write_bytes(self, *, storage_key: str, content: bytes) -> StoredBlob:
        path = self._path_for_key(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_bytes(content)
        os.replace(tmp_path, path)
        return StoredBlob(storage_key=storage_key, byte_size=len(content))

    async def read_bytes(self, *, storage_key: str) -> bytes:
        path = self._path_for_key(storage_key)
        if not path.exists() or not path.is_file():
            raise MemoryNotFoundError("Asset blob not found")
        return path.read_bytes()

    async def delete(self, *, storage_key: str) -> None:
        path = self._path_for_key(storage_key)
        if path.exists() and path.is_file():
            path.unlink()

    async def stat_object(self, *, storage_key: str) -> StoredBlobObject:
        path = self._path_for_key(storage_key)
        if not path.exists() or not path.is_file():
            raise MemoryNotFoundError("Asset blob not found")
        return self._object_for_path(path)

    async def list_objects(
        self,
        *,
        prefix: str = "",
        limit: int = 500,
        cursor: str | None = None,
    ) -> StoredBlobPage:
        normalized_prefix = self._normalize_list_prefix(prefix)
        safe_limit = max(1, min(limit, 5_000))
        root = self._root
        if normalized_prefix:
            root = self._path_for_key(normalized_prefix)
            if root.is_file():
                candidates = [root]
            elif root.exists():
                candidates = [path for path in root.rglob("*") if path.is_file()]
            else:
                candidates = []
        else:
            candidates = [path for path in self._root.rglob("*") if path.is_file()]

        objects = sorted(
            (self._object_for_path(path) for path in candidates),
            key=lambda item: item.storage_key,
        )
        keys = [item.storage_key for item in objects]
        start = bisect_right(keys, cursor) if cursor else 0
        page_objects = tuple(objects[start : start + safe_limit])
        next_cursor = (
            page_objects[-1].storage_key
            if start + safe_limit < len(objects) and page_objects
            else None
        )
        return StoredBlobPage(objects=page_objects, next_cursor=next_cursor)

    def _path_for_key(self, storage_key: str) -> Path:
        normalized = storage_key.strip().replace("\\", "/")
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            raise MemoryValidationError("Invalid storage key")
        path = (self._root / normalized).resolve()
        if self._root != path and self._root not in path.parents:
            raise MemoryValidationError("Invalid storage key")
        return path

    def _object_for_path(self, path: Path) -> StoredBlobObject:
        stat = path.stat()
        storage_key = path.relative_to(self._root).as_posix()
        return StoredBlobObject(
            storage_key=storage_key,
            byte_size=stat.st_size,
            updated_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )

    def _normalize_list_prefix(self, prefix: str) -> str:
        normalized = prefix.strip().replace("\\", "/").strip("/")
        if not normalized:
            return ""
        self._path_for_key(normalized)
        return normalized
