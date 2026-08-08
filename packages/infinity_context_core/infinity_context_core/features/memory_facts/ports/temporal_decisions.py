"""Persistence boundaries for supersession and temporal decision audit."""

from __future__ import annotations

from typing import Protocol

from infinity_context_core.features.memory_facts.domain import (
    FactSupersessionRelation,
    FactTemporalDecision,
    FactTemporalDecisionType,
    MemoryFactScope,
)


class FactTemporalDecisionRepositoryPort(Protocol):
    async def create(self, decision: FactTemporalDecision) -> FactTemporalDecision:
        """Append one immutable semantic decision."""

    async def get(self, decision_id: str) -> FactTemporalDecision | None:
        """Load one decision for audit or compensation."""

    async def get_by_idempotency_key(
        self,
        *,
        scope: MemoryFactScope,
        decision_type: FactTemporalDecisionType,
        idempotency_key: str,
    ) -> FactTemporalDecision | None:
        """Resolve a retried command without repeating mutations."""

    async def find_compensation(
        self,
        decision_id: str,
    ) -> FactTemporalDecision | None:
        """Return the single append-only decision compensating another decision."""


class FactSupersessionRepositoryPort(Protocol):
    async def create(
        self,
        relation: FactSupersessionRelation,
    ) -> FactSupersessionRelation:
        """Append one immutable supersession relation."""

    async def find_active_successor(
        self,
        *,
        scope: MemoryFactScope,
        predecessor_fact_id: str,
    ) -> FactSupersessionRelation | None:
        """Return the single successor already assigned to a predecessor."""

    async def find_active_predecessor(
        self,
        *,
        scope: MemoryFactScope,
        successor_fact_id: str,
    ) -> FactSupersessionRelation | None:
        """Return the predecessor already replaced by a successor."""

    async def find_by_decision(
        self,
        decision_id: str,
    ) -> FactSupersessionRelation | None:
        """Load the immutable edge created by one audited decision."""

    async def list_active(
        self,
        *,
        scope: MemoryFactScope,
    ) -> tuple[FactSupersessionRelation, ...]:
        """Load active edges for deterministic domain cycle validation."""


__all__ = (
    "FactSupersessionRepositoryPort",
    "FactTemporalDecisionRepositoryPort",
)
