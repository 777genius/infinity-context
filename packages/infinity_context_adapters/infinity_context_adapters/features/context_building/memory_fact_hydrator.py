"""Canonical memory-fact hydration for identity-only context hits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.features.context_building.public import (
    CanonicalContextHydratorPort,
    ContextCandidateRequest,
    ContextClockPort,
    ContextEvidence,
    ContextItem,
    ContextSourceRef,
    HydratedContextCandidate,
)
from infinity_context_core.features.memory_facts.public import (
    FactCurrentnessPolicy,
    FactTemporalQueryMode,
    MemoryFactSelectionPort,
    MemoryFactSelectionQuery,
    MemoryFactSnapshot,
)


@dataclass(frozen=True, slots=True)
class MemoryFactContextHydrator:
    """Revalidate derived IDs against canonical fact state before rendering."""

    facts: MemoryFactSelectionPort
    clock: ContextClockPort

    async def hydrate_candidates(
        self,
        request: ContextCandidateRequest,
        canonical_ids: tuple[str, ...],
    ) -> tuple[HydratedContextCandidate, ...]:
        if not canonical_ids:
            return ()
        context_query = request.query
        reference_time = context_query.as_of or self.clock.now()
        temporal_mode = (
            FactTemporalQueryMode.AS_OF
            if context_query.as_of is not None
            else FactTemporalQueryMode.CURRENT
        )
        snapshots = await self.facts.find_eligible(
            MemoryFactSelectionQuery(
                space_id=context_query.scope.space_id,
                memory_scope_ids=(context_query.scope.memory_scope_id,),
                thread_id=context_query.scope.thread_id,
                repository_id=context_query.repository_id,
                code_scope_id=context_query.code_scope_id,
                temporal_mode=temporal_mode,
                reference_time=reference_time,
                fact_ids=canonical_ids,
                limit=len(canonical_ids),
            )
        )
        return tuple(
            HydratedContextCandidate(
                canonical_id=fact.identity.fact_id,
                canonical_version=fact.visibility.version,
                item=_context_item(fact, reference_time=reference_time),
            )
            for fact in snapshots
        )


def create_memory_fact_context_hydrator(
    *,
    facts: MemoryFactSelectionPort,
    clock: ContextClockPort,
) -> CanonicalContextHydratorPort:
    return MemoryFactContextHydrator(facts=facts, clock=clock)


def _context_item(fact: MemoryFactSnapshot, *, reference_time: datetime) -> ContextItem:
    if fact.temporal_extent is None:
        raise ValueError("Canonical context hydration requires temporal_extent")
    currentness = FactCurrentnessPolicy().assess(
        fact.temporal_extent,
        reference_time=reference_time,
        freshness=fact.freshness,
    )
    source_refs = tuple(
        ContextSourceRef(
            source_type=source.source_type,
            source_id=source.source_id,
            chunk_id=source.chunk_id,
            fact_id=fact.identity.fact_id,
            char_start=source.char_start,
            char_end=source.char_end,
            quote_preview=source.quote_preview,
            occurred_at=fact.temporal_extent.occurred_from,
        )
        for source in fact.source_refs
    )
    if not source_refs:
        source_refs = (
            ContextSourceRef(
                source_type="memory_fact",
                source_id=fact.identity.fact_id,
                fact_id=fact.identity.fact_id,
            ),
        )
    evidence = ContextEvidence(
        text=fact.text,
        source_refs=source_refs,
        evidence_id=f"fact:{fact.identity.fact_id}:v{fact.visibility.version}",
        trust_level=fact.visibility.trust_level,
        confidence=fact.visibility.confidence,
        temporal_label=currentness.state.value,
        temporal_assurance=currentness.assurance.value,
        temporal_reason_codes=currentness.reason_codes,
        lifecycle_label=fact.visibility.status,
        temporal_kind=fact.temporal_extent.kind.value,
        observed_at=fact.temporal_extent.observed_at,
        valid_from=fact.temporal_extent.valid_from,
        valid_to=fact.temporal_extent.valid_to,
        last_confirmed_at=fact.freshness.last_confirmed_at,
        canonical_version=fact.visibility.version,
    )
    return ContextItem(
        item_id=fact.identity.fact_id,
        text=fact.text,
        evidence=(evidence,),
        kind=fact.kind,
        role="supporting_evidence",
        tags=fact.tags,
    )


__all__ = (
    "MemoryFactContextHydrator",
    "create_memory_fact_context_hydrator",
)
