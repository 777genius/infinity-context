"""End-to-end policy checks for versioned cognitive dependencies."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from infinity_context_core.features.cognitive_memory.domain.candidate import (
    _create_trusted_cognitive_candidate,
)
from infinity_context_core.features.cognitive_memory.public import (
    CanonicalEvidenceChangedCommand,
    CanonicalEvidenceIdentity,
    CognitiveCandidate,
    CognitiveDerivationOrigin,
    CognitiveEvidenceRef,
    CognitiveKind,
    CognitiveProjectionDependencySet,
    CognitiveProjectionInvalidation,
    CognitiveProjectionState,
    CognitiveProjectionVersion,
    CognitiveScope,
    InvalidateCognitiveDependenciesHandler,
    PersistCognitiveCandidateCommand,
    PersistCognitiveCandidateHandler,
)

NOW = datetime(2026, 8, 5, tzinfo=UTC)


@dataclass(slots=True)
class _ProjectionRecord:
    candidate: CognitiveCandidate
    state: CognitiveProjectionState = CognitiveProjectionState.ACTIVE
    invalidation: CognitiveProjectionInvalidation | None = None


class _ProjectionStore:
    def __init__(self) -> None:
        self.records: list[_ProjectionRecord] = []

    async def upsert_if_evidence_current(
        self,
        candidate: CognitiveCandidate,
        *,
        current_visible_evidence: tuple[CanonicalEvidenceIdentity, ...],
        created_at: datetime,
    ) -> bool:
        del created_at
        if set(candidate.evidence_identities) != set(current_visible_evidence):
            return False
        if not any(record.candidate.identity == candidate.identity for record in self.records):
            self.records.append(_ProjectionRecord(candidate))
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
            and record.candidate.scope == scope
            and any(
                identity.evidence_type == evidence_type and identity.evidence_id == evidence_id
                for identity in record.candidate.evidence_identities
            )
        )

    async def invalidate(self, invalidation: CognitiveProjectionInvalidation) -> bool:
        for record in self.records:
            if record.candidate.identity != invalidation.candidate_id:
                continue
            if record.state is CognitiveProjectionState.INVALIDATED:
                return False
            record.state = CognitiveProjectionState.INVALIDATED
            record.invalidation = invalidation
            return True
        return False


def test_source_version_change_invalidates_dependent_projection_idempotently() -> None:
    store = _ProjectionStore()
    candidate = _candidate(version=3)
    asyncio.run(
        PersistCognitiveCandidateHandler(store).execute(
            PersistCognitiveCandidateCommand(
                candidate=candidate,
                current_visible_evidence=candidate.evidence_identities,
                created_at=NOW,
            )
        )
    )
    command = CanonicalEvidenceChangedCommand(
        scope=candidate.scope,
        evidence_type="fact",
        evidence_id="fact-1",
        current_version=4,
        currently_visible=True,
        source_event_id="fact.updated:fact-1:4",
        occurred_at=NOW,
    )

    first = asyncio.run(InvalidateCognitiveDependenciesHandler(store).execute(command))
    second = asyncio.run(InvalidateCognitiveDependenciesHandler(store).execute(command))

    assert first.invalidated_candidate_ids == (candidate.identity,)
    assert second.invalidated_candidate_ids == ()
    assert store.records[0].state is CognitiveProjectionState.INVALIDATED
    assert store.records[0].invalidation is not None
    assert store.records[0].invalidation.reason_code == "canonical_source_version_changed"


def test_hidden_source_invalidates_even_when_version_did_not_change() -> None:
    store = _ProjectionStore()
    candidate = _candidate(version=3)
    asyncio.run(
        store.upsert_if_evidence_current(
            candidate,
            current_visible_evidence=candidate.evidence_identities,
            created_at=NOW,
        )
    )

    result = asyncio.run(
        InvalidateCognitiveDependenciesHandler(store).execute(
            CanonicalEvidenceChangedCommand(
                scope=candidate.scope,
                evidence_type="fact",
                evidence_id="fact-1",
                current_version=3,
                currently_visible=False,
                source_event_id="fact.disputed:fact-1:4",
                occurred_at=NOW,
            )
        )
    )

    assert result.invalidated_candidate_ids == (candidate.identity,)
    assert store.records[0].invalidation is not None
    assert store.records[0].invalidation.reason_code == "canonical_source_hidden"


def test_stale_candidate_cannot_be_persisted() -> None:
    store = _ProjectionStore()
    candidate = _candidate(version=3)
    current = CanonicalEvidenceIdentity("fact", "fact-1", 4, candidate.scope)

    with pytest.raises(ValueError, match="stale canonical evidence"):
        asyncio.run(
            PersistCognitiveCandidateHandler(store).execute(
                PersistCognitiveCandidateCommand(candidate, (current,), NOW)
            )
        )


def _candidate(*, version: int):
    scope = CognitiveScope("space-1", "scope-1")
    identity = CanonicalEvidenceIdentity("fact", "fact-1", version, scope)
    return _create_trusted_cognitive_candidate(
        scope=scope,
        kind=CognitiveKind.OBSERVATION,
        derivation_origin=CognitiveDerivationOrigin.PROVIDER,
        content="Postgres is the canonical fact store",
        projection_version=CognitiveProjectionVersion("observation-v1"),
        evidence_refs=(CognitiveEvidenceRef(identity, f"fact:fact-1@{version}"),),
        confidence=0.9,
    )
