"""Asset use cases."""

from __future__ import annotations

import hashlib
import re

from memo_stack_core.application.dto import (
    AssetResult,
    CreateAssetCommand,
    DeleteAssetCommand,
    GetAssetQuery,
    ListAssetsQuery,
)
from memo_stack_core.domain.assets import AssetStatus, MemoryAsset, MemoryAssetId
from memo_stack_core.domain.errors import (
    MemoryConflictError,
    MemoryIngressLimitError,
    MemoryNotFoundError,
)
from memo_stack_core.ports.assets import BlobStoragePort
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort

_MAX_FILENAME_CHARS = 240
_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class CreateAssetUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        blob_storage: BlobStoragePort,
        storage_backend: str = "local",
        max_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._blob_storage = blob_storage
        self._storage_backend = storage_backend
        self._max_bytes = max(1, max_bytes)

    async def execute(self, command: CreateAssetCommand) -> AssetResult:
        if not command.content:
            raise MemoryIngressLimitError("Asset content is empty")
        if len(command.content) > self._max_bytes:
            raise MemoryIngressLimitError("Asset exceeds configured upload limit")
        now = self._clock.now()
        digest = hashlib.sha256(command.content).hexdigest()
        async with self._uow_factory() as uow:
            existing = await uow.assets.find_stored_by_sha256(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=str(command.thread_id) if command.thread_id else None,
                sha256_hex=digest,
            )
            if existing is not None:
                return AssetResult(asset=existing, duplicate=True)

        asset_id = MemoryAssetId(self._ids.new_id("asset"))
        storage_key = _storage_key(
            space_id=str(command.space_id),
            memory_scope_id=str(command.memory_scope_id),
            digest=digest,
            filename=command.filename,
        )
        await self._blob_storage.write_bytes(storage_key=storage_key, content=command.content)
        asset = MemoryAsset.create(
            asset_id=asset_id,
            space_id=command.space_id,
            memory_scope_id=command.memory_scope_id,
            thread_id=command.thread_id,
            filename=command.filename,
            content_type=command.content_type,
            byte_size=len(command.content),
            sha256_hex=digest,
            storage_backend=self._storage_backend,
            storage_key=storage_key,
            classification=command.classification,
            metadata=command.metadata,
            now=now,
        )
        try:
            async with self._uow_factory() as uow:
                existing = await uow.assets.find_stored_by_sha256(
                    space_id=str(command.space_id),
                    memory_scope_id=str(command.memory_scope_id),
                    thread_id=str(command.thread_id) if command.thread_id else None,
                    sha256_hex=digest,
                )
                if existing is not None:
                    await uow.commit()
                    await self._delete_blob_if_unreferenced(storage_key=storage_key)
                    return AssetResult(asset=existing, duplicate=True)
                saved = await uow.assets.create(asset)
                await uow.commit()
        except MemoryConflictError:
            await self._delete_blob_if_unreferenced(storage_key=storage_key)
            raise
        return AssetResult(asset=saved)

    async def _delete_blob_if_unreferenced(self, *, storage_key: str) -> None:
        async with self._uow_factory() as uow:
            has_reference = await uow.assets.has_stored_with_storage_key(storage_key=storage_key)
        if not has_reference:
            await self._blob_storage.delete(storage_key=storage_key)


class GetAssetUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: GetAssetQuery) -> MemoryAsset | None:
        async with self._uow_factory() as uow:
            return await uow.assets.get_by_id(query.asset_id)


class ListAssetsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListAssetsQuery) -> list[MemoryAsset]:
        async with self._uow_factory() as uow:
            return await uow.assets.list_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                thread_id=str(query.thread_id) if query.thread_id else None,
                status=query.status,
                limit=query.limit,
                cursor_created_at=query.cursor_created_at,
                cursor_id=query.cursor_id,
            )


class DeleteAssetUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        blob_storage: BlobStoragePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._blob_storage = blob_storage

    async def execute(self, command: DeleteAssetCommand) -> AssetResult:
        now = self._clock.now()
        should_delete_blob = False
        async with self._uow_factory() as uow:
            asset = await uow.assets.get_by_id(command.asset_id)
            if asset is None:
                raise MemoryNotFoundError("Asset not found")
            storage_key = asset.storage_key
            saved = await uow.assets.save(asset.delete(now=now))
            should_delete_blob = not await uow.assets.has_stored_with_storage_key(
                storage_key=storage_key,
                excluding_asset_id=str(asset.id),
            )
            await uow.commit()
        if should_delete_blob:
            await self._blob_storage.delete(storage_key=storage_key)
        return AssetResult(asset=saved)


class ReadAssetBytesUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        blob_storage: BlobStoragePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._blob_storage = blob_storage

    async def execute(self, query: GetAssetQuery) -> tuple[MemoryAsset, bytes]:
        async with self._uow_factory() as uow:
            asset = await uow.assets.get_by_id(query.asset_id)
        if asset is None or asset.status != AssetStatus.STORED:
            raise MemoryNotFoundError("Asset not found")
        return asset, await self._blob_storage.read_bytes(storage_key=asset.storage_key)


def _storage_key(*, space_id: str, memory_scope_id: str, digest: str, filename: str) -> str:
    safe_name = _safe_filename(filename)
    return f"{space_id}/{memory_scope_id}/{digest[:2]}/{digest}/{safe_name}"


def _safe_filename(filename: str) -> str:
    value = _SAFE_FILENAME_PATTERN.sub("_", filename.strip())[:_MAX_FILENAME_CHARS]
    return value.strip("._") or "asset.bin"
