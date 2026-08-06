from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.features.memory_facts.in_memory_fact_store import (
    InMemoryMemoryFactUnitOfWorkFactory,
)
from infinity_context_core.features.memory_facts.public import (
    ConfirmFactCommand,
    ConfirmFactHandler,
    DisputeFactsCommand,
    DisputeFactsHandler,
    EndFactValidityCommand,
    EndFactValidityHandler,
    FactCodeScopeReference,
    FactCurrentness,
    FactCurrentnessPolicy,
    FactTemporalExtent,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    MemoryFactVisibility,
)

OBSERVED = datetime(2026, 1, 1, tzinfo=UTC)
CONFIRMED = datetime(2026, 1, 2, tzinfo=UTC)
NOW = datetime(2026, 1, 3, tzinfo=UTC)
ENDS = datetime(2026, 2, 1, tzinfo=UTC)


def test_confirm_fact_is_atomic_audited_and_idempotent() -> None:
    factory = InMemoryMemoryFactUnitOfWorkFactory((_fact(),))
    handler = ConfirmFactHandler(
        uow_factory=factory,
        clock=_Clock(NOW),
        ids=_Ids(decisions=["decision-confirm"], outbox=["outbox-confirm"]),
    )
    command = ConfirmFactCommand(
        identity=_identity(),
        expected_version=1,
        confirmed_at=CONFIRMED,
        confirmation_basis="manual_review",
        evidence_refs=(_evidence(),),
        actor_id="reviewer-1",
        idempotency_key="confirm-1",
    )

    result = asyncio.run(handler.execute(command))
    replay = asyncio.run(handler.execute(command))

    assert result.fact.visibility.version == 2
    assert result.fact.freshness.last_confirmed_at == CONFIRMED
    assert result.fact.updated_at == NOW
    assert result.decision.target_fact_id is None
    assert result.decision.source_fact_version == 2
    assert result.outbox_message_ids == ("outbox-confirm",)
    assert replay.replayed is True
    assert len(factory.temporal_decisions) == 1
    assert tuple(item.event_type for item in factory.outbox_messages) == ("fact.confirmed",)


def test_end_validity_closes_the_interval_at_an_observed_boundary() -> None:
    factory = InMemoryMemoryFactUnitOfWorkFactory((_fact(),))
    handler = EndFactValidityHandler(
        uow_factory=factory,
        clock=_Clock(NOW),
        ids=_Ids(decisions=["decision-end"], outbox=["outbox-end"]),
    )

    result = asyncio.run(
        handler.execute(
            EndFactValidityCommand(
                identity=_identity(),
                expected_version=1,
                effective_at=NOW,
                reason_code="contract_ends",
                evidence_refs=(_evidence(),),
                actor_id="reviewer-1",
                idempotency_key="end-1",
            )
        )
    )

    assert result.fact.visibility.status == "active"
    assert result.fact.temporal_extent is not None
    assert result.fact.temporal_extent.valid_to == NOW
    policy = FactCurrentnessPolicy()
    assert (
        policy.assess(result.fact.temporal_extent, reference_time=NOW).state
        is FactCurrentness.HISTORICAL
    )
    assert result.decision.target_fact_id is None
    assert result.decision.effective_at == NOW


def test_end_validity_rejects_future_scheduling_until_activation_is_modeled() -> None:
    factory = InMemoryMemoryFactUnitOfWorkFactory((_fact(),))
    handler = EndFactValidityHandler(
        uow_factory=factory,
        clock=_Clock(NOW),
        ids=_Ids(decisions=[], outbox=[]),
    )

    with pytest.raises(ValueError, match="Scheduled validity changes"):
        asyncio.run(
            handler.execute(
                EndFactValidityCommand(
                    identity=_identity(),
                    expected_version=1,
                    effective_at=ENDS,
                    reason_code="contract_ends",
                    evidence_refs=(_evidence(),),
                    actor_id="reviewer-1",
                    idempotency_key="end-future-1",
                )
            )
        )

    assert factory.temporal_decisions == ()
    assert factory.outbox_messages == ()


