"""Read port for canonical temporal fact selection."""

from __future__ import annotations

from typing import Protocol

from infinity_context_core.features.memory_facts.domain import (
    FactSupersessionRelation,
    MemoryFactSelectionQuery,
    MemoryFactSnapshot,
)


class MemoryFactSelectionPort(Protocol):
    async def find_eligible(
        self,
        query: MemoryFactSelectionQuery,
    ) -> tuple[MemoryFactSnapshot, ...]:
        """Filter canonical facts before the requested candidate limit."""

    async def find_current_supersessions(
        self,
        query: MemoryFactSelectionQuery,
    ) -> tuple[FactSupersessionRelation, ...]:
        """Load audited, effective successor edges for requested predecessor ids."""


__all__ = ("MemoryFactSelectionPort",)
