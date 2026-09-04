"""Atomic temporal decision scenarios for memory facts."""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace

import pytest
from infinity_context_core.features.memory_facts.public import (
    DisputeFactsCommand,
    DisputeFactsHandler,
    FactSupersessionRelation,
    FactTemporalExtent,
    FactTemporalQueryMode,
    MemoryFactEvidenceRef,
    MemoryFactSelectionQuery,
    MemoryFactSnapshot,
    ReinstateSupersededFactCommand,
    ReinstateSupersededFactHandler,
    SupersedeFactCommand,
    SupersedeFactHandler,
)
from memory_fact_test_support import (
    EARLIER,
    LATER,
    NOW,
    AsyncEntryGate,
    BarrierUnitOfWorkFactory,
    FakeClock,
    FakeIds,
    _fact_snapshot,
    _scope,
    _source_ref,
)


def test_in_memory_supersession_is_atomic_audited_and_idempotent() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    predecessor = replace(
        _fact_snapshot(fact_id="old"),
        text="The API uses version one.",
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=EARLIER,
            valid_from=EARLIER,
            basis="primary_evidence",
        ),
    )
    successor = replace(
        _fact_snapshot(fact_id="new"),
        text="The API uses version two.",
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=NOW,
            valid_from=NOW,
            basis="primary_evidence",
        ),
    )
    factory = module.create_in_memory_memory_fact_unit_of_work_factory((predecessor, successor))
    ids = FakeIds(
        outbox_message_ids=("outbox-new", "outbox-old"),
        temporal_decision_ids=("decision-1",),
        fact_relation_ids=("relation-1",),
    )
    command = SupersedeFactCommand(
        successor_identity=successor.identity,
        predecessor_identity=predecessor.identity,
        expected_successor_version=1,
        expected_predecessor_version=1,
        effective_at=NOW,
        evidence_refs=(
            MemoryFactEvidenceRef(
                evidence_id="evidence-1",
                source_ref=_source_ref("adr-3"),
            ),
        ),
        actor_id="reviewer-1",
        reason_code="accepted_replacement",
        idempotency_key="supersede-1",
    )
    handler = SupersedeFactHandler(
        uow_factory=factory,
        clock=FakeClock(NOW),
        ids=ids,
    )

    result = asyncio.run(handler.execute(command))
    replay = asyncio.run(handler.execute(command))

    assert result.successor.visibility.version == 2
    assert result.predecessor.visibility.status == "superseded"
    assert result.predecessor.temporal_extent is not None
    assert result.predecessor.temporal_extent.valid_to == NOW
    assert result.successor.freshness.last_confirmed_at is None
    assert len(factory.temporal_decisions) == 1
    assert len(factory.supersessions) == 1
    assert result.decision.source_fact_version == 2
    assert result.decision.target_fact_version == 2
    assert result.relation.decision_id == result.decision.decision_id
    assert replay.replayed
    assert replay.outbox_message_ids == ("outbox-new", "outbox-old")
    assert len(factory.outbox_messages) == 2


def test_supersession_coordinates_all_existing_and_command_source_refs_before_fact_locks() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    predecessor = replace(
        _fact_snapshot(fact_id="old"),
        source_refs=(_source_ref("old-document"),),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=EARLIER,
            valid_from=EARLIER,
            basis="primary_evidence",
        ),
    )
    successor = replace(
        _fact_snapshot(fact_id="new"),
        source_refs=(_source_ref("new-document"),),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=NOW,
            valid_from=NOW,
            basis="primary_evidence",
        ),
    )
    inner = module.create_in_memory_memory_fact_unit_of_work_factory((predecessor, successor))
    factory = _RecordingCoordinationFactory(inner)
    command_ref = _source_ref("decision-document")

    asyncio.run(
        SupersedeFactHandler(
            uow_factory=factory,
            clock=FakeClock(NOW),
            ids=FakeIds(
                outbox_message_ids=("outbox-new", "outbox-old"),
                temporal_decision_ids=("decision-1",),
                fact_relation_ids=("relation-1",),
            ),
        ).execute(
            SupersedeFactCommand(
                successor_identity=successor.identity,
                predecessor_identity=predecessor.identity,
                expected_successor_version=1,
                expected_predecessor_version=1,
                effective_at=NOW,
                evidence_refs=(MemoryFactEvidenceRef(source_ref=command_ref),),
                actor_id="reviewer-1",
                reason_code="accepted_replacement",
                idempotency_key="supersede-source-union",
            )
        )
    )

    assert factory.events.index("coordinate") < factory.events.index("get_many_for_update")
    assert set(factory.coordinated_refs) == {
        predecessor.source_refs[0],
        successor.source_refs[0],
        command_ref,
    }


