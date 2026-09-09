"""Canonical generic relations in the caller's fact transaction."""

from __future__ import annotations

from typing import Protocol

from infinity_context_core.features.memory_facts.domain.fact import (
    MemoryFactScope,
    MemoryFactSnapshot,
)
from infinity_context_core.features.memory_facts.domain.relations import (
    FactRelationSnapshot,
    FactRelationType,
)


class FactRelationRepositoryPort(Protocol):
    async def get(self, relation_id: str, *, scope: MemoryFactScope) -> FactRelationSnapshot | None:
        """Read within the supplied space and memory scope (independent of thread)."""

    async def find_active(
        self, *, source_fact_id: str, target_fact_id: str, relation_type: FactRelationType
    ) -> FactRelationSnapshot | None:
        """Read the directed logical key after canonical fact locks are held."""

    async def create(self, relation: FactRelationSnapshot) -> FactRelationSnapshot:
        """Insert using the existing active logical-key uniqueness boundary."""

    async def save(self, relation: FactRelationSnapshot) -> FactRelationSnapshot:
        """Persist relation lifecycle only; never revise a fact or emit an outbox event."""

    async def get_related_fact(
        self, fact_id: str, *, scope: MemoryFactScope
    ) -> MemoryFactSnapshot | None:
        """Hydrate canonical related evidence within one memory scope."""

    async def list_for_fact(
        self,
        *,
        fact_id: str,
        scope: MemoryFactScope,
        status: str | None,
        limit: int,
        enforce_code_scope: bool = False,
        repository_id: str | None = None,
        code_scope_id: str | None = None,
    ) -> tuple[FactRelationSnapshot, ...]:
        """Order by updated_at/id descending; apply code scope before the row limit."""
