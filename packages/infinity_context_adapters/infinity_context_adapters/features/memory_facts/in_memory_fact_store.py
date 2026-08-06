"""In-memory repository, outbox and unit-of-work seam for memory_facts adapters."""

from __future__ import annotations

from collections.abc import Iterable
from types import TracebackType
from typing import ClassVar

from infinity_context_core.features.memory_facts.public import (
    FEATURE_ID,
    FactEligibilityPolicy,
    FactSupersessionRelation,
    FactTemporalDecision,
    FactTemporalDecisionType,
    MemoryFactIdentity,
    MemoryFactOperationReceipt,
    MemoryFactOutboxMessage,
    MemoryFactRepositoryPort,
    MemoryFactScope,
    MemoryFactSelectionQuery,
    MemoryFactSnapshot,
    MemoryFactUnitOfWorkFactoryPort,
)

_FactKey = tuple[str, str, str | None, str]
_IdempotencyKey = tuple[str, str, str | None, FactTemporalDecisionType, str]
_OperationReceiptKey = tuple[str, str, str | None, str, str]


class _InMemoryMemoryFactState:
    def __init__(self, facts: Iterable[MemoryFactSnapshot] = ()) -> None:
        self._facts: dict[_FactKey, MemoryFactSnapshot] = {}
        self._versions: dict[_FactKey, list[MemoryFactSnapshot]] = {}
        self._outbox_messages: list[MemoryFactOutboxMessage] = []
        self._temporal_decisions: dict[str, FactTemporalDecision] = {}
        self._decision_idempotency: dict[_IdempotencyKey, str] = {}
        self._operation_receipts: dict[_OperationReceiptKey, MemoryFactOperationReceipt] = {}
        self._supersessions: list[FactSupersessionRelation] = []
        self._revision = 0
        for fact in facts:
            self._put(fact, allow_existing=False)
            self._versions[_fact_key(fact.identity)] = [fact]

    def snapshot(
        self,
    ) -> tuple[
        dict[_FactKey, MemoryFactSnapshot],
        dict[_FactKey, list[MemoryFactSnapshot]],
        list[MemoryFactOutboxMessage],
        dict[str, FactTemporalDecision],
        dict[_IdempotencyKey, str],
        dict[_OperationReceiptKey, MemoryFactOperationReceipt],
        list[FactSupersessionRelation],
        int,
    ]:
        return (
            dict(self._facts),
            {key: list(versions) for key, versions in self._versions.items()},
            list(self._outbox_messages),
            dict(self._temporal_decisions),
            dict(self._decision_idempotency),
            dict(self._operation_receipts),
            list(self._supersessions),
            self._revision,
        )

    def replace(
        self,
        facts: dict[_FactKey, MemoryFactSnapshot],
        versions: dict[_FactKey, list[MemoryFactSnapshot]],
        outbox_messages: list[MemoryFactOutboxMessage],
        temporal_decisions: dict[str, FactTemporalDecision],
        decision_idempotency: dict[_IdempotencyKey, str],
        operation_receipts: dict[_OperationReceiptKey, MemoryFactOperationReceipt],
        supersessions: list[FactSupersessionRelation],
        expected_revision: int,
    ) -> None:
        if self._revision != expected_revision:
            raise ValueError("In-memory fact transaction conflict")
        self._facts = dict(facts)
        self._versions = {key: list(items) for key, items in versions.items()}
        self._outbox_messages = list(outbox_messages)
        self._temporal_decisions = dict(temporal_decisions)
        self._decision_idempotency = dict(decision_idempotency)
        self._operation_receipts = dict(operation_receipts)
        self._supersessions = list(supersessions)
        self._revision += 1

    def facts(self) -> tuple[MemoryFactSnapshot, ...]:
        return tuple(self._facts.values())

    def outbox_messages(self) -> tuple[MemoryFactOutboxMessage, ...]:
        return tuple(self._outbox_messages)

    def temporal_decisions(self) -> tuple[FactTemporalDecision, ...]:
        return tuple(self._temporal_decisions.values())

    def supersessions(self) -> tuple[FactSupersessionRelation, ...]:
        return tuple(self._supersessions)

    def _put(
        self,
        fact: MemoryFactSnapshot,
        *,
        allow_existing: bool,
    ) -> None:
        key = _fact_key(fact.identity)
        if not allow_existing and key in self._facts:
            raise ValueError("memory_fact_already_exists")
        self._facts[key] = fact