def test_supersession_rejects_source_ref_change_during_document_coordination() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    predecessor = replace(
        _fact_snapshot(fact_id="old"),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=EARLIER,
            valid_from=EARLIER,
        ),
    )
    successor = replace(
        _fact_snapshot(fact_id="new"),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=NOW,
            valid_from=NOW,
        ),
    )
    changed_successor = replace(
        successor,
        source_refs=(_source_ref("concurrent-source"),),
    )
    inner = module.create_in_memory_memory_fact_unit_of_work_factory((predecessor, successor))
    factory = _RecordingCoordinationFactory(inner, locked_replacement=changed_successor)

    with pytest.raises(ValueError, match="changed during source coordination"):
        asyncio.run(
            SupersedeFactHandler(
                uow_factory=factory,
                clock=FakeClock(NOW),
                ids=FakeIds(),
            ).execute(
                SupersedeFactCommand(
                    successor_identity=successor.identity,
                    predecessor_identity=predecessor.identity,
                    expected_successor_version=1,
                    expected_predecessor_version=1,
                    effective_at=NOW,
                    evidence_refs=(
                        MemoryFactEvidenceRef(source_ref=_source_ref("decision-source")),
                    ),
                    actor_id="reviewer-1",
                    reason_code="accepted_replacement",
                    idempotency_key="supersede-concurrent-source-change",
                )
            )
        )

    assert inner.facts == (predecessor, successor)


class _RecordingCoordinationFactory:
    def __init__(self, inner, *, locked_replacement=None) -> None:
        self._inner = inner
        self.locked_replacement = locked_replacement
        self.events: list[str] = []
        self.coordinated_refs = ()

    def __call__(self):
        return _RecordingCoordinationUnitOfWork(self._inner(), self)


class _RecordingCoordinationUnitOfWork:
    def __init__(self, inner, owner) -> None:
        self._inner = inner
        self._owner = owner

    async def __aenter__(self):
        await self._inner.__aenter__()
        self.facts = _RecordingFactRepository(self._inner.facts, self._owner)
        self.outbox = self._inner.outbox
        self.supersessions = self._inner.supersessions
        self.temporal_decisions = self._inner.temporal_decisions
        self.operation_receipts = self._inner.operation_receipts
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._inner.__aexit__(exc_type, exc, tb)

    async def lock_scope(self, scope):
        await self._inner.lock_scope(scope)

    async def coordinate_source_refs(self, *, scope, source_refs):
        self._owner.events.append("coordinate")
        self._owner.coordinated_refs = source_refs
        await self._inner.coordinate_source_refs(scope=scope, source_refs=source_refs)

    async def commit(self):
        await self._inner.commit()


class _RecordingFactRepository:
    def __init__(self, inner, owner) -> None:
        self._inner = inner
        self._owner = owner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def get_many_for_update(self, identities):
        self._owner.events.append("get_many_for_update")
        locked = await self._inner.get_many_for_update(identities)
        replacement = self._owner.locked_replacement
        if replacement is None:
            return locked
        return tuple(
            replacement if fact.identity == replacement.identity else fact for fact in locked
        )


