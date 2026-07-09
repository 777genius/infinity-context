"""In-memory repository, outbox and unit-of-work seam for memory_facts adapters."""

from __future__ import annotations

from collections.abc import Iterable
from types import TracebackType
from typing import ClassVar

from infinity_context_core.features.memory_facts.public import (
    FEATURE_ID,
    MemoryFactIdentity,
    MemoryFactOutboxMessage,
    MemoryFactRepositoryPort,
    MemoryFactSnapshot,
    MemoryFactUnitOfWorkFactoryPort,
)

_FactKey = tuple[str, str, str | None, str]


class _InMemoryMemoryFactState:
    def __init__(self, facts: Iterable[MemoryFactSnapshot] = ()) -> None:
        self._facts: dict[_FactKey, MemoryFactSnapshot] = {}
        self._outbox_messages: list[MemoryFactOutboxMessage] = []
        for fact in facts:
            self._put(fact, allow_existing=False)

    def snapshot(
        self,
    ) -> tuple[dict[_FactKey, MemoryFactSnapshot], list[MemoryFactOutboxMessage]]:
        return dict(self._facts), list(self._outbox_messages)

    def replace(
        self,
        facts: dict[_FactKey, MemoryFactSnapshot],
        outbox_messages: list[MemoryFactOutboxMessage],
    ) -> None:
        self._facts = dict(facts)
        self._outbox_messages = list(outbox_messages)

    def facts(self) -> tuple[MemoryFactSnapshot, ...]:
        return tuple(self._facts.values())

    def outbox_messages(self) -> tuple[MemoryFactOutboxMessage, ...]:
        return tuple(self._outbox_messages)

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

    async def create(self, fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        key = _fact_key(fact.identity)
        if key in self._facts:
            raise ValueError("memory_fact_already_exists")
        self._facts[key] = fact
        return fact

    async def get(self, identity: MemoryFactIdentity) -> MemoryFactSnapshot | None:
        return self._facts.get(_fact_key(identity))

    async def get_for_update(
        self,
        identity: MemoryFactIdentity,
    ) -> MemoryFactSnapshot | None:
        return await self.get(identity)

    async def save(self, fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        key = _fact_key(fact.identity)
        if key not in self._facts:
            raise KeyError("memory_fact_not_found")
        self._facts[key] = fact
        return fact


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


class InMemoryMemoryFactUnitOfWork:
    """Transactional unit-of-work seam backed by in-memory snapshots."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, state: _InMemoryMemoryFactState | None = None) -> None:
        self._state = state or _InMemoryMemoryFactState()
        self._working_facts, self._working_outbox_messages = self._state.snapshot()
        self.facts = InMemoryMemoryFactRepository(self._working_facts)
        self.outbox = InMemoryMemoryFactOutbox(self._working_outbox_messages)
        self._committed = False

    async def __aenter__(self) -> InMemoryMemoryFactUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        if exc_type is not None or not self._committed:
            await self.rollback()

    async def commit(self) -> None:
        self._state.replace(self._working_facts, self._working_outbox_messages)
        self._committed = True

    async def rollback(self) -> None:
        self._working_facts, self._working_outbox_messages = self._state.snapshot()
        self.facts = InMemoryMemoryFactRepository(self._working_facts)
        self.outbox = InMemoryMemoryFactOutbox(self._working_outbox_messages)
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

    def __call__(self) -> InMemoryMemoryFactUnitOfWork:
        return InMemoryMemoryFactUnitOfWork(self._state)


def create_in_memory_memory_fact_store(
    facts: Iterable[MemoryFactSnapshot] = (),
) -> MemoryFactRepositoryPort:
    """Create a standalone in-memory memory fact repository."""

    working_facts, _messages = _InMemoryMemoryFactState(facts).snapshot()
    return InMemoryMemoryFactRepository(working_facts)


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
    "InMemoryMemoryFactOutbox",
    "InMemoryMemoryFactRepository",
    "InMemoryMemoryFactUnitOfWork",
    "InMemoryMemoryFactUnitOfWorkFactory",
    "create_in_memory_memory_fact_store",
    "create_in_memory_memory_fact_unit_of_work_factory",
)