class InMemoryMemoryFactRepository:
    """Stdlib-only MemoryFactRepositoryPort implementation."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, facts: dict[_FactKey, MemoryFactSnapshot] | None = None) -> None:
        self._facts = facts if facts is not None else {}
        self._versions: dict[_FactKey, list[MemoryFactSnapshot]] = {}

    @classmethod
    def transactional(
        cls,
        facts: dict[_FactKey, MemoryFactSnapshot],
        versions: dict[_FactKey, list[MemoryFactSnapshot]],
    ) -> InMemoryMemoryFactRepository:
        repository = cls(facts)
        repository._versions = versions
        return repository

    async def create(self, fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        key = _fact_key(fact.identity)
        if key in self._facts:
            raise ValueError("memory_fact_already_exists")
        self._facts[key] = fact
        self._versions[key] = [fact]
        return fact

    async def get(self, identity: MemoryFactIdentity) -> MemoryFactSnapshot | None:
        return self._facts.get(_fact_key(identity))

    async def get_for_update(
        self,
        identity: MemoryFactIdentity,
    ) -> MemoryFactSnapshot | None:
        return await self.get(identity)

    async def get_many_for_update(
        self,
        identities: tuple[MemoryFactIdentity, ...],
    ) -> tuple[MemoryFactSnapshot, ...]:
        return tuple(
            fact
            for identity in identities
            if (fact := self._facts.get(_fact_key(identity))) is not None
        )

    async def save(self, fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        key = _fact_key(fact.identity)
        if key not in self._facts:
            raise KeyError("memory_fact_not_found")
        current_version = self._facts[key].visibility.version
        if fact.visibility.version != current_version + 1:
            raise ValueError(
                "Memory fact version conflict: "
                f"expected {current_version + 1}, actual {fact.visibility.version}"
            )
        self._facts[key] = fact
        self._versions.setdefault(key, []).append(fact)
        return fact

    async def list_versions(
        self,
        identity: MemoryFactIdentity,
    ) -> tuple[MemoryFactSnapshot, ...]:
        return tuple(self._versions.get(_fact_key(identity), ()))

    async def find_eligible(
        self,
        query: MemoryFactSelectionQuery,
    ) -> tuple[MemoryFactSnapshot, ...]:
        policy = FactEligibilityPolicy()
        candidates = (
            fact
            for fact in self._facts.values()
            if fact.identity.scope.space_id == query.space_id
            and fact.identity.scope.memory_scope_id in query.memory_scope_ids
            and (not query.fact_ids or fact.identity.fact_id in query.fact_ids)
            and (
                fact.identity.scope.thread_id is None
                if query.thread_id is None
                else fact.identity.scope.thread_id in {None, query.thread_id}
            )
            and (
                fact.code_scope is None
                or fact.code_scope.is_visible_in(
                    repository_id=query.repository_id,
                    code_scope_id=query.code_scope_id,
                )
            )
            and policy.assess(
                fact,
                mode=query.temporal_mode,
                reference_time=query.reference_time,
            ).eligible
        )
        return tuple(
            sorted(
                candidates,
                key=lambda fact: fact.identity.fact_id,
            )[: query.limit]
        )


class InMemoryMemoryFactOutbox:
    """Stdlib-only MemoryFactOutboxPort implementation."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, messages: list[MemoryFactOutboxMessage] | None = None) -> None:
        self._messages = messages if messages is not None else []

    @property
    def messages(self) -> tuple[MemoryFactOutboxMessage, ...]:
        return tuple(self._messages)

    async def enqueue(self, message: MemoryFactOutboxMessage) -> None:
        self._messages.append(message)


class InMemoryFactTemporalDecisionRepository:
    """Append-only temporal decisions sharing the fact transaction."""

    def __init__(
        self,
        decisions: dict[str, FactTemporalDecision],
        idempotency: dict[_IdempotencyKey, str],
    ) -> None:
        self._decisions = decisions
        self._idempotency = idempotency

    async def create(self, decision: FactTemporalDecision) -> FactTemporalDecision:
        key = (
            decision.scope.space_id,
            decision.scope.memory_scope_id,
            decision.scope.thread_id,
            decision.decision_type,
            decision.idempotency_key,
        )
        if decision.decision_id in self._decisions:
            if self._decisions[decision.decision_id] == decision:
                return decision
            raise ValueError("Temporal decision is append-only")
        if key in self._idempotency:
            raise ValueError("Temporal decision idempotency conflict")
        self._decisions[decision.decision_id] = decision
        self._idempotency[key] = decision.decision_id
        return decision

    async def get(self, decision_id: str) -> FactTemporalDecision | None:
        return self._decisions.get(decision_id)

    async def get_by_idempotency_key(
        self,
        *,
        scope: MemoryFactScope,
        decision_type: FactTemporalDecisionType,
        idempotency_key: str,
    ) -> FactTemporalDecision | None:
        decision_id = self._idempotency.get(
            (
                scope.space_id,
                scope.memory_scope_id,
                scope.thread_id,
                FactTemporalDecisionType(decision_type),
                idempotency_key,
            )
        )
        return self._decisions.get(decision_id) if decision_id is not None else None

    async def find_compensation(
        self,
        decision_id: str,
    ) -> FactTemporalDecision | None:
        return next(
            (
                decision
                for decision in self._decisions.values()
                if decision.compensates_decision_id == decision_id
            ),
            None,
        )


