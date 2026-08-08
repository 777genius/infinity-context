"""Atomic application flow for high-impact fact supersession."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.features.memory_facts.application.authorization import (
    require_authorized_code_scope,
)
from infinity_context_core.features.memory_facts.application.events import (
    FACT_CREATED_EVENT,
    FACT_SUPERSEDED_EVENT,
    FACT_UPDATED_EVENT,
    new_fact_outbox_message,
)
from infinity_context_core.features.memory_facts.application.idempotency import (
    normalize_memory_fact_idempotency_key,
)
from infinity_context_core.features.memory_facts.application.locking import (
    memory_fact_identity_lock_key,
)
from infinity_context_core.features.memory_facts.domain import (
    FactCodeScopeReference,
    FactSupersessionPolicy,
    FactSupersessionRelation,
    FactTemporalDecision,
    FactTemporalDecisionType,
    FactTemporalExtent,
    MemoryFact,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSnapshot,
)
from infinity_context_core.features.memory_facts.ports import (
    MemoryFactClockPort,
    MemoryFactIdPort,
    MemoryFactUnitOfWorkFactoryPort,
    MemoryFactUnitOfWorkPort,
)

SUPERSESSION_POLICY_VERSION = "fact-supersession-v1"


@dataclass(frozen=True, slots=True)
class SupersedeFactCommand:
    successor_identity: MemoryFactIdentity
    predecessor_identity: MemoryFactIdentity
    expected_successor_version: int
    expected_predecessor_version: int
    effective_at: datetime
    evidence_refs: tuple[MemoryFactEvidenceRef, ...]
    actor_id: str
    reason_code: str
    idempotency_key: str
    authorized_code_scope: FactCodeScopeReference | None = None

    def __post_init__(self) -> None:
        if self.expected_successor_version < 1 or self.expected_predecessor_version < 1:
            raise ValueError("Supersession expected versions must be positive")
        if not self.evidence_refs:
            raise ValueError("Supersession requires evidence_refs")
        for field_name in ("actor_id", "reason_code", "idempotency_key"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be blank")
        object.__setattr__(
            self,
            "idempotency_key",
            normalize_memory_fact_idempotency_key(self.idempotency_key, required=True),
        )
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class SupersedeFactResult:
    successor: MemoryFactSnapshot
    predecessor: MemoryFactSnapshot
    decision: FactTemporalDecision
    relation: FactSupersessionRelation
    outbox_message_ids: tuple[str, ...] = ()
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ReinstateSupersededFactCommand:
    scope: MemoryFactScope
    supersession_decision_id: str
    expected_rejected_successor_version: int
    expected_original_predecessor_version: int
    evidence_refs: tuple[MemoryFactEvidenceRef, ...]
    actor_id: str
    reason_code: str
    idempotency_key: str
    authorized_code_scope: FactCodeScopeReference | None = None

    def __post_init__(self) -> None:
        if (
            self.expected_rejected_successor_version < 1
            or self.expected_original_predecessor_version < 1
        ):
            raise ValueError("Reinstatement expected versions must be positive")
        if not self.evidence_refs:
            raise ValueError("Reinstatement requires evidence_refs")
        for field_name in (
            "supersession_decision_id",
            "actor_id",
            "reason_code",
            "idempotency_key",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be blank")
        object.__setattr__(
            self,
            "idempotency_key",
            normalize_memory_fact_idempotency_key(self.idempotency_key, required=True),
        )


@dataclass(frozen=True, slots=True)
class ReinstateSupersededFactResult:
    reinstated_fact: MemoryFactSnapshot
    rejected_successor: MemoryFactSnapshot
    decision: FactTemporalDecision
    relation: FactSupersessionRelation
    outbox_message_ids: tuple[str, ...] = ()
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class SupersedeFactHandler:
    """Apply fact replacement, audit and projection intents in one transaction."""

    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort
    policy: FactSupersessionPolicy = FactSupersessionPolicy()

    async def execute(self, command: SupersedeFactCommand) -> SupersedeFactResult:
        async with self.uow_factory() as uow:
            await uow.lock_scope(command.successor_identity.scope)
            replayed = await uow.temporal_decisions.get_by_idempotency_key(
                scope=command.successor_identity.scope,
                decision_type=FactTemporalDecisionType.SUPERSEDE,
                idempotency_key=command.idempotency_key,
            )
            if replayed is not None:
                return await _replay_result(uow, command, replayed)

            ordered_identities = tuple(
                sorted(
                    (command.successor_identity, command.predecessor_identity),
                    key=memory_fact_identity_lock_key,
                )
            )
            locked = await uow.facts.get_many_for_update(ordered_identities)
            replayed = await uow.temporal_decisions.get_by_idempotency_key(
                scope=command.successor_identity.scope,
                decision_type=FactTemporalDecisionType.SUPERSEDE,
                idempotency_key=command.idempotency_key,
            )
            if replayed is not None:
                return await _replay_result(uow, command, replayed)
            by_identity = {fact.identity: fact for fact in locked}
            try:
                successor_snapshot = by_identity[command.successor_identity]
                predecessor_snapshot = by_identity[command.predecessor_identity]
            except KeyError as exc:
                raise LookupError("Supersession fact not found") from exc
            require_authorized_code_scope(
                successor_snapshot,
                command.authorized_code_scope,
            )
            require_authorized_code_scope(
                predecessor_snapshot,
                command.authorized_code_scope,
            )

            successor = MemoryFact.restore(successor_snapshot)
            predecessor = MemoryFact.restore(predecessor_snapshot)
            self.policy.validate(
                successor=successor,
                predecessor=predecessor,
                effective_at=command.effective_at,
            )
            successor.require_revision(command.expected_successor_version)
            predecessor.require_revision(command.expected_predecessor_version)
            active_relations = await uow.supersessions.list_active(scope=predecessor.identity.scope)
            self.policy.validate_graph(
                active_relations=active_relations,
                successor_fact_id=successor.identity.fact_id,
                predecessor_fact_id=predecessor.identity.fact_id,
            )

            now = self.clock.now()
            changed_successor = successor.record_as_supersession_successor(
                expected_version=command.expected_successor_version,
                effective_at=command.effective_at,
                now=now,
            )
            changed_predecessor = predecessor.supersede(
                expected_version=command.expected_predecessor_version,
                effective_at=command.effective_at,
                now=now,
            )
            saved_successor = await uow.facts.save(changed_successor.to_snapshot())
            saved_predecessor = await uow.facts.save(changed_predecessor.to_snapshot())
            successor_event = new_fact_outbox_message(
                ids=self.ids,
                fact=saved_successor,
                event_type=FACT_UPDATED_EVENT,
                occurred_at=now,
            )
            predecessor_event = new_fact_outbox_message(
                ids=self.ids,
                fact=saved_predecessor,
                event_type=FACT_SUPERSEDED_EVENT,
                occurred_at=now,
            )
            decision = FactTemporalDecision(
                decision_id=self.ids.new_temporal_decision_id(),
                decision_type=FactTemporalDecisionType.SUPERSEDE,
                scope=successor.identity.scope,
                source_fact_id=successor.identity.fact_id,
                source_fact_version=saved_successor.visibility.version,
                target_fact_id=predecessor.identity.fact_id,
                target_fact_version=saved_predecessor.visibility.version,
                effective_at=command.effective_at,
                evidence_refs=command.evidence_refs,
                actor_id=command.actor_id,
                policy_version=SUPERSESSION_POLICY_VERSION,
                reason_code=command.reason_code,
                applied_at=now,
                idempotency_key=command.idempotency_key,
                outbox_message_ids=(
                    successor_event.message_id,
                    predecessor_event.message_id,
                ),
            )
            relation = FactSupersessionRelation(
                relation_id=self.ids.new_fact_relation_id(),
                scope=successor.identity.scope,
                successor_fact_id=successor.identity.fact_id,
                successor_fact_version=saved_successor.visibility.version,
                predecessor_fact_id=predecessor.identity.fact_id,
                predecessor_fact_version=saved_predecessor.visibility.version,
                effective_at=command.effective_at,
                decision_id=decision.decision_id,
                created_at=now,
            )
            await uow.temporal_decisions.create(decision)
            await uow.supersessions.create(relation)
            await uow.outbox.enqueue(successor_event)
            await uow.outbox.enqueue(predecessor_event)
            await uow.commit()

        return SupersedeFactResult(
            successor=saved_successor,
            predecessor=saved_predecessor,
            decision=decision,
            relation=relation,
            outbox_message_ids=(successor_event.message_id, predecessor_event.message_id),
        )


@dataclass(frozen=True, slots=True)
class ReinstateSupersededFactHandler:
    """Compensate a bad replacement without rewriting or deleting its audit trail."""

    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort

    async def execute(
        self,
        command: ReinstateSupersededFactCommand,
    ) -> ReinstateSupersededFactResult:
        async with self.uow_factory() as uow:
            await uow.lock_scope(command.scope)
            replayed = await uow.temporal_decisions.get_by_idempotency_key(
                scope=command.scope,
                decision_type=FactTemporalDecisionType.REINSTATE,
                idempotency_key=command.idempotency_key,
            )
            if replayed is not None:
                return await _replay_reinstatement(uow, command, replayed)

            original = await uow.temporal_decisions.get(command.supersession_decision_id)
            if original is None:
                raise LookupError("Supersession decision not found")
            if (
                original.decision_type is not FactTemporalDecisionType.SUPERSEDE
                or original.scope != command.scope
            ):
                raise ValueError("Decision is not a supersession in the requested scope")
            identities = tuple(
                sorted(
                    (
                        MemoryFactIdentity(
                            fact_id=original.source_fact_id,
                            scope=original.scope,
                        ),
                        MemoryFactIdentity(
                            fact_id=original.target_fact_id,
                            scope=original.scope,
                        ),
                    ),
                    key=memory_fact_identity_lock_key,
                )
            )
            locked = await uow.facts.get_many_for_update(identities)
            replayed = await uow.temporal_decisions.get_by_idempotency_key(
                scope=command.scope,
                decision_type=FactTemporalDecisionType.REINSTATE,
                idempotency_key=command.idempotency_key,
            )
            if replayed is not None:
                return await _replay_reinstatement(uow, command, replayed)
            by_fact_id = {fact.identity.fact_id: fact for fact in locked}
            try:
                rejected_snapshot = by_fact_id[original.source_fact_id]
                predecessor_snapshot = by_fact_id[original.target_fact_id]
            except KeyError as exc:
                raise LookupError("Supersession compensation fact not found") from exc
            require_authorized_code_scope(
                rejected_snapshot,
                command.authorized_code_scope,
            )
            require_authorized_code_scope(
                predecessor_snapshot,
                command.authorized_code_scope,
            )
            _require_snapshot_version(
                rejected_snapshot,
                command.expected_rejected_successor_version,
            )
            _require_snapshot_version(
                predecessor_snapshot,
                command.expected_original_predecessor_version,
            )
            if await uow.temporal_decisions.find_compensation(original.decision_id):
                raise ValueError("Supersession decision is already compensated")

            now = self.clock.now()
            rejected = MemoryFact.restore(rejected_snapshot)
            predecessor = MemoryFact.restore(predecessor_snapshot)
            if (
                predecessor.lifecycle.status.value not in {"active", "superseded"}
                or predecessor.temporal_extent.valid_to != original.effective_at
            ):
                raise ValueError("Original predecessor does not match supersession audit")
            if original.effective_at >= now:
                raise ValueError("Scheduled supersession cannot be reinstated before it applies")
            changed_rejected = rejected.supersede(
                expected_version=command.expected_rejected_successor_version,
                effective_at=now,
                now=now,
            )
            restored_identity = MemoryFactIdentity(
                fact_id=self.ids.new_fact_id(),
                scope=original.scope,
            )
            source_refs = tuple(
                dict.fromkeys(
                    (
                        *predecessor.source_refs,
                        *(evidence.source_ref for evidence in command.evidence_refs),
                    )
                )
            )
            evidence_refs = tuple(
                dict.fromkeys((*predecessor.evidence_refs, *command.evidence_refs))
            )
            reinstated = MemoryFact.remember(
                identity=restored_identity,
                text=predecessor.text,
                source_refs=source_refs,
                now=now,
                kind=predecessor.kind,
                evidence_refs=evidence_refs,
                category=predecessor.category,
                tags=predecessor.tags,
                quality=predecessor.quality,
                temporal_extent=FactTemporalExtent.ongoing_state(
                    observed_at=now,
                    valid_from=now,
                    basis="compensating_decision",
                ),
                freshness=predecessor.freshness,
                retention=predecessor.retention,
                epistemic_context=predecessor.epistemic_context,
                code_scope=predecessor.code_scope,
            )
            saved_rejected = await uow.facts.save(changed_rejected.to_snapshot())
            saved_reinstated = await uow.facts.create(reinstated.to_snapshot())
            reinstated_event = new_fact_outbox_message(
                ids=self.ids,
                fact=saved_reinstated,
                event_type=FACT_CREATED_EVENT,
                occurred_at=now,
            )
            rejected_event = new_fact_outbox_message(
                ids=self.ids,
                fact=saved_rejected,
                event_type=FACT_SUPERSEDED_EVENT,
                occurred_at=now,
            )
            decision = FactTemporalDecision(
                decision_id=self.ids.new_temporal_decision_id(),
                decision_type=FactTemporalDecisionType.REINSTATE,
                scope=original.scope,
                source_fact_id=saved_reinstated.identity.fact_id,
                source_fact_version=saved_reinstated.visibility.version,
                target_fact_id=saved_rejected.identity.fact_id,
                target_fact_version=saved_rejected.visibility.version,
                effective_at=now,
                evidence_refs=command.evidence_refs,
                actor_id=command.actor_id,
                policy_version=SUPERSESSION_POLICY_VERSION,
                reason_code=command.reason_code,
                applied_at=now,
                idempotency_key=command.idempotency_key,
                compensates_decision_id=original.decision_id,
                outbox_message_ids=(
                    reinstated_event.message_id,
                    rejected_event.message_id,
                ),
            )
            relation = FactSupersessionRelation(
                relation_id=self.ids.new_fact_relation_id(),
                scope=original.scope,
                successor_fact_id=saved_reinstated.identity.fact_id,
                successor_fact_version=saved_reinstated.visibility.version,
                predecessor_fact_id=saved_rejected.identity.fact_id,
                predecessor_fact_version=saved_rejected.visibility.version,
                effective_at=now,
                decision_id=decision.decision_id,
                created_at=now,
            )
            await uow.temporal_decisions.create(decision)
            await uow.supersessions.create(relation)
            await uow.outbox.enqueue(reinstated_event)
            await uow.outbox.enqueue(rejected_event)
            await uow.commit()

        return ReinstateSupersededFactResult(
            reinstated_fact=saved_reinstated,
            rejected_successor=saved_rejected,
            decision=decision,
            relation=relation,
            outbox_message_ids=(reinstated_event.message_id, rejected_event.message_id),
        )


async def _replay_result(
    uow: MemoryFactUnitOfWorkPort,
    command: SupersedeFactCommand,
    decision: FactTemporalDecision,
) -> SupersedeFactResult:
    if (
        decision.decision_type is not FactTemporalDecisionType.SUPERSEDE
        or decision.source_fact_id != command.successor_identity.fact_id
        or decision.target_fact_id != command.predecessor_identity.fact_id
        or decision.scope != command.successor_identity.scope
        or command.predecessor_identity.scope != command.successor_identity.scope
        or decision.source_fact_version != command.expected_successor_version + 1
        or decision.target_fact_version != command.expected_predecessor_version + 1
        or decision.effective_at != command.effective_at
        or decision.evidence_refs != command.evidence_refs
        or decision.actor_id != command.actor_id
        or decision.reason_code != command.reason_code
    ):
        raise ValueError("Supersession idempotency key was reused for another command")
    successor = await _snapshot_at_version(
        uow,
        command.successor_identity,
        decision.source_fact_version,
    )
    predecessor = await _snapshot_at_version(
        uow,
        command.predecessor_identity,
        decision.target_fact_version,
    )
    relation = await uow.supersessions.find_by_decision(decision.decision_id)
    if successor is None or predecessor is None or relation is None:
        raise RuntimeError("Supersession replay audit is incomplete")
    require_authorized_code_scope(successor, command.authorized_code_scope)
    require_authorized_code_scope(predecessor, command.authorized_code_scope)
    return SupersedeFactResult(
        successor=successor,
        predecessor=predecessor,
        decision=decision,
        relation=relation,
        outbox_message_ids=decision.outbox_message_ids,
        replayed=True,
    )


async def _replay_reinstatement(
    uow: MemoryFactUnitOfWorkPort,
    command: ReinstateSupersededFactCommand,
    decision: FactTemporalDecision,
) -> ReinstateSupersededFactResult:
    original = await uow.temporal_decisions.get(command.supersession_decision_id)
    if (
        original is None
        or original.decision_type is not FactTemporalDecisionType.SUPERSEDE
        or original.scope != command.scope
        or original.target_fact_version != command.expected_original_predecessor_version
        or decision.decision_type is not FactTemporalDecisionType.REINSTATE
        or decision.scope != command.scope
        or decision.compensates_decision_id != command.supersession_decision_id
        or decision.target_fact_version != command.expected_rejected_successor_version + 1
        or decision.evidence_refs != command.evidence_refs
        or decision.actor_id != command.actor_id
        or decision.reason_code != command.reason_code
    ):
        raise ValueError("Reinstatement idempotency key was reused for another command")
    reinstated = await _snapshot_at_version(
        uow,
        MemoryFactIdentity(fact_id=decision.source_fact_id, scope=decision.scope),
        decision.source_fact_version,
    )
    rejected = await _snapshot_at_version(
        uow,
        MemoryFactIdentity(fact_id=decision.target_fact_id, scope=decision.scope),
        decision.target_fact_version,
    )
    relation = await uow.supersessions.find_by_decision(decision.decision_id)
    if reinstated is None or rejected is None or relation is None:
        raise RuntimeError("Reinstatement replay audit is incomplete")
    require_authorized_code_scope(reinstated, command.authorized_code_scope)
    require_authorized_code_scope(rejected, command.authorized_code_scope)
    return ReinstateSupersededFactResult(
        reinstated_fact=reinstated,
        rejected_successor=rejected,
        decision=decision,
        relation=relation,
        outbox_message_ids=decision.outbox_message_ids,
        replayed=True,
    )


async def _snapshot_at_version(
    uow: MemoryFactUnitOfWorkPort,
    identity: MemoryFactIdentity,
    version: int | None,
) -> MemoryFactSnapshot | None:
    if version is None:
        return None
    return next(
        (
            snapshot
            for snapshot in await uow.facts.list_versions(identity)
            if snapshot.visibility.version == version
        ),
        None,
    )


def _require_snapshot_version(fact: MemoryFactSnapshot, expected: int) -> None:
    if fact.visibility.version != expected:
        raise ValueError(
            f"Memory fact version conflict: expected {expected}, actual {fact.visibility.version}"
        )


__all__ = (
    "ReinstateSupersededFactCommand",
    "ReinstateSupersededFactHandler",
    "ReinstateSupersededFactResult",
    "SUPERSESSION_POLICY_VERSION",
    "SupersedeFactCommand",
    "SupersedeFactHandler",
    "SupersedeFactResult",
)
