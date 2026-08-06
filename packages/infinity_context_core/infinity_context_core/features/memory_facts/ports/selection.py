"""Read port for canonical temporal fact selection."""

from __future__ import annotations

from typing import Protocol

from infinity_context_core.features.memory_facts.domain import (
    MemoryFactSelectionQuery,
    MemoryFactSnapshot,
)


class MemoryFactSelectionPort(Protocol):
    async def find_eligible(
        self,
        query: MemoryFactSelectionQuery,
    ) -> tuple[MemoryFactSnapshot, ...]:
        """Filter canonical facts before the requested candidate limit."""


__all__ = ("MemoryFactSelectionPort",)
