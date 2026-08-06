"""Outbox-safe orchestration across memory_facts and cognitive_memory APIs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from infinity_context_core.features.cognitive_memory.public import (
    CanonicalEvidenceChangedCommand,
    CognitiveProjectionRepositoryPort,
    CognitiveScope,
    InvalidateCognitiveDependenciesHandler,
)
from infinity_context_core.features.memory_facts.public import (
    FactLifecycleStatus,
    MemoryFactIdentity,
    MemoryFactOutboxMessage,
    MemoryFactRepositoryPort,
)


class FactCognitiveInvalidationStatus(StrEnum):
    APPLIED = "applied"
    NO_DEPENDENCIES = "no_dependencies"
    STALE_EVENT_IGNORED = "stale_event_ignored"
    FACT_NOT_FOUND = "fact_not_found"


@dataclass(frozen=True, slots=True)
class FactCognitiveInvalidationResult:
    status: FactCognitiveInvalidationStatus
    invalidated_candidate_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FactCognitiveInvalidationProcess:
    """Never let an old outbox event invalidate dependencies of a newer fact."""

    facts: MemoryFactRepositoryPort
    projections: CognitiveProjectionRepositoryPort

    async def handle(
        self,
        event: MemoryFactOutboxMessage,
    ) -> FactCognitiveInvalidationResult:
        current = await self.facts.get(
            MemoryFactIdentity(fact_id=event.aggregate_id, scope=event.scope)
        )
        if current is None:
            return FactCognitiveInvalidationResult(FactCognitiveInvalidationStatus.FACT_NOT_FOUND)
        if current.visibility.version != event.aggregate_version:
            return FactCognitiveInvalidationResult(
                FactCognitiveInvalidationStatus.STALE_EVENT_IGNORED
            )
        occurred_at = event.occurred_at or current.updated_at
        if occurred_at is None:
            raise ValueError("Fact cognitive invalidation requires event time")
        result = await InvalidateCognitiveDependenciesHandler(self.projections).execute(
            CanonicalEvidenceChangedCommand(
                scope=CognitiveScope(
                    space_id=event.scope.space_id,
                    memory_scope_id=event.scope.memory_scope_id,
                    thread_id=event.scope.thread_id,
                ),
                evidence_type="fact",
                evidence_id=event.aggregate_id,
                current_version=current.visibility.version,
                currently_visible=(current.visibility.status == FactLifecycleStatus.ACTIVE),
                source_event_id=event.message_id,
                occurred_at=occurred_at,
            )
        )
        invalidated_ids = tuple(identity.value for identity in result.invalidated_candidate_ids)
        return FactCognitiveInvalidationResult(
            (
                FactCognitiveInvalidationStatus.APPLIED
                if invalidated_ids
                else FactCognitiveInvalidationStatus.NO_DEPENDENCIES
            ),
            invalidated_ids,
        )


__all__ = (
    "FactCognitiveInvalidationProcess",
    "FactCognitiveInvalidationResult",
    "FactCognitiveInvalidationStatus",
)
