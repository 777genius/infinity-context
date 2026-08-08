"""Application boundary for canonical temporal fact selection."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.memory_facts.domain import (
    MemoryFactSelectionQuery,
    MemoryFactSnapshot,
)
from infinity_context_core.features.memory_facts.ports import MemoryFactSelectionPort


@dataclass(frozen=True, slots=True)
class SelectMemoryFactsHandler:
    """Expose fact selection without leaking repositories across feature boundaries."""

    selection: MemoryFactSelectionPort

    async def execute(
        self,
        query: MemoryFactSelectionQuery,
    ) -> tuple[MemoryFactSnapshot, ...]:
        return await self.selection.find_eligible(query)


__all__ = ("SelectMemoryFactsHandler",)
