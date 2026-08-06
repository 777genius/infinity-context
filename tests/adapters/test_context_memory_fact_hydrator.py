"""Canonical fact hydration checks for context candidate IDs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from infinity_context_adapters.features.context_building.memory_fact_hydrator import (
    MemoryFactContextHydrator,
)
from infinity_context_adapters.features.memory_facts.in_memory_fact_store import (
    create_in_memory_memory_fact_store,
)
from infinity_context_core.features.context_building.public import (
    ContextCandidateRequest,
    ContextQuery,
    ContextScope,
)
from infinity_context_core.features.memory_facts.public import (
    FactCodeScopeReference,
    FactTemporalExtent,
    MemoryFact,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSourceRef,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


@dataclass(frozen=True)
class _Clock:
    def now(self) -> datetime:
        return NOW


def test_hydrator_revalidates_scope_temporal_state_and_renders_canonical_labels() -> None:
    eligible = _fact("eligible", repository_id="repo-a")
    wrong_repository = _fact("wrong-repository", repository_id="repo-b")
    historical = _fact("historical", repository_id="repo-a")
    historical = replace(
        historical,
        temporal_extent=FactTemporalExtent(
            kind="state",
            observed_at=NOW,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 7, 1, tzinfo=UTC),
            basis="asserted",
            precision="exact",
        ),
    )
    store = create_in_memory_memory_fact_store(
        (eligible.to_snapshot(), wrong_repository.to_snapshot(), historical.to_snapshot())
    )
    hydrator = MemoryFactContextHydrator(facts=store, clock=_Clock())
    request = ContextCandidateRequest(
        query=ContextQuery(
            scope=ContextScope(space_id="space-1", memory_scope_id="scope-1"),
            text="current architecture",
            repository_id="repo-a",
        ),
        limit=3,
    )

    result = asyncio.run(
        hydrator.hydrate_candidates(
            request,
            ("eligible", "wrong-repository", "historical"),
        )
    )

    assert tuple(candidate.canonical_id for candidate in result) == ("eligible",)
    evidence = result[0].item.evidence[0]
    assert evidence.canonical_version == 1
    assert evidence.lifecycle_label == "active"
    assert evidence.temporal_label == "current"
    assert evidence.temporal_assurance == "asserted"
    assert evidence.temporal_reason_codes == ("inside_validity_interval",)
    assert evidence.temporal_kind == "state"
    assert evidence.valid_from == NOW
    assert evidence.observed_at == NOW
    assert evidence.source_refs[0].fact_id == "eligible"


def test_hydrator_honors_as_of_queries_without_reviving_other_repositories() -> None:
    historical = _fact("historical", repository_id="repo-a")
    historical = replace(
        historical,
        temporal_extent=FactTemporalExtent(
            kind="state",
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 7, 1, tzinfo=UTC),
            basis="asserted",
            precision="exact",
        ),
    )
    other = _fact("other", repository_id="repo-b")
    store = create_in_memory_memory_fact_store((historical.to_snapshot(), other.to_snapshot()))
    hydrator = MemoryFactContextHydrator(facts=store, clock=_Clock())
    request = ContextCandidateRequest(
        query=ContextQuery(
            scope=ContextScope(space_id="space-1", memory_scope_id="scope-1"),
            text="architecture in June",
            as_of=datetime(2026, 6, 1, tzinfo=UTC),
            repository_id="repo-a",
        ),
        limit=2,
    )

    result = asyncio.run(hydrator.hydrate_candidates(request, ("historical", "other")))

    assert tuple(candidate.canonical_id for candidate in result) == ("historical",)
    assert result[0].item.evidence[0].temporal_label == "current"


def _fact(fact_id: str, *, repository_id: str) -> MemoryFact:
    return MemoryFact.remember(
        identity=MemoryFactIdentity(
            fact_id=fact_id,
            scope=MemoryFactScope(space_id="space-1", memory_scope_id="scope-1"),
        ),
        text=f"Canonical fact {fact_id}",
        source_refs=(MemoryFactSourceRef(source_type="note", source_id=f"src-{fact_id}"),),
        now=NOW,
        code_scope=FactCodeScopeReference(repository_id=repository_id),
    )
