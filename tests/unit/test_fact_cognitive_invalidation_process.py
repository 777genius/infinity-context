"""Outbox ordering checks for fact-to-cognition invalidation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from infinity_context_adapters.features.cognitive_memory.in_memory_projection_store import (
    InMemoryCognitiveProjectionStore,
)
from infinity_context_adapters.features.memory_facts.in_memory_fact_store import (
    create_in_memory_memory_fact_store,
)
from infinity_context_core.features.cognitive_memory.public import (
    CognitiveProjectionState,
)
from infinity_context_core.features.memory_facts.public import (
    FactTemporalExtent,
    MemoryFactIdentity,
    MemoryFactOutboxMessage,
    MemoryFactScope,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    MemoryFactVisibility,
)
from infinity_context_core.processes.fact_cognitive_invalidation import (
    FactCognitiveInvalidationProcess,
    FactCognitiveInvalidationStatus,
)

from tests.cognitive_candidate_test_support import create_cognitive_candidate

NOW = datetime(2026, 8, 5, tzinfo=UTC)


def test_stale_outbox_event_is_ignored_before_newer_version_invalidates() -> None:
    scope = MemoryFactScope("space-1", "scope-1")
    current = _fact(scope=scope, version=2)
    facts = create_in_memory_memory_fact_store((current,))
    projections = InMemoryCognitiveProjectionStore()
    candidate = _candidate(version=1)
    asyncio.run(
        projections.upsert_if_evidence_current(
            candidate,
            current_visible_evidence=candidate.evidence_identities,
            created_at=NOW,
        )
    )
    process = FactCognitiveInvalidationProcess(facts=facts, projections=projections)

    stale_result = asyncio.run(process.handle(_event(scope=scope, version=1)))

    assert stale_result.status is FactCognitiveInvalidationStatus.STALE_EVENT_IGNORED
    assert projections.records[0].state is CognitiveProjectionState.ACTIVE

    current_result = asyncio.run(process.handle(_event(scope=scope, version=2)))

    assert current_result.status is FactCognitiveInvalidationStatus.APPLIED
    assert current_result.invalidated_candidate_ids == (candidate.identity.value,)
    assert projections.records[0].state is CognitiveProjectionState.INVALIDATED


def _fact(*, scope: MemoryFactScope, version: int) -> MemoryFactSnapshot:
    return MemoryFactSnapshot(
        identity=MemoryFactIdentity("fact-1", scope),
        text="Postgres is canonical",
        source_refs=(MemoryFactSourceRef("note", "source-1"),),
        visibility=MemoryFactVisibility(version=version),
        created_at=NOW,
        updated_at=NOW,
        temporal_extent=FactTemporalExtent.ongoing_state(observed_at=NOW),
    )


def _candidate(*, version: int):
    return create_cognitive_candidate(
        version=version,
        content="Postgres is canonical",
    )


def _event(*, scope: MemoryFactScope, version: int) -> MemoryFactOutboxMessage:
    return MemoryFactOutboxMessage(
        message_id=f"event-{version}",
        event_type="fact.updated",
        aggregate_id="fact-1",
        aggregate_version=version,
        scope=scope,
        occurred_at=NOW,
    )
