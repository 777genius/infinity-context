"""Transaction-bound canonical mutations used by review/governance workflows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from infinity_context_core.features.memory_facts.application.conflicts import (
    DISPUTE_POLICY_VERSION,
)
from infinity_context_core.features.memory_facts.application.events import (
    FACT_CREATED_EVENT,
    FACT_DELETED_EVENT,
    FACT_DISPUTED_EVENT,
    FACT_SUPERSEDED_EVENT,
    FACT_UPDATED_EVENT,
    new_fact_outbox_message,
)
from infinity_context_core.features.memory_facts.application.supersession import (
    SUPERSESSION_POLICY_VERSION,
)
from infinity_context_core.features.memory_facts.domain import (
    FactCodeScopeReference,
    FactCurrentness,
    FactCurrentnessPolicy,
    FactEpistemicContext,
    FactQuality,
    FactRetention,
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
    MemoryFactSourceRef,
)
from infinity_context_core.features.memory_facts.domain.taxonomy import (
    materialize_fact_retention_expiry,
)
from infinity_context_core.features.memory_facts.ports import (
    MemoryFactClockPort,
    MemoryFactIdPort,
    MemoryFactTransactionPort,
)


@dataclass(frozen=True, slots=True)
class ReviewedFactCandidate:
    scope: MemoryFactScope
    text: str
    source_refs: tuple[MemoryFactSourceRef, ...]
    evidence_refs: tuple[MemoryFactEvidenceRef, ...]
    kind: str = "note"
    quality: FactQuality = FactQuality()
    temporal_extent: FactTemporalExtent | None = None
    category: str | None = None
    tags: tuple[str, ...] = ()
    retention: FactRetention = FactRetention()
    epistemic_context: FactEpistemicContext = FactEpistemicContext()
    code_scope: FactCodeScopeReference | None = None


@dataclass(frozen=True, slots=True)
class ReviewedFactTarget:
    identity: MemoryFactIdentity
    expected_version: int
    code_scope: FactCodeScopeReference | None = None

    def __post_init__(self) -> None:
        if self.expected_version < 1:
            raise ValueError("Reviewed fact expected_version must be positive")


@dataclass(frozen=True, slots=True)
class ReviewedFactDecision:
    candidate: ReviewedFactCandidate
    target: ReviewedFactTarget | None
    actor_id: str
    reason_code: str
    idempotency_key: str
    effective_at: datetime
    allow_weaker_evidence: bool = False

    def __post_init__(self) -> None:
        for field_name in ("actor_id", "reason_code", "idempotency_key"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be blank")
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("Reviewed fact effective_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ReviewedFactMutationResult:
    primary_fact: MemoryFactSnapshot
    affected_facts: tuple[MemoryFactSnapshot, ...]
    decision: FactTemporalDecision | None = None
    relation: FactSupersessionRelation | None = None
    outbox_message_ids: tuple[str, ...] = ()


class ReviewedFactMutationPort(Protocol):
    async def remember(self, decision: ReviewedFactDecision) -> ReviewedFactMutationResult: ...

    async def correct(self, decision: ReviewedFactDecision) -> ReviewedFactMutationResult: ...

    async def forget(self, decision: ReviewedFactDecision) -> ReviewedFactMutationResult: ...

    async def attach_evidence(
        self,
        decision: ReviewedFactDecision,
    ) -> ReviewedFactMutationResult: ...

    async def create_and_supersede(
        self,
        decision: ReviewedFactDecision,
    ) -> ReviewedFactMutationResult: ...

    async def create_and_dispute(
        self,
        decision: ReviewedFactDecision,
    ) -> ReviewedFactMutationResult: ...


@dataclass(frozen=True, slots=True)
class ReviewedFactMutationExecutor:
    """Apply reviewed changes without owning commit; the process UoW commits once."""

    transaction: MemoryFactTransactionPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort
    supersession_policy: FactSupersessionPolicy = FactSupersessionPolicy()

    async def remember(self, decision: ReviewedFactDecision) -> ReviewedFactMutationResult:
        _require_no_target(decision)
        await self._coordinate_candidate(decision.candidate)
        now = self.clock.now()
        saved = await self._create_candidate(decision.candidate, now=now)
        return await self._emit_single(saved, FACT_CREATED_EVENT, now=now)

    async def correct(self, decision: ReviewedFactDecision) -> ReviewedFactMutationResult:
        target = _require_target(decision)
        await self._coordinate_candidate(decision.candidate)
        current = await self._load_target(target)
        _require_candidate_trust(
            decision.candidate,
            current,
            allow_weaker=decision.allow_weaker_evidence,
        )
        candidate = decision.candidate
        now = self.clock.now()
        changed = MemoryFact.restore(current).update(
            expected_version=target.expected_version,
            text=candidate.text,
            source_refs=candidate.source_refs,
            now=now,
            kind=candidate.kind,
            evidence_refs=candidate.evidence_refs,
            category=candidate.category,
            tags=candidate.tags,
            retention=materialize_fact_retention_expiry(
                candidate.retention,
                now=now,
            ),
        )
        saved = await self.transaction.facts.save(changed.to_snapshot())
        return await self._emit_single(saved, FACT_UPDATED_EVENT, now=_updated_at(saved))

    async def forget(self, decision: ReviewedFactDecision) -> ReviewedFactMutationResult:
        target = _require_target(decision)
        current = await self._load_target(target)
        _require_candidate_trust(
            decision.candidate,
            current,
            allow_weaker=decision.allow_weaker_evidence,
        )
        now = self.clock.now()
        changed = MemoryFact.restore(current).forget(
            expected_version=target.expected_version,
            now=now,
        )
        saved = await self.transaction.facts.save(changed.to_snapshot())
        return await self._emit_single(saved, FACT_DELETED_EVENT, now=now)

    async def attach_evidence(
        self,
        decision: ReviewedFactDecision,
    ) -> ReviewedFactMutationResult:
        target = _require_target(decision)
        await self._coordinate_candidate(decision.candidate)
        current = await self._load_target(target)
        _require_candidate_trust(
            decision.candidate,
            current,
            allow_weaker=decision.allow_weaker_evidence,
        )
        now = self.clock.now()
        changed = MemoryFact.restore(current).attach_evidence(
            expected_version=target.expected_version,
            source_refs=decision.candidate.source_refs,
            evidence_refs=decision.candidate.evidence_refs,
            now=now,
        )
        saved = await self.transaction.facts.save(changed.to_snapshot())
        return await self._emit_single(saved, FACT_UPDATED_EVENT, now=now)

    async def create_and_supersede(
        self,
        decision: ReviewedFactDecision,
    ) -> ReviewedFactMutationResult:
        target = _require_target(decision)
        await self.transaction.lock_scope(target.identity.scope)
        await self._coordinate_candidate(decision.candidate)
        predecessor_snapshot = await self._load_target(target)
        _require_candidate_trust(
            decision.candidate,
            predecessor_snapshot,
            allow_weaker=decision.allow_weaker_evidence,
        )
        now = self.clock.now()
        predecessor = MemoryFact.restore(predecessor_snapshot)
        successor_candidate = _inherit_target_disclosure(
            decision.candidate,
            predecessor_snapshot,
        )
        successor_extent = successor_candidate.temporal_extent or FactTemporalExtent.ongoing_state(
            observed_at=now,
            valid_from=decision.effective_at,
            basis="asserted",
        )
        effective_at = successor_extent.valid_from
        if effective_at is None:
            raise ValueError("Supersession successor valid_from is required")
        if effective_at > now:
            raise ValueError("Scheduled supersession is not supported")
        successor_candidate = replace(
            successor_candidate,
            temporal_extent=successor_extent,
        )
        successor = MemoryFact.restore(await self._create_candidate(successor_candidate, now=now))
        active_relations = await self.transaction.supersessions.list_active(
            scope=target.identity.scope
        )
        self.supersession_policy.validate(
            successor=successor,
            predecessor=predecessor,
            effective_at=effective_at,
        )
        self.supersession_policy.validate_graph(
            active_relations=active_relations,
            successor_fact_id=successor.identity.fact_id,
            predecessor_fact_id=predecessor.identity.fact_id,
        )
        saved_successor = await self.transaction.facts.save(
            successor.record_as_supersession_successor(
                expected_version=1,
                effective_at=effective_at,
                now=now,
            ).to_snapshot()
        )
        saved_predecessor = await self.transaction.facts.save(
            predecessor.supersede(
                expected_version=target.expected_version,
                effective_at=effective_at,
                now=now,
            ).to_snapshot()
        )
        successor_event = new_fact_outbox_message(
            ids=self.ids,
            fact=saved_successor,
            event_type=FACT_CREATED_EVENT,
            occurred_at=now,
        )
        predecessor_event = new_fact_outbox_message(
            ids=self.ids,
            fact=saved_predecessor,
            event_type=FACT_SUPERSEDED_EVENT,
            occurred_at=now,
        )
        audit = FactTemporalDecision(
            decision_id=self.ids.new_temporal_decision_id(),
            decision_type=FactTemporalDecisionType.SUPERSEDE,
            scope=target.identity.scope,
            source_fact_id=saved_successor.identity.fact_id,
            source_fact_version=saved_successor.visibility.version,
            target_fact_id=saved_predecessor.identity.fact_id,
            target_fact_version=saved_predecessor.visibility.version,
            effective_at=effective_at,
            evidence_refs=decision.candidate.evidence_refs,
            actor_id=decision.actor_id,
            policy_version=SUPERSESSION_POLICY_VERSION,
            reason_code=decision.reason_code,
            applied_at=now,
            idempotency_key=decision.idempotency_key,
            outbox_message_ids=(successor_event.message_id, predecessor_event.message_id),
        )
        relation = FactSupersessionRelation(
            relation_id=self.ids.new_fact_relation_id(),
            scope=target.identity.scope,
            successor_fact_id=saved_successor.identity.fact_id,
            successor_fact_version=saved_successor.visibility.version,
            predecessor_fact_id=saved_predecessor.identity.fact_id,
            predecessor_fact_version=saved_predecessor.visibility.version,
            effective_at=effective_at,
            decision_id=audit.decision_id,
            created_at=now,
        )
        await self.transaction.temporal_decisions.create(audit)
        await self.transaction.supersessions.create(relation)
        await self.transaction.outbox.enqueue(successor_event)
        await self.transaction.outbox.enqueue(predecessor_event)
        return ReviewedFactMutationResult(
            primary_fact=saved_successor,
            affected_facts=(saved_successor, saved_predecessor),
            decision=audit,
            relation=relation,
            outbox_message_ids=(successor_event.message_id, predecessor_event.message_id),
        )

    async def create_and_dispute(
        self,
        decision: ReviewedFactDecision,
    ) -> ReviewedFactMutationResult:
        target = _require_target(decision)
        await self._coordinate_candidate(decision.candidate)
        challenged_snapshot = await self._load_target(target)
        _require_candidate_trust(
            decision.candidate,
            challenged_snapshot,
            allow_weaker=decision.allow_weaker_evidence,
        )
        now = self.clock.now()
        challenger_candidate = _inherit_target_disclosure(
            decision.candidate,
            challenged_snapshot,
        )
        challenger = MemoryFact.restore(await self._create_candidate(challenger_candidate, now=now))
        challenged = MemoryFact.restore(challenged_snapshot)
        if not challenger.epistemic_context.is_automatically_comparable_with(
            challenged.epistemic_context
        ):
            raise ValueError("Dispute requires comparable epistemic contexts")
        if any(
            FactCurrentnessPolicy()
            .assess(
                fact.temporal_extent,
                reference_time=now,
                freshness=fact.freshness,
            )
            .state
            is not FactCurrentness.CURRENT
            for fact in (challenger, challenged)
        ):
            raise ValueError("Dispute requires two currently valid facts")
        saved_challenger = await self.transaction.facts.save(
            challenger.dispute(expected_version=1, now=now).to_snapshot()
        )
        saved_challenged = await self.transaction.facts.save(
            challenged.dispute(expected_version=target.expected_version, now=now).to_snapshot()
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
        audit = FactTemporalDecision(
            decision_id=self.ids.new_temporal_decision_id(),
            decision_type=FactTemporalDecisionType.DISPUTE,
            scope=target.identity.scope,
            source_fact_id=saved_challenger.identity.fact_id,
            source_fact_version=saved_challenger.visibility.version,
            target_fact_id=saved_challenged.identity.fact_id,
            target_fact_version=saved_challenged.visibility.version,
            effective_at=now,
            evidence_refs=decision.candidate.evidence_refs,
            actor_id=decision.actor_id,
            policy_version=DISPUTE_POLICY_VERSION,
            reason_code=decision.reason_code,
            applied_at=now,
            idempotency_key=decision.idempotency_key,
            outbox_message_ids=(challenger_event.message_id, challenged_event.message_id),
        )
        await self.transaction.temporal_decisions.create(audit)
        await self.transaction.outbox.enqueue(challenger_event)
        await self.transaction.outbox.enqueue(challenged_event)
        return ReviewedFactMutationResult(
            primary_fact=saved_challenger,
            affected_facts=(saved_challenger, saved_challenged),
            decision=audit,
            outbox_message_ids=(challenger_event.message_id, challenged_event.message_id),
        )

    async def _create_candidate(
        self,
        candidate: ReviewedFactCandidate,
        *,
        now: datetime,
    ) -> MemoryFactSnapshot:
        aggregate = MemoryFact.remember(
            identity=MemoryFactIdentity(self.ids.new_fact_id(), candidate.scope),
            text=candidate.text,
            source_refs=candidate.source_refs,
            now=now,
            kind=candidate.kind,
            evidence_refs=candidate.evidence_refs,
            category=candidate.category,
            tags=candidate.tags,
            quality=candidate.quality,
            temporal_extent=candidate.temporal_extent
            or FactTemporalExtent.ongoing_state(
                observed_at=now,
                valid_from=now,
                basis="asserted",
            ),
            retention=materialize_fact_retention_expiry(
                candidate.retention,
                now=now,
            ),
            epistemic_context=candidate.epistemic_context,
            code_scope=candidate.code_scope,
        )
        return await self.transaction.facts.create(aggregate.to_snapshot())

    async def _coordinate_candidate(self, candidate: ReviewedFactCandidate) -> None:
        await self.transaction.coordinate_source_refs(
            scope=candidate.scope,
            source_refs=candidate.source_refs,
        )

    async def _load_target(self, target: ReviewedFactTarget) -> MemoryFactSnapshot:
        current = await self.transaction.facts.get_for_update(target.identity)
        if current is None:
            raise LookupError(f"Memory fact not found: {target.identity.fact_id}")
        if current.visibility.version != target.expected_version:
            raise ValueError("Stale reviewed fact version")
        if current.code_scope != target.code_scope:
            raise ValueError("Reviewed fact code scope mismatch")
        return current

    async def _emit_single(
        self,
        fact: MemoryFactSnapshot,
        event_type: str,
        *,
        now: datetime,
    ) -> ReviewedFactMutationResult:
        event = new_fact_outbox_message(
            ids=self.ids,
            fact=fact,
            event_type=event_type,
            occurred_at=now,
        )
        await self.transaction.outbox.enqueue(event)
        return ReviewedFactMutationResult(
            primary_fact=fact,
            affected_facts=(fact,),
            outbox_message_ids=(event.message_id,),
        )


def _require_target(decision: ReviewedFactDecision) -> ReviewedFactTarget:
    if decision.target is None:
        raise ValueError("Reviewed mutation requires target fact")
    if decision.candidate.scope != decision.target.identity.scope:
        raise ValueError("Reviewed mutation cannot cross fact scope")
    return decision.target


def _require_no_target(decision: ReviewedFactDecision) -> None:
    if decision.target is not None:
        raise ValueError("Reviewed remember cannot target an existing fact")


def _updated_at(fact: MemoryFactSnapshot) -> datetime:
    if fact.updated_at is None:
        raise RuntimeError("Canonical fact mutation did not set updated_at")
    return fact.updated_at


def _require_candidate_trust(
    candidate: ReviewedFactCandidate,
    target: MemoryFactSnapshot,
    *,
    allow_weaker: bool,
) -> None:
    rank = {"low": 1, "medium": 2, "high": 3}
    if (
        rank[candidate.quality.trust_level.value]
        < rank[str(target.visibility.trust_level).casefold()]
        and not allow_weaker
    ):
        raise ValueError("Weak reviewed evidence cannot mutate a stronger fact")


def _inherit_target_disclosure(
    candidate: ReviewedFactCandidate,
    target: MemoryFactSnapshot,
) -> ReviewedFactCandidate:
    return replace(
        candidate,
        quality=FactQuality(
            confidence=candidate.quality.confidence,
            trust_level=candidate.quality.trust_level,
            classification=target.visibility.classification,
        ),
    )


__all__ = (
    "ReviewedFactCandidate",
    "ReviewedFactDecision",
    "ReviewedFactMutationExecutor",
    "ReviewedFactMutationPort",
    "ReviewedFactMutationResult",
    "ReviewedFactTarget",
)
