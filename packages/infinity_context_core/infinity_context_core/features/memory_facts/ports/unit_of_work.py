"""Unit-of-work ports owned by the memory_facts feature."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol

from infinity_context_core.features.memory_facts.ports.outbox import (
    MemoryFactOutboxPort,
)
from infinity_context_core.features.memory_facts.ports.repositories import (
    MemoryFactRepositoryPort,
)


class MemoryFactUnitOfWorkPort(Protocol):
    facts: MemoryFactRepositoryPort
    outbox: MemoryFactOutboxPort

    async def __aenter__(self) -> MemoryFactUnitOfWorkPort:
        """Open one canonical fact transaction."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Rollback on errors and release transaction resources."""

    async def commit(self) -> None:
        """Commit canonical fact changes."""

    async def rollback(self) -> None:
        """Rollback canonical fact changes."""


class MemoryFactUnitOfWorkFactoryPort(Protocol):
    def __call__(self) -> MemoryFactUnitOfWorkPort:
        """Create a fresh unit of work for one fact lifecycle command."""


__all__ = ("MemoryFactUnitOfWorkFactoryPort", "MemoryFactUnitOfWorkPort")
