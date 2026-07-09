"""Unit-of-work ports owned by the memory_scopes feature."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol

from infinity_context_core.features.memory_scopes.ports.repositories import (
    MemoryScopeRepositoryPort,
)


class MemoryScopeUnitOfWorkPort(Protocol):
    memory_scopes: MemoryScopeRepositoryPort

    async def __aenter__(self) -> MemoryScopeUnitOfWorkPort:
        """Open one canonical memory scope transaction."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Rollback on errors and release transaction resources."""

    async def commit(self) -> None:
        """Commit canonical memory scope changes."""

    async def rollback(self) -> None:
        """Rollback canonical memory scope changes."""


class MemoryScopeUnitOfWorkFactoryPort(Protocol):
    def __call__(self) -> MemoryScopeUnitOfWorkPort:
        """Create a fresh unit of work for one memory scope command."""


__all__ = ("MemoryScopeUnitOfWorkFactoryPort", "MemoryScopeUnitOfWorkPort")
