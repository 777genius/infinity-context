"""Atomic conflict admission for mutually comparable canonical claims."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.memory_facts.application.authorization import (
    require_authorized_code_scope,
)
from infinity_context_core.features.memory_facts.application.events import (
    FACT_DISPUTED_EVENT,
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
    FactCurrentness,
    FactCurrentnessPolicy,
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

DISPUTE_POLICY_VERSION = "fact-dispute-v1"


@dataclass(frozen=True, slots=True)
class DisputeFactsCommand:
    challenger_identity: MemoryFactIdentity
    challenged_identity: MemoryFactIdentity
    expected_challenger_version: int
    expected_challenged_version: int
    evidence_refs: tuple[MemoryFactEvidenceRef, ...]
    actor_id: str
    reason_code: str
    idempotency_key: str
    authorized_code_scope: FactCodeScopeReference | None = None

    def __post_init__(self) -> None:
        if self.expected_challenger_version < 1 or self.expected_challenged_version < 1:
            raise ValueError("Dispute expected versions must be positive")
        if not self.evidence_refs:
            raise ValueError("Dispute requires evidence_refs")
        for field_name in ("actor_id", "reason_code", "idempotency_key"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be blank")
        object.__setattr__(
            self,
            "idempotency_key",
            normalize_memory_fact_idempotency_key(self.idempotency_key, required=True),
        )


@dataclass(frozen=True, slots=True)
class DisputeFactsResult:
    challenger: MemoryFactSnapshot
    challenged: MemoryFactSnapshot
    decision: FactTemporalDecision
    outbox_message_ids: tuple[str, ...] = ()
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class DisputeFactsHandler:
    """Remove both sides of a credible conflict from normal prompt context."""

    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort

    async def execute(self, command: DisputeFactsCommand) -> DisputeFactsResult:
        async with self.uow_factory() as uow:
            replayed = await uow.temporal_decisions.get_by_idempotency_key(
                scope=command.challenger_identity.scope,
                decision_type=FactTemporalDecisionType.DISPUTE,
                idempotency_key=command.idempotency_key,
            )
            if replayed is not None:
                return await _replay_dispute(uow, command, replayed)
            identities = tuple(
                sorted(
                    (command.challenger_identity, command.challenged_identity),
                    key=memory_fact_identity_lock_key,
                )
            )
            locked = await uow.facts.get_many_for_update(identities)
            replayed = await uow.temporal_decisions.get_by_idempotency_key(
                scope=command.challenger_identity.scope,
                decision_type=FactTemporalDecisionType.DISPUTE,
                idempotency_key=command.idempotency_key,
            )
            if replayed is not None:
                return await _replay_dispute(uow, command, replayed)
            by_identity = {fact.identity: fact for fact in locked}
            try:
                challenger_snapshot = by_identity[command.challenger_identity]
                challenged_snapshot = by_identity[command.challenged_identity]
            except KeyError as exc:
                raise LookupError("Dispute fact not found") from exc
            require_authorized_code_scope(
                challenger_snapshot,
                command.authorized_code_scope,
            )
            require_authorized_code_scope(
                challenged_snapshot,
                command.authorized_code_scope,
            )
            challenger = MemoryFact.restore(challenger_snapshot)
            challenged = MemoryFact.restore(challenged_snapshot)
            if challenger.identity.fact_id == challenged.identity.fact_id:
                raise ValueError("Fact cannot dispute itself")
            if challenger.identity.scope != challenged.identity.scope:
                raise ValueError("Dispute cannot cross fact scope")
            if challenger.code_scope != challenged.code_scope:
                raise ValueError("Dispute cannot cross code scope")
            if not challenger.epistemic_context.is_automatically_comparable_with(
                challenged.epistemic_context
            ):
                raise ValueError("Dispute requires comparable epistemic contexts")
            challenger.require_revision(command.expected_challenger_version)
            challenged.require_revision(command.expected_challenged_version)
            now = self.clock.now()
            currentness = FactCurrentnessPolicy()
            if any(
                currentness.assess(fact.temporal_extent, reference_time=now).state
                is not FactCurrentness.CURRENT
                for fact in (challenger, challenged)
            ):
                raise ValueError("Dispute requires two currently valid facts")
            saved_challenger = await uow.facts.save(
                challenger.dispute(
                    expected_version=command.expected_challenger_version,
                    now=now,
                ).to_snapshot()
            )
            saved_challenged = await uow.facts.save(
                challenged.dispute(
                    expected_version=command.expected_challenged_version,
                    now=now,
                ).to_snapshot()
            )
            challenger_event = new_fact_outbox_message(
                ids=self.ids,
                fact=saved_challenger,
                event_type=FACT_DISPUTED_EVENT,
                occurred_at=now,
            )
            challenged_event = new_fact_outbox_message(
                ids=self.ids,
                fact=saved_challenged,
                event_type=FACT_DISPUTED_EVENT,
                occurred_at=now,
            )
            decision = FactTemporalDecision(
                decision_id=self.ids.new_temporal_decision_id(),
                decision_type=FactTemporalDecisionType.DISPUTE,
                scope=challenger.identity.scope,
                source_fact_id=challenger.identity.fact_id,
                source_fact_version=saved_challenger.visibility.version,
                target_fact_id=challenged.identity.fact_id,
                target_fact_version=saved_challenged.visibility.version,
                effective_at=now,
                evidence_refs=command.evidence_refs,
                actor_id=command.actor_id,
                policy_version=DISPUTE_POLICY_VERSION,
                reason_code=command.reason_code,
                applied_at=now,
                idempotency_key=command.idempotency_key,
                outbox_message_ids=(
                    challenger_event.message_id,
                    challenged_event.message_id,
                ),
            )
            await uow.temporal_decisions.create(decision)
            await uow.outbox.enqueue(challenger_event)
            await uow.outbox.enqueue(challenged_event)
            await uow.commit()

        return DisputeFactsResult(
            challenger=saved_challenger,
            challenged=saved_challenged,
            decision=decision,
            outbox_message_ids=(challenger_event.message_id, challenged_event.message_id),
        )


async def _replay_dispute(
    uow: MemoryFactUnitOfWorkPort,
    command: DisputeFactsCommand,
    decision: FactTemporalDecision,
) -> DisputeFactsResult:
    if (
        decision.decision_type is not FactTemporalDecisionType.DISPUTE
        or decision.scope != command.challenger_identity.scope
        or command.challenged_identity.scope != command.challenger_identity.scope
        or decision.source_fact_id != command.challenger_identity.fact_id
        or decision.target_fact_id != command.challenged_identity.fact_id
        or decision.source_fact_version != command.expected_challenger_version + 1
        or decision.target_fact_version != command.expected_challenged_version + 1
        or decision.evidence_refs != command.evidence_refs
        or decision.actor_id != command.actor_id
        or decision.reason_code != command.reason_code
    ):
        raise ValueError("Dispute idempotency key was reused for another command")
    challenger = await _snapshot_at_version(
        uow,
        command.challenger_identity,
        decision.source_fact_version,
    )
    challenged = await _snapshot_at_version(
        uow,
        command.challenged_identity,
        decision.target_fact_version,
    )
    if challenger is None or challenged is None:
        raise RuntimeError("Dispute replay audit is incomplete")
    require_authorized_code_scope(challenger, command.authorized_code_scope)
    require_authorized_code_scope(challenged, command.authorized_code_scope)
    return DisputeFactsResult(
        challenger=challenger,
        challenged=challenged,
        decision=decision,
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


__all__ = (
    "DisputeFactsCommand",
    "DisputeFactsHandler",
    "DisputeFactsResult",
)