def test_reinstatement_compensates_without_rewriting_supersession_history() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    predecessor = replace(
        _fact_snapshot(fact_id="old"),
        source_refs=(_source_ref("predecessor-document"),),
        text="The API uses version one.",
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=EARLIER,
            valid_from=EARLIER,
            basis="primary_evidence",
        ),
    )
    successor = replace(
        _fact_snapshot(fact_id="new"),
        source_refs=(_source_ref("successor-document"),),
        text="The API uses version two.",
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=NOW,
            valid_from=NOW,
            basis="primary_evidence",
        ),
    )
    factory = module.create_in_memory_memory_fact_unit_of_work_factory((predecessor, successor))
    first = asyncio.run(
        SupersedeFactHandler(
            uow_factory=factory,
            clock=FakeClock(NOW),
            ids=FakeIds(
                outbox_message_ids=("outbox-new", "outbox-old"),
                temporal_decision_ids=("decision-1",),
                fact_relation_ids=("relation-1",),
            ),
        ).execute(
            SupersedeFactCommand(
                successor_identity=successor.identity,
                predecessor_identity=predecessor.identity,
                expected_successor_version=1,
                expected_predecessor_version=1,
                effective_at=NOW,
                evidence_refs=(
                    MemoryFactEvidenceRef(
                        evidence_id="evidence-1",
                        source_ref=_source_ref("adr-3"),
                    ),
                ),
                actor_id="reviewer-1",
                reason_code="accepted_replacement",
                idempotency_key="supersede-1",
            )
        )
    )
    compensation_command = ReinstateSupersededFactCommand(
        scope=_scope(),
        supersession_decision_id=first.decision.decision_id,
        expected_rejected_successor_version=2,
        expected_original_predecessor_version=2,
        evidence_refs=(
            MemoryFactEvidenceRef(
                evidence_id="evidence-rollback",
                source_ref=_source_ref("incident-1"),
            ),
        ),
        actor_id="reviewer-2",
        reason_code="replacement_rejected",
        idempotency_key="reinstate-1",
    )
    changed_while_coordinating = replace(
        first.successor,
        source_refs=(_source_ref("legacy-update-document"),),
        visibility=replace(first.successor.visibility, version=3),
    )
    rejected_factory = _RecordingCoordinationFactory(
        factory,
        locked_replacement=changed_while_coordinating,
    )
    with pytest.raises(ValueError, match="Reinstatement fact changed during source coordination"):
        asyncio.run(
            ReinstateSupersededFactHandler(
                uow_factory=rejected_factory,
                clock=FakeClock(LATER),
                ids=FakeIds(),
            ).execute(compensation_command)
        )
    assert len(factory.temporal_decisions) == 1

    coordinated_factory = _RecordingCoordinationFactory(factory)
    compensator = ReinstateSupersededFactHandler(
        uow_factory=coordinated_factory,
        clock=FakeClock(LATER),
        ids=FakeIds(
            fact_ids=("restored",),
            outbox_message_ids=("outbox-restored", "outbox-rejected"),
            temporal_decision_ids=("decision-2",),
            fact_relation_ids=("relation-2",),
        ),
    )

    compensation = asyncio.run(compensator.execute(compensation_command))
    replay = asyncio.run(compensator.execute(compensation_command))

    assert compensation.decision.compensates_decision_id == first.decision.decision_id
    assert compensation.decision.decision_type.value == "reinstate"
    assert compensation.reinstated_fact.identity.fact_id == "restored"
    assert compensation.reinstated_fact.text == predecessor.text
    assert compensation.reinstated_fact.visibility.status == "active"
    assert compensation.reinstated_fact.temporal_extent is not None
    assert compensation.reinstated_fact.temporal_extent.valid_from == LATER
    assert compensation.rejected_successor.visibility.status == "superseded"
    assert compensation.rejected_successor.temporal_extent is not None
    assert compensation.rejected_successor.temporal_extent.valid_to == LATER
    assert len(factory.temporal_decisions) == 2
    assert len(factory.supersessions) == 2
    assert replay.replayed
    assert coordinated_factory.events.index("coordinate") < coordinated_factory.events.index(
        "get_many_for_update"
    )
    assert set(coordinated_factory.coordinated_refs) == {
        _source_ref("predecessor-document"),
        _source_ref("successor-document"),
        _source_ref("incident-1"),
    }

    async def select_current() -> tuple[MemoryFactSnapshot, ...]:
        async with factory() as uow:
            return await uow.facts.find_eligible(
                MemoryFactSelectionQuery(
                    space_id="space-1",
                    memory_scope_ids=("scope-1",),
                    temporal_mode=FactTemporalQueryMode.CURRENT,
                    reference_time=LATER,
                    limit=10,
                )
            )

    assert asyncio.run(select_current()) == (compensation.reinstated_fact,)


