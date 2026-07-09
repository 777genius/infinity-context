"""Repository ports owned by the memory_scopes feature."""

from __future__ import annotations

from typing import Protocol

from infinity_context_core.features.memory_scopes.domain import (
    MemoryScopeIdentity,
    MemoryScopeSnapshot,
)


class MemoryScopeRepositoryPort(Protocol):
    async def create(self, scope: MemoryScopeSnapshot) -> MemoryScopeSnapshot:
        """Persist a new canonical memory scope snapshot."""

    async def get(
        self,
        identity: MemoryScopeIdentity,
    ) -> MemoryScopeSnapshot | None:
        """Load a canonical memory scope by feature-owned identity."""

    async def get_for_update(
        self,
        identity: MemoryScopeIdentity,
    ) -> MemoryScopeSnapshot | None:
        """Load a canonical memory scope with a write lock when supported."""

    async def get_by_external_ref(
        self,
        space_id: str,
        external_ref: str,
    ) -> MemoryScopeSnapshot | None:
        """Load a memory scope by a space-local external reference."""

    async def save(self, scope: MemoryScopeSnapshot) -> MemoryScopeSnapshot:
        """Persist a changed canonical memory scope snapshot."""


__all__ = ("MemoryScopeRepositoryPort",)