def test_temporal_idempotency_is_scoped_by_scope_thread_and_operation() -> None:
    global_fact = _fact()
    other_scope = replace(
        _fact(),
        identity=MemoryFactIdentity(
            "fact-2",
            MemoryFactScope(space_id="space-1", memory_scope_id="scope-2"),
        ),
    )
    thread_fact = replace(
        _fact(),
        identity=MemoryFactIdentity(
            "fact-3",
            MemoryFactScope(
                space_id="space-1",
                memory_scope_id="scope-1",
                thread_id="thread-1",
            ),
        ),
    )
    factory = InMemoryMemoryFactUnitOfWorkFactory((global_fact, other_scope, thread_fact))
    ids = _Ids(
        decisions=["decision-1", "decision-2", "decision-3", "decision-4"],
        outbox=["outbox-1", "outbox-2", "outbox-3", "outbox-4"],
    )
    confirm = ConfirmFactHandler(uow_factory=factory, clock=_Clock(NOW), ids=ids)

    for fact in (global_fact, other_scope, thread_fact):
        result = asyncio.run(
            confirm.execute(
                ConfirmFactCommand(
                    identity=fact.identity,
                    expected_version=1,
                    confirmed_at=CONFIRMED,
                    confirmation_basis="manual_review",
                    evidence_refs=(_evidence(),),
                    actor_id="reviewer-1",
                    idempotency_key="shared-key",
                )
            )
        )
        assert result.replayed is False

    ended = asyncio.run(
        EndFactValidityHandler(uow_factory=factory, clock=_Clock(NOW), ids=ids).execute(
            EndFactValidityCommand(
                identity=global_fact.identity,
                expected_version=2,
                effective_at=NOW,
                reason_code="contract_ends",
                evidence_refs=(_evidence(),),
                actor_id="reviewer-1",
                idempotency_key="shared-key",
            )
        )
    )

    assert ended.replayed is False
    assert len(factory.temporal_decisions) == 4


def test_dispute_rejects_cross_repository_facts() -> None:
    first = replace(
        _fact(),
        code_scope=FactCodeScopeReference("repo-1", "branch-main"),
    )
    second = replace(
        _fact(),
        identity=MemoryFactIdentity("fact-2", _identity().scope),
        code_scope=FactCodeScopeReference("repo-2", "branch-main"),
    )
    factory = InMemoryMemoryFactUnitOfWorkFactory((first, second))
    handler = DisputeFactsHandler(
        uow_factory=factory,
        clock=_Clock(NOW),
        ids=_Ids(decisions=[], outbox=[]),
    )

    with pytest.raises(ValueError, match="cross code scope"):
        asyncio.run(
            handler.execute(
                DisputeFactsCommand(
                    challenger_identity=first.identity,
                    challenged_identity=second.identity,
                    expected_challenger_version=1,
                    expected_challenged_version=1,
                    evidence_refs=(_evidence(),),
                    actor_id="reviewer-1",
                    reason_code="conflict",
                    idempotency_key="dispute-1",
                )
            )
        )


def _fact() -> MemoryFactSnapshot:
    return MemoryFactSnapshot(
        identity=_identity(),
        text="The service uses PostgreSQL.",
        source_refs=(_source(),),
        visibility=MemoryFactVisibility(version=1),
        created_at=OBSERVED,
        updated_at=OBSERVED,
        temporal_extent=FactTemporalExtent.ongoing_state(observed_at=OBSERVED),
    )


def _identity() -> MemoryFactIdentity:
    return MemoryFactIdentity(
        fact_id="fact-1",
        scope=MemoryFactScope(space_id="space-1", memory_scope_id="scope-1"),
    )


def _source() -> MemoryFactSourceRef:
    return MemoryFactSourceRef(source_type="document", source_id="doc-1")


def _evidence() -> MemoryFactEvidenceRef:
    return MemoryFactEvidenceRef(source_ref=_source(), evidence_id="evidence-1")


class _Clock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value


class _Ids:
    def __init__(self, *, decisions: list[str], outbox: list[str]) -> None:
        self._decisions = decisions
        self._outbox = outbox

    def new_temporal_decision_id(self) -> str:
        return self._decisions.pop(0)

    def new_outbox_message_id(self) -> str:
        return self._outbox.pop(0)

    def new_fact_id(self) -> str:  # pragma: no cover - not used by these handlers.
        raise AssertionError("unexpected fact id")

    def new_tombstone_id(self) -> str:  # pragma: no cover - not used by these handlers.
        raise AssertionError("unexpected tombstone id")

    def new_fact_relation_id(self) -> str:  # pragma: no cover - not used by these handlers.
        raise AssertionError("unexpected relation id")