def test_future_supersession_is_rejected_until_activation_is_modeled() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    predecessor = replace(
        _fact_snapshot(fact_id="old"),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=EARLIER,
            valid_from=EARLIER,
        ),
    )
    successor = replace(
        _fact_snapshot(fact_id="new"),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=NOW,
            valid_from=NOW,
        ),
    )
    factory = module.create_in_memory_memory_fact_unit_of_work_factory((predecessor, successor))
    handler = SupersedeFactHandler(
        uow_factory=factory,
        clock=FakeClock(EARLIER),
        ids=FakeIds(),
    )

    with pytest.raises(ValueError, match="Scheduled supersession"):
        asyncio.run(
            handler.execute(
                SupersedeFactCommand(
                    successor_identity=successor.identity,
                    predecessor_identity=predecessor.identity,
                    expected_successor_version=1,
                    expected_predecessor_version=1,
                    effective_at=NOW,
                    evidence_refs=(MemoryFactEvidenceRef(source_ref=_source_ref("schedule-1")),),
                    actor_id="reviewer-1",
                    reason_code="scheduled_replacement",
                    idempotency_key="scheduled-1",
                )
            )
        )

    assert factory.facts == (predecessor, successor)
    assert factory.temporal_decisions == ()
    assert factory.supersessions == ()


def test_fact_conflict_disputes_both_claims_without_selecting_a_winner() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    first = replace(
        _fact_snapshot(fact_id="claim-a"),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=EARLIER,
            valid_from=EARLIER,
        ),
    )
    second = replace(
        _fact_snapshot(fact_id="claim-b"),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=EARLIER,
            valid_from=EARLIER,
        ),
    )
    factory = module.create_in_memory_memory_fact_unit_of_work_factory((first, second))
    command = DisputeFactsCommand(
        challenger_identity=first.identity,
        challenged_identity=second.identity,
        expected_challenger_version=1,
        expected_challenged_version=1,
        evidence_refs=(MemoryFactEvidenceRef(source_ref=_source_ref("conflict-1")),),
        actor_id="reviewer-1",
        reason_code="exclusive_claims_conflict",
        idempotency_key="dispute-1",
    )
    handler = DisputeFactsHandler(
        uow_factory=factory,
        clock=FakeClock(NOW),
        ids=FakeIds(
            outbox_message_ids=("outbox-a", "outbox-b"),
            temporal_decision_ids=("decision-dispute",),
        ),
    )

    result = asyncio.run(handler.execute(command))
    replay = asyncio.run(handler.execute(command))

    assert result.challenger.visibility.status == "disputed"
    assert result.challenged.visibility.status == "disputed"
    assert result.challenger.temporal_extent == first.temporal_extent
    assert result.challenged.temporal_extent == second.temporal_extent
    assert result.decision.decision_type.value == "dispute"
    assert len(factory.temporal_decisions) == 1
    assert len(factory.outbox_messages) == 2
    assert replay.replayed


def test_dispute_rejects_future_or_non_overlapping_claims() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    current = replace(
        _fact_snapshot(fact_id="current"),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=EARLIER,
            valid_from=EARLIER,
        ),
    )
    future = replace(
        _fact_snapshot(fact_id="future"),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=NOW,
            valid_from=LATER,
        ),
    )
    factory = module.create_in_memory_memory_fact_unit_of_work_factory((current, future))

    with pytest.raises(ValueError, match="currently valid facts"):
        asyncio.run(
            DisputeFactsHandler(
                uow_factory=factory,
                clock=FakeClock(NOW),
                ids=FakeIds(),
            ).execute(
                DisputeFactsCommand(
                    challenger_identity=future.identity,
                    challenged_identity=current.identity,
                    expected_challenger_version=1,
                    expected_challenged_version=1,
                    evidence_refs=(MemoryFactEvidenceRef(source_ref=_source_ref("future")),),
                    actor_id="reviewer-1",
                    reason_code="premature_conflict",
                    idempotency_key="future-dispute",
                )
            )
        )

    assert factory.facts == (current, future)
    assert factory.temporal_decisions == ()


