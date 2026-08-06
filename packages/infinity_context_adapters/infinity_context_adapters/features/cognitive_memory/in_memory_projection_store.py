"""In-memory derived projection repository for deterministic tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.features.cognitive_memory.public import (
    CanonicalEvidenceIdentity,
    CognitiveCandidate,
    CognitiveProjectionDependencySet,
    CognitiveProjectionInvalidation,
    CognitiveProjectionState,
    CognitiveScope,
)


@dataclass(frozen=True, slots=True)
class InMemoryCognitiveProjectionRecord:
    candidate: CognitiveCandidate
    state: CognitiveProjectionState
    created_at: datetime
    invalidation: CognitiveProjectionInvalidation | None = None


class InMemoryCognitiveProjectionStore:
    """Derived state may mutate, but exact canonical dependencies never do."""

    def __init__(self) -> None:
        self._records: dict[str, InMemoryCognitiveProjectionRecord] = {}

    @property
    def records(self) -> tuple[InMemoryCognitiveProjectionRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    async def upsert_if_evidence_current(
        self,
        candidate: CognitiveCandidate,
        *,
        current_visible_evidence: tuple[CanonicalEvidenceIdentity, ...],
        created_at: datetime,
    ) -> bool:
        if set(candidate.evidence_identities) != set(current_visible_evidence):
            return False
        key = candidate.identity.value
        current = self._records.get(key)
        if current is not None:
            if current.candidate != candidate:
                raise ValueError("Deterministic cognitive identity collision")
            return True
        self._records[key] = InMemoryCognitiveProjectionRecord(
            candidate=candidate,
            state=CognitiveProjectionState.ACTIVE,
            created_at=created_at,
        )
        return True

    async def list_active_dependents(
        self,
        *,
        scope: CognitiveScope,
        evidence_type: str,
        evidence_id: str,
    ) -> tuple[CognitiveProjectionDependencySet, ...]:
        return tuple(
            CognitiveProjectionDependencySet(
                candidate_id=record.candidate.identity,
                scope=record.candidate.scope,
                evidence_identities=record.candidate.evidence_identities,
            )
            for record in self.records
            if record.state is CognitiveProjectionState.ACTIVE
            and record.candidate.scope.space_id == scope.space_id
            and record.candidate.scope.memory_scope_id == scope.memory_scope_id
            and any(
                identity.evidence_type == evidence_type and identity.evidence_id == evidence_id
                for identity in record.candidate.evidence_identities
            )
        )

    async def invalidate(self, invalidation: CognitiveProjectionInvalidation) -> bool:
        key = invalidation.candidate_id.value
        current = self._records.get(key)
        if current is None or current.state is CognitiveProjectionState.INVALIDATED:
            return False
        self._records[key] = InMemoryCognitiveProjectionRecord(
            candidate=current.candidate,
            state=CognitiveProjectionState.INVALIDATED,
            created_at=current.created_at,
            invalidation=invalidation,
        )
        return True


__all__ = (
    "InMemoryCognitiveProjectionRecord",
    "InMemoryCognitiveProjectionStore",
)
