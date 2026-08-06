"""Canonical reviewed mutations share one transaction and domain lifecycle."""

from __future__ import annotations

import asyncio

from infinity_context_adapters.features.memory_facts.in_memory_fact_store import (
    InMemoryMemoryFactUnitOfWorkFactory,
)
from infinity_context_core.features.memory_facts.public import (
    FactTemporalDecisionType,
    FactTemporalExtent,
    MemoryFact,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSourceRef,
    ReviewedFactCandidate,
    ReviewedFactDecision,
    ReviewedFactMutationExecutor,
    ReviewedFactTarget,
)
from memory_fact_test_support import EARLIER, NOW, FakeClock, FakeIds


def test_reviewed_supersession_creates_one_audited_replacement_chain() -> None:
    asyncio.run(_assert_reviewed_supersession())


async def _assert_reviewed_supersession() -> None:
    predecessor = _fact("predecessor", "Postgres v15 is required.")
    factory = InMemoryMemoryFactUnitOfWorkFactory((predecessor,))
    ids = FakeIds(
        fact_ids=("successor",),
        outbox_message_ids=("outbox-successor", "outbox-predecessor"),
        temporal_decision_ids=("decision-1",),
        fact_relation_ids=("relation-1",),
    )

    async with factory() as transaction:
        result = await ReviewedFactMutationExecutor(
            transaction=transaction,
            clock=FakeClock(NOW),
            ids=ids,
        ).create_and_supersede(
            _decision(
                candidate_text="Postgres v16 is required.",
                target=predecessor.identity,
            )
        )
        await transaction.commit()

    by_id = {fact.identity.fact_id: fact for fact in factory.facts}
    assert result.decision is not None
    assert result.decision.decision_type is FactTemporalDecisionType.SUPERSEDE
    assert result.relation is not None
    assert result.relation.predecessor_fact_id == "predecessor"
    assert by_id["predecessor"].visibility.status == "superseded"
    assert by_id["predecessor"].temporal_extent is not None
    assert by_id["predecessor"].temporal_extent.valid_to == NOW
    assert by_id["successor"].visibility.status == "active"
    assert by_id["successor"].temporal_extent is not None
    assert by_id["successor"].temporal_extent.valid_from == NOW
    assert result.outbox_message_ids == ("outbox-successor", "outbox-predecessor")


def test_reviewed_conflict_disputes_both_claims_in_one_decision() -> None:
    asyncio.run(_assert_reviewed_dispute())


async def _assert_reviewed_dispute() -> None:
    challenged = _fact("challenged", "The API is REST-only.")
    factory = InMemoryMemoryFactUnitOfWorkFactory((challenged,))
    ids = FakeIds(
        fact_ids=("challenger",),
        outbox_message_ids=("outbox-challenger", "outbox-challenged"),
        temporal_decision_ids=("decision-2",),
    )

    async with factory() as transaction:
        result = await ReviewedFactMutationExecutor(
            transaction=transaction,
            clock=FakeClock(NOW),
            ids=ids,
        ).create_and_dispute(
            _decision(
                candidate_text="The API supports GraphQL.",
                target=challenged.identity,
            )
        )
        await transaction.commit()

    by_id = {fact.identity.fact_id: fact for fact in factory.facts}
    assert result.decision is not None
    assert result.decision.decision_type is FactTemporalDecisionType.DISPUTE
    assert by_id["challenger"].visibility.status == "disputed"
    assert by_id["challenged"].visibility.status == "disputed"
    assert result.outbox_message_ids == ("outbox-challenger", "outbox-challenged")


def _fact(fact_id: str, text: str):
    return MemoryFact.remember(
        identity=MemoryFactIdentity(fact_id, _scope()),
        text=text,
        source_refs=(_source(f"source-{fact_id}"),),
        now=EARLIER,
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=EARLIER,
            valid_from=EARLIER,
            basis="asserted",
        ),
    ).to_snapshot()


def _decision(
    *,
    candidate_text: str,
    target: MemoryFactIdentity,
) -> ReviewedFactDecision:
    source = _source(f"candidate-{target.fact_id}")
    return ReviewedFactDecision(
        candidate=ReviewedFactCandidate(
            scope=target.scope,
            text=candidate_text,
            source_refs=(source,),
            evidence_refs=(MemoryFactEvidenceRef(source_ref=source),),
        ),
        target=ReviewedFactTarget(target, expected_version=1),
        actor_id="reviewer-1",
        reason_code="manual_review",
        idempotency_key=f"review-{target.fact_id}",
        effective_at=NOW,
    )


def _scope() -> MemoryFactScope:
    return MemoryFactScope("space-1", "scope-1")


def _source(source_id: str) -> MemoryFactSourceRef:
    return MemoryFactSourceRef("document", source_id)
