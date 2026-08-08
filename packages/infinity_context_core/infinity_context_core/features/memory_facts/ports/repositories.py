"""Repository ports owned by the memory_facts feature."""

from __future__ import annotations

from typing import Protocol

from infinity_context_core.features.memory_facts.domain import (
    MemoryFactIdentity,
    MemoryFactSnapshot,
)


class MemoryFactRepositoryPort(Protocol):
    async def create(self, fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        """Persist a new canonical fact snapshot."""

    async def get(self, identity: MemoryFactIdentity) -> MemoryFactSnapshot | None:
        """Load a canonical fact by feature-owned identity."""

    async def get_for_update(
        self,
        identity: MemoryFactIdentity,
    ) -> MemoryFactSnapshot | None:
        """Load a canonical fact with a write lock when supported."""

    async def get_many_for_update(
        self,
        identities: tuple[MemoryFactIdentity, ...],
    ) -> tuple[MemoryFactSnapshot, ...]:
        """Lock facts in caller-provided deterministic identity order."""

    async def save(self, fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        """Persist a changed canonical fact snapshot."""

    async def list_versions(
        self,
        identity: MemoryFactIdentity,
    ) -> tuple[MemoryFactSnapshot, ...]:
        """Load immutable canonical snapshots in ascending revision order."""


__all__ = ("MemoryFactRepositoryPort",)