class InMemoryMemoryFactOperationReceiptRepository:
    """Immutable retry receipts sharing the canonical fact transaction."""

    def __init__(
        self,
        receipts: dict[_OperationReceiptKey, MemoryFactOperationReceipt],
    ) -> None:
        self._receipts = receipts

    async def create(
        self,
        receipt: MemoryFactOperationReceipt,
    ) -> MemoryFactOperationReceipt:
        key = _operation_receipt_key(
            space_id=receipt.space_id,
            memory_scope_id=receipt.memory_scope_id,
            thread_id=receipt.thread_id,
            operation=receipt.operation,
            idempotency_key=receipt.idempotency_key,
        )
        existing = self._receipts.get(key)
        if existing is not None:
            if existing == receipt:
                return existing
            raise ValueError("Fact operation receipt is append-only")
        self._receipts[key] = receipt
        return receipt

    async def get(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        operation: str,
        idempotency_key: str,
    ) -> MemoryFactOperationReceipt | None:
        return self._receipts.get(
            _operation_receipt_key(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                thread_id=thread_id,
                operation=operation,
                idempotency_key=idempotency_key,
            )
        )


def _operation_receipt_key(
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str | None,
    operation: str,
    idempotency_key: str,
) -> _OperationReceiptKey:
    return (space_id, memory_scope_id, thread_id, operation, idempotency_key)


class InMemoryFactSupersessionRepository:
    """Immutable supersession edges sharing the fact transaction."""

    def __init__(self, relations: list[FactSupersessionRelation]) -> None:
        self._relations = relations

    async def create(
        self,
        relation: FactSupersessionRelation,
    ) -> FactSupersessionRelation:
        for existing in self._relations:
            if existing.relation_id == relation.relation_id:
                if existing == relation:
                    return relation
                raise ValueError("Supersession relation is append-only")
            if (
                existing.scope == relation.scope
                and existing.predecessor_fact_id == relation.predecessor_fact_id
            ):
                raise ValueError("Supersession predecessor already has a successor")
            if (
                existing.scope == relation.scope
                and existing.successor_fact_id == relation.successor_fact_id
            ):
                raise ValueError("Supersession successor already replaces another fact")
        self._relations.append(relation)
        return relation

    async def find_active_successor(
        self,
        *,
        scope: MemoryFactScope,
        predecessor_fact_id: str,
    ) -> FactSupersessionRelation | None:
        return next(
            (
                relation
                for relation in self._relations
                if relation.scope == scope and relation.predecessor_fact_id == predecessor_fact_id
            ),
            None,
        )

    async def find_active_predecessor(
        self,
        *,
        scope: MemoryFactScope,
        successor_fact_id: str,
    ) -> FactSupersessionRelation | None:
        return next(
            (
                relation
                for relation in self._relations
                if relation.scope == scope and relation.successor_fact_id == successor_fact_id
            ),
            None,
        )

    async def find_by_decision(
        self,
        decision_id: str,
    ) -> FactSupersessionRelation | None:
        return next(
            (relation for relation in self._relations if relation.decision_id == decision_id),
            None,
        )

    async def list_active(
        self,
        *,
        scope: MemoryFactScope,
    ) -> tuple[FactSupersessionRelation, ...]:
        return tuple(relation for relation in self._relations if relation.scope == scope)


