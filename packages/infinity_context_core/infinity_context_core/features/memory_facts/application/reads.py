"""Feature-owned query handlers for canonical administrative fact reads."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.memory_facts.domain import MemoryFactSnapshot
from infinity_context_core.features.memory_facts.ports.read_models import (
    MemoryFactListSpec,
    MemoryFactReadModelPort,
)


@dataclass(frozen=True, slots=True)
class GetMemoryFactHandler:
    reads: MemoryFactReadModelPort

    async def execute(self, fact_id: str) -> MemoryFactSnapshot:
        fact = await self.reads.get_by_id(fact_id)
        if fact is None:
            raise LookupError(f"Memory fact not found: {fact_id}")
        return fact

    async def get_many(self, fact_ids: tuple[str, ...]) -> tuple[MemoryFactSnapshot, ...]:
        return await self.reads.get_many_by_ids(fact_ids)


@dataclass(frozen=True, slots=True)
class ListMemoryFactsHandler:
    reads: MemoryFactReadModelPort

    async def execute(self, spec: MemoryFactListSpec) -> tuple[MemoryFactSnapshot, ...]:
        return await self.reads.list_for_scope(spec)


@dataclass(frozen=True, slots=True)
class ListMemoryFactVersionsHandler:
    reads: MemoryFactReadModelPort

    async def execute(self, fact_id: str) -> tuple[MemoryFactSnapshot, ...]:
        versions = await self.reads.list_versions_by_id(fact_id)
        if not versions:
            raise LookupError(f"Memory fact not found: {fact_id}")
        return versions


@dataclass(frozen=True, slots=True)
class MemoryFactReadUseCases:
    get_fact: GetMemoryFactHandler
    list_facts: ListMemoryFactsHandler
    list_versions: ListMemoryFactVersionsHandler


__all__ = (
    "GetMemoryFactHandler",
    "ListMemoryFactVersionsHandler",
    "ListMemoryFactsHandler",
    "MemoryFactReadUseCases",
)
