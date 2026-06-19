"""Ports for binary asset storage and context links."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from infinity_context_core.domain.assets import (
    MemoryAsset,
    MemoryContextLink,
    MemoryContextLinkSuggestion,
)


@dataclass(frozen=True)
class StoredBlob:
    storage_key: str
    byte_size: int


@dataclass(frozen=True)
class StoredBlobObject:
    storage_key: str
    byte_size: int | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class StoredBlobReference:
    source_type: str
    source_id: str
    storage_backend: str
    storage_key: str
    sha256_hex: str
    byte_size: int
    created_at: datetime


@dataclass(frozen=True)
class StoredBlobPage:
    objects: tuple[StoredBlobObject, ...]
    next_cursor: str | None = None


class BlobStoragePort(Protocol):
    async def write_bytes(self, *, storage_key: str, content: bytes) -> StoredBlob:
        """Write a blob under a logical storage key."""

    async def read_bytes(self, *, storage_key: str) -> bytes:
        """Read a blob by logical storage key."""

    async def delete(self, *, storage_key: str) -> None:
        """Delete a blob if it exists."""


class BlobStorageMaintenancePort(BlobStoragePort, Protocol):
    async def stat_object(self, *, storage_key: str) -> StoredBlobObject:
        """Read metadata for one blob without loading full content when supported."""

    async def list_objects(
        self,
        *,
        prefix: str = "",
        limit: int = 500,
        cursor: str | None = None,
    ) -> StoredBlobPage:
        """List provider-neutral blob objects under a logical storage key prefix."""


class AssetRepositoryPort(Protocol):
    async def create(self, asset: MemoryAsset) -> MemoryAsset:
        """Persist an asset metadata row."""

    async def save(self, asset: MemoryAsset) -> MemoryAsset:
        """Persist asset metadata changes."""

    async def get_by_id(self, asset_id: str) -> MemoryAsset | None:
        """Load asset metadata by id."""

    async def find_stored_by_sha256(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        sha256_hex: str,
    ) -> MemoryAsset | None:
        """Find a stored asset duplicate in the same thread context."""

    async def find_any_stored_by_sha256(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        storage_backend: str,
        sha256_hex: str,
    ) -> MemoryAsset | None:
        """Find any stored asset duplicate in the same memory scope and storage backend."""

    async def has_stored_with_storage_key(
        self,
        *,
        storage_key: str,
        excluding_asset_id: str | None = None,
    ) -> bool:
        """Check whether a stored asset still references a blob storage key."""

    async def list_stored_storage_keys(
        self,
        *,
        storage_backend: str,
        storage_keys: tuple[str, ...],
    ) -> set[str]:
        """Return storage keys referenced by active stored assets."""

    async def list_stored_blob_references(
        self,
        *,
        storage_backend: str,
        prefix: str,
        limit: int,
    ) -> list[StoredBlobReference]:
        """List active asset blob references for storage maintenance."""

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[MemoryAsset]:
        """List asset metadata rows for one scope."""


class ContextLinkRepositoryPort(Protocol):
    async def create(self, link: MemoryContextLink) -> MemoryContextLink:
        """Persist a context link."""

    async def save(self, link: MemoryContextLink) -> MemoryContextLink:
        """Persist context link changes."""

    async def get_by_id(self, context_link_id: str) -> MemoryContextLink | None:
        """Load context link by id."""

    async def find_active(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relation_type: str,
    ) -> MemoryContextLink | None:
        """Find an active link for idempotent link creation."""

    async def list_for_source(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        source_type: str,
        source_id: str,
        status: str | None,
        limit: int,
        statuses: tuple[str, ...] | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
    ) -> list[MemoryContextLink]:
        """List links from one source object."""

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
        limit: int,
        statuses: tuple[str, ...] | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
    ) -> list[MemoryContextLink]:
        """List relation history for one memory scope."""


class ContextLinkSuggestionRepositoryPort(Protocol):
    async def create(
        self,
        suggestion: MemoryContextLinkSuggestion,
    ) -> MemoryContextLinkSuggestion:
        """Persist a context link suggestion."""

    async def save(
        self,
        suggestion: MemoryContextLinkSuggestion,
    ) -> MemoryContextLinkSuggestion:
        """Persist context link suggestion changes."""

    async def get_by_id(
        self,
        suggestion_id: str,
    ) -> MemoryContextLinkSuggestion | None:
        """Load a context link suggestion by id."""

    async def find_pending(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relation_type: str,
    ) -> MemoryContextLinkSuggestion | None:
        """Find a pending suggestion for idempotent suggestion creation."""

    async def find_latest_for_pair(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relation_type: str,
    ) -> MemoryContextLinkSuggestion | None:
        """Find the latest suggestion for one source/target/relation pair."""

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
        limit: int,
        source_type: str | None = None,
        source_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> list[MemoryContextLinkSuggestion]:
        """List context link suggestions in a scope."""

    async def count_by_status_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
    ) -> dict[str, int]:
        """Count context link suggestions by review status for one memory scope."""