class InMemoryMemoryFactUnitOfWork:
    """Transactional unit-of-work seam backed by in-memory snapshots."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, state: _InMemoryMemoryFactState | None = None) -> None:
        self._state = state or _InMemoryMemoryFactState()
        (
            self._working_facts,
            self._working_versions,
            self._working_outbox_messages,
            self._working_temporal_decisions,
            self._working_decision_idempotency,
            self._working_operation_receipts,
            self._working_supersessions,
            self._base_revision,
        ) = self._state.snapshot()
        self.facts = InMemoryMemoryFactRepository.transactional(
            self._working_facts,
            self._working_versions,
        )
        self.outbox = InMemoryMemoryFactOutbox(self._working_outbox_messages)
        self.temporal_decisions = InMemoryFactTemporalDecisionRepository(
            self._working_temporal_decisions,
            self._working_decision_idempotency,
        )
        self.operation_receipts = InMemoryMemoryFactOperationReceiptRepository(
            self._working_operation_receipts
        )
        self.supersessions = InMemoryFactSupersessionRepository(self._working_supersessions)
        self._committed = False

    async def __aenter__(self) -> InMemoryMemoryFactUnitOfWork:
        return self

    async def lock_scope(self, scope: MemoryFactScope) -> None:
        del scope
        # The shared-state optimistic revision check serializes in-memory commits.

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        if exc_type is not None or not self._committed:
            await self.rollback()

    async def commit(self) -> None:
        self._state.replace(
            self._working_facts,
            self._working_versions,
            self._working_outbox_messages,
            self._working_temporal_decisions,
            self._working_decision_idempotency,
            self._working_operation_receipts,
            self._working_supersessions,
            self._base_revision,
        )
        self._committed = True

    async def rollback(self) -> None:
        (
            self._working_facts,
            self._working_versions,
            self._working_outbox_messages,
            self._working_temporal_decisions,
            self._working_decision_idempotency,
            self._working_operation_receipts,
            self._working_supersessions,
            self._base_revision,
        ) = self._state.snapshot()
        self.facts = InMemoryMemoryFactRepository.transactional(
            self._working_facts,
            self._working_versions,
        )
        self.outbox = InMemoryMemoryFactOutbox(self._working_outbox_messages)
        self.temporal_decisions = InMemoryFactTemporalDecisionRepository(
            self._working_temporal_decisions,
            self._working_decision_idempotency,
        )
        self.operation_receipts = InMemoryMemoryFactOperationReceiptRepository(
            self._working_operation_receipts
        )
        self.supersessions = InMemoryFactSupersessionRepository(self._working_supersessions)
        self._committed = False


class InMemoryMemoryFactUnitOfWorkFactory:
    """Factory that shares one in-memory canonical state across UoWs."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, facts: Iterable[MemoryFactSnapshot] = ()) -> None:
        self._state = _InMemoryMemoryFactState(facts)

    @property
    def facts(self) -> tuple[MemoryFactSnapshot, ...]:
        return self._state.facts()

    @property
    def outbox_messages(self) -> tuple[MemoryFactOutboxMessage, ...]:
        return self._state.outbox_messages()

    @property
    def temporal_decisions(self) -> tuple[FactTemporalDecision, ...]:
        return self._state.temporal_decisions()

    @property
    def supersessions(self) -> tuple[FactSupersessionRelation, ...]:
        return self._state.supersessions()

    def __call__(self) -> InMemoryMemoryFactUnitOfWork:
        return InMemoryMemoryFactUnitOfWork(self._state)


def create_in_memory_memory_fact_store(
    facts: Iterable[MemoryFactSnapshot] = (),
) -> MemoryFactRepositoryPort:
    """Create a standalone in-memory memory fact repository."""

    working_facts, working_versions, *_rest = _InMemoryMemoryFactState(facts).snapshot()
    return InMemoryMemoryFactRepository.transactional(working_facts, working_versions)


def create_in_memory_memory_fact_unit_of_work_factory(
    facts: Iterable[MemoryFactSnapshot] = (),
) -> MemoryFactUnitOfWorkFactoryPort:
    """Create an in-memory memory fact unit-of-work factory."""

    return InMemoryMemoryFactUnitOfWorkFactory(facts)


def _fact_key(identity: MemoryFactIdentity) -> _FactKey:
    scope = identity.scope
    return (
        scope.space_id,
        scope.memory_scope_id,
        scope.thread_id,
        identity.fact_id,
    )


__all__ = (
    "InMemoryFactSupersessionRepository",
    "InMemoryFactTemporalDecisionRepository",
    "InMemoryMemoryFactOutbox",
    "InMemoryMemoryFactOperationReceiptRepository",
    "InMemoryMemoryFactRepository",
    "InMemoryMemoryFactUnitOfWork",
    "InMemoryMemoryFactUnitOfWorkFactory",
    "create_in_memory_memory_fact_store",
    "create_in_memory_memory_fact_unit_of_work_factory",
)
