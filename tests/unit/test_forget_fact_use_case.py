from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from infinity_context_core.application.dto import ForgetFactCommand
from infinity_context_core.application.use_cases.forget_fact import ForgetFactUseCase
from infinity_context_core.domain.entities import (
    FactStatus,
    MemoryFact,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)
from infinity_context_core.domain.events import OutboxEvent

_NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


class _Facts:
    def __init__(self, current: MemoryFact) -> None:
        self.current = current
        self.get_for_update_calls: list[str] = []
        self.saved: list[MemoryFact] = []

    async def get_for_update(self, fact_id: str) -> MemoryFact:
        self.get_for_update_calls.append(fact_id)
        return self.current

    async def save(self, fact: MemoryFact) -> MemoryFact:
        self.saved.append(fact)
        return fact


class _Outbox:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []

    async def enqueue(self, event: OutboxEvent) -> None:
        self.events.append(event)


class _Uow:
    def __init__(self, current: MemoryFact) -> None:
        self.facts = _Facts(current)
        self.outbox = _Outbox()
        self.commit_calls = 0
        self.exit_calls = 0

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.exit_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1


class _UowFactory:
    def __init__(self, uow: _Uow) -> None:
        self._uow = uow
        self.calls = 0

    def __call__(self) -> _Uow:
        self.calls += 1
        return self._uow


class _Clock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return _NOW


def _active_fact() -> MemoryFact:
    return MemoryFact.create(
        fact_id=MemoryFactId("fact-1"),
        space_id=SpaceId("space-1"),
        memory_scope_id=MemoryScopeId("scope-1"),
        text="Canonical cleanup remains idempotent.",
        kind=MemoryKind.ARCHITECTURE_DECISION,
        source_refs=(SourceRef(source_type="manual", source_id="source-1"),),
        now=_NOW,
    )


def _execute(current: MemoryFact) -> tuple[object, _Uow, _UowFactory, _Clock]:
    uow = _Uow(current)
    factory = _UowFactory(uow)
    clock = _Clock()
    result = asyncio.run(
        ForgetFactUseCase(uow_factory=factory, clock=clock).execute(
            ForgetFactCommand(fact_id=str(current.id))
        )
    )
    return result, uow, factory, clock


@pytest.mark.parametrize("version", (1, 7))
def test_already_deleted_fact_is_noop_for_v1_and_higher_versions(version: int) -> None:
    current = replace(_active_fact(), status=FactStatus.DELETED, version=version)

    result, uow, factory, clock = _execute(current)

    assert result.fact is current
    assert result.indexing_status == "already_deleted"
    assert uow.facts.get_for_update_calls == [str(current.id)]
    assert uow.facts.saved == []
    assert uow.outbox.events == []
    assert uow.commit_calls == 1
    assert uow.exit_calls == 1
    assert factory.calls == 1
    assert clock.calls == 0


def test_active_fact_still_saves_enqueues_and_commits_once() -> None:
    current = _active_fact()

    result, uow, _, clock = _execute(current)

    assert result.fact.status == FactStatus.DELETED
    assert result.fact.version == current.version + 1
    assert result.indexing_status == "pending"
    assert uow.facts.saved == [result.fact]
    assert len(uow.outbox.events) == 1
    assert uow.outbox.events[0].event_type == "graph.delete_fact"
    assert uow.outbox.events[0].aggregate_id == str(current.id)
    assert uow.outbox.events[0].aggregate_version == result.fact.version
    assert uow.commit_calls == 1
    assert uow.exit_calls == 1
    assert clock.calls == 1
