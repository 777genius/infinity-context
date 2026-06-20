"""Asset use cases."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from infinity_context_core.application.asset_upload_policy import assess_asset_upload
from infinity_context_core.application.dto import (
    AssetResult,
    CreateAssetCommand,
    DeduplicationInfo,
    DeleteAssetCommand,
    GetAssetQuery,
    ListAssetsQuery,
)
from infinity_context_core.application.safe_payload import safe_metadata
from infinity_context_core.domain.assets import (
    AssetStatus,
    ContextLinkSuggestionStatus,
    MemoryAsset,
    MemoryAssetId,
    MemoryContextLinkSuggestion,
    MemoryContextLinkSuggestionId,
)
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryIngressLimitError,
    MemoryNotFoundError,
    MemoryQuotaExceededError,
)
from infinity_context_core.ports.assets import BlobStoragePort
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort, UnitOfWorkPort

_MAX_FILENAME_CHARS = 240
_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
_EXACT_SHA256_MATCH_TYPE = "exact_sha256"
_THREAD_DUPLICATE_REASON_CODES = (
    "exact_sha256",
    "same_thread",
    "existing_asset_reused",
)
_SCOPE_DUPLICATE_REASON_CODES = (
    "exact_sha256",
    "same_memory_scope",
    "blob_reused",
)
_REUSE_EXISTING_ASSET_ACTION = "reuse_existing_asset"
_LINK_DUPLICATE_CONTEXTS_ACTION = "link_duplicate_asset_contexts"


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
        max_image_pixels: int = 50_000_000,
        max_archive_entries: int = 2_000,
        max_archive_uncompressed_bytes: int = 250 * 1024 * 1024,
        max_archive_single_entry_bytes: int = 100 * 1024 * 1024,
        max_archive_compression_ratio: int = 100,
        max_storage_bytes_per_memory_scope: int = 0,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._blob_storage = blob_storage
        self._storage_backend = storage_backend
        self._max_bytes = max(1, max_bytes)
        self._max_image_pixels = max(1, max_image_pixels)
        self._max_archive_entries = max(1, max_archive_entries)
        self._max_archive_uncompressed_bytes = max(1, max_archive_uncompressed_bytes)
        self._max_archive_single_entry_bytes = max(1, max_archive_single_entry_bytes)
        self._max_archive_compression_ratio = max(1, max_archive_compression_ratio)
        self._max_storage_bytes_per_memory_scope = max(0, max_storage_bytes_per_memory_scope)

    async def execute(self, command: CreateAssetCommand) -> AssetResult:
        if not command.content:
            raise MemoryIngressLimitError("Asset content is empty")
        if len(command.content) > self._max_bytes:
            raise MemoryIngressLimitError("Asset exceeds configured upload limit")
        upload_assessment = assess_asset_upload(
            filename=command.filename,
            declared_content_type=command.content_type,
            content=command.content,
            max_image_pixels=self._max_image_pixels,
            max_archive_entries=self._max_archive_entries,
            max_archive_uncompressed_bytes=self._max_archive_uncompressed_bytes,
            max_archive_single_entry_bytes=self._max_archive_single_entry_bytes,
            max_archive_compression_ratio=self._max_archive_compression_ratio,
        )
        now = self._clock.now()
        digest = hashlib.sha256(command.content).hexdigest()
        reusable_asset: MemoryAsset | None = None
        async with self._uow_factory() as uow:
            existing = await uow.assets.find_stored_by_sha256(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=str(command.thread_id) if command.thread_id else None,
                sha256_hex=digest,
            )
            if existing is not None:
                return AssetResult(
                    asset=existing,
                    duplicate=True,
                    deduplication=DeduplicationInfo(
                        duplicate=True,
                        status="exact_asset_match",
                        reason_code="asset_dedup.exact_asset_match",
                        scope="thread",
                        match_type=_EXACT_SHA256_MATCH_TYPE,
                        reason_codes=_THREAD_DUPLICATE_REASON_CODES,
                        recommended_action=_REUSE_EXISTING_ASSET_ACTION,
                        source_label=command.filename,
                        target_label=existing.filename,
                        duplicate_of_asset_id=str(existing.id),
                        storage_key_reused=True,
                        blob_written=False,
                    ),
                )
            reusable_asset = await uow.assets.find_any_stored_by_sha256(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                storage_backend=self._storage_backend,
                sha256_hex=digest,
            )
            if reusable_asset is None and self._max_storage_bytes_per_memory_scope > 0:
                stored_blob_bytes = await uow.assets.sum_stored_blob_bytes(
                    space_id=str(command.space_id),
                    memory_scope_id=str(command.memory_scope_id),
                    storage_backend=self._storage_backend,
                )
                if stored_blob_bytes + len(command.content) > (
                    self._max_storage_bytes_per_memory_scope
                ):
                    raise MemoryQuotaExceededError(
                        "Asset storage quota for memory scope would be exceeded"
                    )

        asset_id = MemoryAssetId(self._ids.new_id("asset"))
        storage_key = (
            reusable_asset.storage_key
            if reusable_asset is not None
            else _storage_key(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                digest=digest,
                filename=command.filename,
            )
        )
        wrote_blob = False
        if reusable_asset is None:
            await self._blob_storage.write_bytes(storage_key=storage_key, content=command.content)
            wrote_blob = True
        metadata = {
            **safe_metadata(command.metadata or {}),
            **upload_assessment.metadata,
        }
        dedupe_suggestion_id: str | None = None
        dedupe_suggestion_status: str | None = None
        if reusable_asset is not None:
            metadata.update(
                {
                    "asset_blob_deduplicated": True,
                    "asset_blob_duplicate_of_asset_id": str(reusable_asset.id),
                    "asset_blob_dedupe_scope": "memory_scope",
                }
            )
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
            metadata=metadata,
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
                    cleaned_up = False
                    if wrote_blob:
                        cleaned_up = await self._delete_blob_if_unreferenced(
                            storage_key=storage_key
                        )
                    return AssetResult(
                        asset=existing,
                        duplicate=True,
                        deduplication=DeduplicationInfo(
                            duplicate=True,
                            status="late_exact_asset_match",
                            reason_code="asset_dedup.late_exact_asset_match",
                            scope="thread",
                            match_type=_EXACT_SHA256_MATCH_TYPE,
                            reason_codes=_THREAD_DUPLICATE_REASON_CODES,
                            recommended_action=_REUSE_EXISTING_ASSET_ACTION,
                            source_label=command.filename,
                            target_label=existing.filename,
                            duplicate_of_asset_id=str(existing.id),
                            storage_key_reused=True,
                            blob_written=wrote_blob,
                            temporary_blob_cleaned_up=cleaned_up,
                        ),
                    )
                saved = await uow.assets.create(asset)
                if reusable_asset is not None:
                    suggestion = await self._ensure_duplicate_asset_suggestion(
                        uow,
                        source=saved,
                        target=reusable_asset,
                        sha256_hex=digest,
                        now=now,
                    )
                    if suggestion is not None:
                        dedupe_suggestion_id = str(suggestion.id)
                        dedupe_suggestion_status = suggestion.status.value
                await uow.commit()
        except MemoryConflictError:
            if wrote_blob:
                await self._delete_blob_if_unreferenced(
                    storage_key=storage_key,
                    suppress_errors=True,
                )
            raise
        except Exception:
            if wrote_blob:
                await self._delete_blob_if_unreferenced(
                    storage_key=storage_key,
                    suppress_errors=True,
                )
            raise
        if reusable_asset is not None:
            deduplication = DeduplicationInfo(
                duplicate=True,
                status="scope_blob_reused",
                reason_code="asset_dedup.scope_blob_reused",
                scope="memory_scope",
                match_type=_EXACT_SHA256_MATCH_TYPE,
                reason_codes=_SCOPE_DUPLICATE_REASON_CODES,
                recommended_action=_LINK_DUPLICATE_CONTEXTS_ACTION,
                source_label=saved.filename,
                target_label=reusable_asset.filename,
                duplicate_of_asset_id=str(reusable_asset.id),
                suggestion_id=dedupe_suggestion_id,
                suggestion_status=dedupe_suggestion_status,
                storage_key_reused=True,
                blob_written=False,
            )
        else:
            deduplication = DeduplicationInfo(
                duplicate=False,
                status="new_blob_stored",
                reason_code="asset_dedup.new_blob_stored",
                scope="none",
                storage_key_reused=False,
                blob_written=True,
            )
        return AssetResult(
            asset=saved,
            duplicate=reusable_asset is not None,
            deduplication=deduplication,
        )

    async def _ensure_duplicate_asset_suggestion(
        self,
        uow: UnitOfWorkPort,
        *,
        source: MemoryAsset,
        target: MemoryAsset,
        sha256_hex: str,
        now: datetime,
    ) -> MemoryContextLinkSuggestion | None:
        existing_link = await uow.context_links.find_active(
            space_id=str(source.space_id),
            memory_scope_id=str(source.memory_scope_id),
            source_type="asset",
            source_id=str(source.id),
            target_type="asset",
            target_id=str(target.id),
            relation_type="duplicates",
        )
        if existing_link is not None:
            return None
        reverse_link = await uow.context_links.find_active(
            space_id=str(source.space_id),
            memory_scope_id=str(source.memory_scope_id),
            source_type="asset",
            source_id=str(target.id),
            target_type="asset",
            target_id=str(source.id),
            relation_type="duplicates",
        )
        if reverse_link is not None:
            return None
        existing = await uow.context_link_suggestions.find_latest_for_pair(
            space_id=str(source.space_id),
            memory_scope_id=str(source.memory_scope_id),
            source_type="asset",
            source_id=str(source.id),
            target_type="asset",
            target_id=str(target.id),
            relation_type="duplicates",
        )
        if existing is not None:
            if existing.status in {
                ContextLinkSuggestionStatus.APPROVED,
                ContextLinkSuggestionStatus.REJECTED,
            }:
                return None
            return existing
        suggestion = MemoryContextLinkSuggestion.create(
            suggestion_id=MemoryContextLinkSuggestionId(self._ids.new_id("ctxlinksug")),
            space_id=source.space_id,
            memory_scope_id=source.memory_scope_id,
            source_type="asset",
            source_id=str(source.id),
            target_type="asset",
            target_id=str(target.id),
            relation_type="duplicates",
            confidence="high",
            reason="Exact same asset bytes already exist in this memory scope",
            score=100.0,
            metadata={
                "dedupe_match_type": _EXACT_SHA256_MATCH_TYPE,
                "dedupe_reason_codes": list(_SCOPE_DUPLICATE_REASON_CODES),
                "sha256_prefix": sha256_hex[:12],
                "source_asset_filename": source.filename,
                "target_asset_filename": target.filename,
                "source_label": source.filename,
                "target_label": target.filename,
                "recommended_action": _LINK_DUPLICATE_CONTEXTS_ACTION,
            },
            now=now,
        )
        return await uow.context_link_suggestions.create(suggestion)

    async def _delete_blob_if_unreferenced(
        self,
        *,
        storage_key: str,
        suppress_errors: bool = False,
    ) -> bool:
        async with self._uow_factory() as uow:
            has_reference = await uow.assets.has_stored_with_storage_key(storage_key=storage_key)
        if not has_reference:
            try:
                await self._blob_storage.delete(storage_key=storage_key)
                return True
            except Exception:
                if not suppress_errors:
                    raise
        return False


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
            extraction_artifacts = await uow.asset_extractions.list_artifacts_for_asset(
                asset_id=str(asset.id)
            )
            saved = await uow.assets.save(asset.delete(now=now))
            should_delete_blob = not await uow.assets.has_stored_with_storage_key(
                storage_key=storage_key,
                excluding_asset_id=str(asset.id),
            )
            await uow.commit()
        if should_delete_blob:
            await self._blob_storage.delete(storage_key=storage_key)
        for artifact in extraction_artifacts:
            await self._blob_storage.delete(storage_key=artifact.storage_key)
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
