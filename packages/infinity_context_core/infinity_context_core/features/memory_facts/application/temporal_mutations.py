"""Audited single-fact temporal mutations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.features.memory_facts.application.authorization import (
    require_authorized_code_scope,
)
from infinity_context_core.features.memory_facts.application.events import (
    FACT_CONFIRMED_EVENT,
    FACT_TEMPORAL_ENDED_EVENT,
    new_fact_outbox_message,
)
from infinity_context_core.features.memory_facts.application.idempotency import (
    normalize_memory_fact_idempotency_key,
)
from infinity_context_core.features.memory_facts.domain import (
    FactCodeScopeReference,
    FactTemporalDecision,
    FactTemporalDecisionType,
    MemoryFact,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactSnapshot,
)
from infinity_context_core.features.memory_facts.ports import (
    MemoryFactClockPort,
    MemoryFactIdPort,
    MemoryFactUnitOfWorkFactoryPort,
    MemoryFactUnitOfWorkPort,
)

FACT_TEMPORAL_MUTATION_POLICY_VERSION = "fact-temporal-mutation-v1"


@dataclass(frozen=True, slots=True)
class ConfirmFactCommand:
    identity: MemoryFactIdentity
    expected_version: int
    confirmed_at: datetime
    confirmation_basis: str
    evidence_refs: tuple[MemoryFactEvidenceRef, ...]
    actor_id: str
    idempotency_key: str
    authorized_code_scope: FactCodeScopeReference | None = None

    def __post_init__(self) -> None:
        _validate_command(
            expected_version=self.expected_version,
            effective_at=self.confirmed_at,
            evidence_refs=self.evidence_refs,
            actor_id=self.actor_id,
            reason_code=self.confirmation_basis,
            idempotency_key=self.idempotency_key,
        )
        object.__setattr__(
            self,
            "idempotency_key",
            normalize_memory_fact_idempotency_key(self.idempotency_key, required=True),
        )


@dataclass(frozen=True, slots=True)
class ConfirmFactResult:
    fact: MemoryFactSnapshot
    decision: FactTemporalDecision
    outbox_message_ids: tuple[str, ...] = ()
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class EndFactValidityCommand:
    identity: MemoryFactIdentity
    expected_version: int
    effective_at: datetime
    reason_code: str
    evidence_refs: tuple[MemoryFactEvidenceRef, ...]
    actor_id: str
    idempotency_key: str
    authorized_code_scope: FactCodeScopeReference | None = None

    def __post_init__(self) -> None:
        _validate_command(
            expected_version=self.expected_version,
            effective_at=self.effective_at,
            evidence_refs=self.evidence_refs,
            actor_id=self.actor_id,
            reason_code=self.reason_code,
            idempotency_key=self.idempotency_key,
        )
        object.__setattr__(
            self,
            "idempotency_key",
            normalize_memory_fact_idempotency_key(self.idempotency_key, required=True),
        )


@dataclass(frozen=True, slots=True)
class EndFactValidityResult:
    fact: MemoryFactSnapshot
    decision: FactTemporalDecision
    outbox_message_ids: tuple[str, ...] = ()
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ConfirmFactHandler:
    """Record explicit evidence confirmation; transaction time is not confirmation."""

    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort

    async def execute(self, command: ConfirmFactCommand) -> ConfirmFactResult:
        async with self.uow_factory() as uow:
            replayed = await _replayed_decision(
                uow,
                command.identity,
                FactTemporalDecisionType.CONFIRM,
                command.idempotency_key,
            )
            if replayed is not None:
                _require_replay(
                    decision=replayed,
                    decision_type=FactTemporalDecisionType.CONFIRM,
                    command=command,
                    effective_at=command.confirmed_at,
                    reason_code=command.confirmation_basis,
                )
                fact = await _fact_at_decision_version(uow, command.identity, replayed)
                require_authorized_code_scope(fact, command.authorized_code_scope)
                return ConfirmFactResult(
                    fact=fact,
                    decision=replayed,
                    outbox_message_ids=replayed.outbox_message_ids,
                    replayed=True,
                )

            current = await uow.facts.get_for_update(command.identity)
            replayed = await _replayed_decision(
                uow,
                command.identity,
                FactTemporalDecisionType.CONFIRM,
                command.idempotency_key,
            )
            if replayed is not None:
                _require_replay(
                    decision=replayed,
                    decision_type=FactTemporalDecisionType.CONFIRM,
                    command=command,
                    effective_at=command.confirmed_at,
                    reason_code=command.confirmation_basis,
                )
                fact = await _fact_at_decision_version(uow, command.identity, replayed)
                require_authorized_code_scope(fact, command.authorized_code_scope)
                return ConfirmFactResult(
                    fact=fact,
                    decision=replayed,
                    outbox_message_ids=replayed.outbox_message_ids,
                    replayed=True,
                )
            if current is None:
                raise LookupError(f"Memory fact not found: {command.identity.fact_id}")
            require_authorized_code_scope(current, command.authorized_code_scope)
            now = self.clock.now()
            changed = MemoryFact.restore(current).confirm(
                expected_version=command.expected_version,
                confirmed_at=command.confirmed_at,
                confirmation_basis=command.confirmation_basis,
                now=now,
            )
            saved = await uow.facts.save(changed.to_snapshot())
            event = new_fact_outbox_message(
                ids=self.ids,
                fact=saved,
                event_type=FACT_CONFIRMED_EVENT,
                occurred_at=now,
            )
            decision = _decision(
                ids=self.ids,
                identity=command.identity,
                fact_version=saved.visibility.version,
                decision_type=FactTemporalDecisionType.CONFIRM,
                effective_at=command.confirmed_at,
                evidence_refs=command.evidence_refs,
                actor_id=command.actor_id,
                reason_code=command.confirmation_basis,
                applied_at=now,
                idempotency_key=command.idempotency_key,
                outbox_message_ids=(event.message_id,),
            )
            await uow.temporal_decisions.create(decision)
            await uow.outbox.enqueue(event)
            await uow.commit()
        return ConfirmFactResult(
            fact=saved,
            decision=decision,
            outbox_message_ids=(event.message_id,),
        )


@dataclass(frozen=True, slots=True)
class EndFactValidityHandler:
    """Close state validity without fabricating a replacement fact."""

    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort

    async def execute(self, command: EndFactValidityCommand) -> EndFactValidityResult:
        async with self.uow_factory() as uow:
            replayed = await _replayed_decision(
                uow,
                command.identity,
                FactTemporalDecisionType.TEMPORAL_END,
                command.idempotency_key,
            )
            if replayed is not None:
                _require_replay(
                    decision=replayed,
                    decision_type=FactTemporalDecisionType.TEMPORAL_END,
                    command=command,
                    effective_at=command.effective_at,
                    reason_code=command.reason_code,
                )
                fact = await _fact_at_decision_version(uow, command.identity, replayed)
                require_authorized_code_scope(fact, command.authorized_code_scope)
                return EndFactValidityResult(
                    fact=fact,
                    decision=replayed,
                    outbox_message_ids=replayed.outbox_message_ids,
                    replayed=True,
                )

            current = await uow.facts.get_for_update(command.identity)
            replayed = await _replayed_decision(
                uow,
                command.identity,
                FactTemporalDecisionType.TEMPORAL_END,
                command.idempotency_key,
            )
            if replayed is not None:
                _require_replay(
                    decision=replayed,
                    decision_type=FactTemporalDecisionType.TEMPORAL_END,
                    command=command,
                    effective_at=command.effective_at,
                    reason_code=command.reason_code,
                )
                fact = await _fact_at_decision_version(uow, command.identity, replayed)
                require_authorized_code_scope(fact, command.authorized_code_scope)
                return EndFactValidityResult(
                    fact=fact,
                    decision=replayed,
                    outbox_message_ids=replayed.outbox_message_ids,
                    replayed=True,
                )
            if current is None:
                raise LookupError(f"Memory fact not found: {command.identity.fact_id}")
            require_authorized_code_scope(current, command.authorized_code_scope)
            now = self.clock.now()
            changed = MemoryFact.restore(current).end_validity(
                expected_version=command.expected_version,
                effective_at=command.effective_at,
                now=now,
            )
            saved = await uow.facts.save(changed.to_snapshot())
            event = new_fact_outbox_message(
                ids=self.ids,
                fact=saved,
                event_type=FACT_TEMPORAL_ENDED_EVENT,
                occurred_at=now,
            )
            decision = _decision(
                ids=self.ids,
                identity=command.identity,
                fact_version=saved.visibility.version,
                decision_type=FactTemporalDecisionType.TEMPORAL_END,
                effective_at=command.effective_at,
                evidence_refs=command.evidence_refs,
                actor_id=command.actor_id,
                reason_code=command.reason_code,
                applied_at=now,
                idempotency_key=command.idempotency_key,
                outbox_message_ids=(event.message_id,),
            )
            await uow.temporal_decisions.create(decision)
            await uow.outbox.enqueue(event)
            await uow.commit()
        return EndFactValidityResult(
            fact=saved,
            decision=decision,
            outbox_message_ids=(event.message_id,),
        )


def _validate_command(
    *,
    expected_version: int,
    effective_at: datetime,
    evidence_refs: tuple[MemoryFactEvidenceRef, ...],
    actor_id: str,
    reason_code: str,
    idempotency_key: str,
) -> None:
    if expected_version < 1:
        raise ValueError("Temporal mutation expected_version must be positive")
    if effective_at.tzinfo is None or effective_at.utcoffset() is None:
        raise ValueError("Temporal mutation time must be timezone-aware")
    if not evidence_refs:
        raise ValueError("Temporal mutation requires evidence_refs")
    for field_name, value in (
        ("actor_id", actor_id),
        ("reason_code", reason_code),
        ("idempotency_key", idempotency_key),
    ):
        if not value.strip():
            raise ValueError(f"{field_name} cannot be blank")
    normalize_memory_fact_idempotency_key(idempotency_key, required=True)


def _decision(
    *,
    ids: MemoryFactIdPort,
    identity: MemoryFactIdentity,
    fact_version: int,
    decision_type: FactTemporalDecisionType,
    effective_at: datetime,
    evidence_refs: tuple[MemoryFactEvidenceRef, ...],
    actor_id: str,
    reason_code: str,
    applied_at: datetime,
    idempotency_key: str,
    outbox_message_ids: tuple[str, ...],
) -> FactTemporalDecision:
    return FactTemporalDecision(
        decision_id=ids.new_temporal_decision_id(),
        decision_type=decision_type,
        scope=identity.scope,
        source_fact_id=identity.fact_id,
        source_fact_version=fact_version,
        target_fact_id=None,
        target_fact_version=None,
        effective_at=effective_at,
        evidence_refs=evidence_refs,
        actor_id=actor_id,
        policy_version=FACT_TEMPORAL_MUTATION_POLICY_VERSION,
        reason_code=reason_code,
        applied_at=applied_at,
        idempotency_key=idempotency_key,
        outbox_message_ids=outbox_message_ids,
    )


async def _replayed_decision(
    uow: MemoryFactUnitOfWorkPort,
    identity: MemoryFactIdentity,
    decision_type: FactTemporalDecisionType,
    idempotency_key: str,
) -> FactTemporalDecision | None:
    return await uow.temporal_decisions.get_by_idempotency_key(
        scope=identity.scope,
        decision_type=decision_type,
        idempotency_key=idempotency_key,
    )


def _require_replay(
    *,
    decision: FactTemporalDecision,
    decision_type: FactTemporalDecisionType,
    command: ConfirmFactCommand | EndFactValidityCommand,
    effective_at: datetime,
    reason_code: str,
) -> None:
    if (
        decision.decision_type is not decision_type
        or decision.scope != command.identity.scope
        or decision.source_fact_id != command.identity.fact_id
        or decision.source_fact_version != command.expected_version + 1
        or decision.target_fact_id is not None
        or decision.effective_at != effective_at
        or decision.evidence_refs != command.evidence_refs
        or decision.actor_id != command.actor_id
        or decision.reason_code != reason_code
    ):
        raise ValueError("Temporal mutation idempotency key was reused for another command")


async def _fact_at_decision_version(
    uow: MemoryFactUnitOfWorkPort,
    identity: MemoryFactIdentity,
    decision: FactTemporalDecision,
) -> MemoryFactSnapshot:
    fact = next(
        (
            snapshot
            for snapshot in await uow.facts.list_versions(identity)
            if snapshot.visibility.version == decision.source_fact_version
        ),
        None,
    )
    if fact is None:
        raise RuntimeError("Temporal mutation replay audit is incomplete")
    return fact


__all__ = (
    "FACT_TEMPORAL_MUTATION_POLICY_VERSION",
    "ConfirmFactCommand",
    "ConfirmFactHandler",
    "ConfirmFactResult",
    "EndFactValidityCommand",
    "EndFactValidityHandler",
    "EndFactValidityResult",
)