def test_supersession_cycle_is_rejected_before_any_mutation() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    predecessor = replace(
        _fact_snapshot(fact_id="old"),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=EARLIER,
            valid_from=EARLIER,
        ),
    )
    successor = replace(
        _fact_snapshot(fact_id="new"),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=NOW,
            valid_from=NOW,
        ),
    )
    factory = module.create_in_memory_memory_fact_unit_of_work_factory((predecessor, successor))

    async def seed_cycle_edge() -> None:
        async with factory() as uow:
            await uow.supersessions.create(
                FactSupersessionRelation(
                    relation_id="existing-edge",
                    scope=_scope(),
                    successor_fact_id="old",
                    successor_fact_version=1,
                    predecessor_fact_id="new",
                    predecessor_fact_version=1,
                    effective_at=NOW,
                    decision_id="existing-decision",
                    created_at=EARLIER,
                )
            )
            await uow.commit()

    asyncio.run(seed_cycle_edge())
    handler = SupersedeFactHandler(
        uow_factory=factory,
        clock=FakeClock(NOW),
        ids=FakeIds(),
    )
    with pytest.raises(ValueError, match="create a cycle"):
        asyncio.run(
            handler.execute(
                SupersedeFactCommand(
                    successor_identity=successor.identity,
                    predecessor_identity=predecessor.identity,
                    expected_successor_version=1,
                    expected_predecessor_version=1,
                    effective_at=NOW,
                    evidence_refs=(MemoryFactEvidenceRef(source_ref=_source_ref("cycle-1")),),
                    actor_id="reviewer-1",
                    reason_code="invalid_cycle",
                    idempotency_key="cycle-1",
                )
            )
        )

    assert factory.facts == (predecessor, successor)
    assert factory.outbox_messages == ()


def test_two_concurrent_supersessions_produce_one_commit_and_one_conflict() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    predecessor = replace(
        _fact_snapshot(fact_id="old"),
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=EARLIER,
            valid_from=EARLIER,
        ),
    )
    successors = tuple(
        replace(
            _fact_snapshot(fact_id=f"new-{suffix}"),
            temporal_extent=FactTemporalExtent.ongoing_state(
                observed_at=NOW,
                valid_from=NOW,
            ),
        )
        for suffix in ("a", "b")
    )
    canonical_factory = module.create_in_memory_memory_fact_unit_of_work_factory(
        (predecessor, *successors)
    )
    gate = AsyncEntryGate(parties=2)
    concurrent_factory = BarrierUnitOfWorkFactory(canonical_factory, gate)

    async def run(index: int):
        successor = successors[index]
        return await SupersedeFactHandler(
            uow_factory=concurrent_factory,
            clock=FakeClock(NOW),
            ids=FakeIds(
                outbox_message_ids=(f"outbox-{index}-new", f"outbox-{index}-old"),
                temporal_decision_ids=(f"decision-{index}",),
                fact_relation_ids=(f"relation-{index}",),
            ),
        ).execute(
            SupersedeFactCommand(
                successor_identity=successor.identity,
                predecessor_identity=predecessor.identity,
                expected_successor_version=1,
                expected_predecessor_version=1,
                effective_at=NOW,
                evidence_refs=(
                    MemoryFactEvidenceRef(source_ref=_source_ref(f"concurrent-{index}")),
                ),
                actor_id="reviewer-1",
                reason_code="concurrent_replacement",
                idempotency_key=f"concurrent-{index}",
            )
        )

    async def race():
        return await asyncio.gather(run(0), run(1), return_exceptions=True)

    results = asyncio.run(race())

    committed = [result for result in results if not isinstance(result, BaseException)]
    conflicted = [result for result in results if isinstance(result, BaseException)]
    assert len(committed) == 1
    assert len(conflicted) == 1
    assert isinstance(conflicted[0], ValueError)
    assert "transaction conflict" in str(conflicted[0])
    assert len(canonical_factory.temporal_decisions) == 1
    assert len(canonical_factory.supersessions) == 1
    assert len(canonical_factory.outbox_messages) == 2
