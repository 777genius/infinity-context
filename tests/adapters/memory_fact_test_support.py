"""Shared deterministic fixtures for memory fact adapter tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from infinity_context_core.features.memory_facts.public import (
    MemoryFactIdentity,
    MemoryFactOutboxMessage,
    MemoryFactScope,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    MemoryFactVisibility,
)

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
EARLIER = datetime(2026, 1, 1, 2, 3, 4, tzinfo=UTC)
LATER = datetime(2026, 1, 3, 3, 4, 5, tzinfo=UTC)


def _scope(
    *,
    space_id: str = "space-1",
    memory_scope_id: str = "scope-1",
    thread_id: str | None = None,
) -> MemoryFactScope:
    return MemoryFactScope(
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
    )


def _source_ref(source_id: str) -> MemoryFactSourceRef:
    return MemoryFactSourceRef(source_type="document", source_id=source_id)


def _fact_snapshot(
    *,
    fact_id: str,
    scope: MemoryFactScope | None = None,
    version: int = 1,
) -> MemoryFactSnapshot:
    return MemoryFactSnapshot(
        identity=MemoryFactIdentity(fact_id=fact_id, scope=scope or _scope()),
        text="Ada owns the API runbook.",
        source_refs=(_source_ref("doc-1"),),
        visibility=MemoryFactVisibility(status="active", version=version),
        kind="ownership",
        category="operations",
        tags=("api",),
        created_at=EARLIER,
        updated_at=EARLIER,
    )


def _outbox_message(
    message_id: str,
    event_type: str,
    fact: MemoryFactSnapshot,
) -> MemoryFactOutboxMessage:
    return MemoryFactOutboxMessage(
        message_id=message_id,
        event_type=event_type,
        aggregate_id=fact.identity.fact_id,
        aggregate_version=fact.visibility.version,
        scope=fact.identity.scope,
        occurred_at=NOW,
    )


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeIds:
    def __init__(
        self,
        *,
        fact_ids: tuple[str, ...] = (),
        outbox_message_ids: tuple[str, ...] = (),
        tombstone_ids: tuple[str, ...] = (),
        temporal_decision_ids: tuple[str, ...] = (),
        fact_relation_ids: tuple[str, ...] = (),
    ) -> None:
        self._fact_ids = list(fact_ids)
        self._outbox_message_ids = list(outbox_message_ids)
        self._tombstone_ids = list(tombstone_ids)
        self._temporal_decision_ids = list(temporal_decision_ids)
        self._fact_relation_ids = list(fact_relation_ids)

    def new_fact_id(self) -> str:
        return self._fact_ids.pop(0)

    def new_outbox_message_id(self) -> str:
        return self._outbox_message_ids.pop(0)

    def new_tombstone_id(self) -> str:
        return self._tombstone_ids.pop(0)

    def new_temporal_decision_id(self) -> str:
        return self._temporal_decision_ids.pop(0)

    def new_fact_relation_id(self) -> str:
        return self._fact_relation_ids.pop(0)


class AsyncEntryGate:
    def __init__(self, *, parties: int) -> None:
        self._parties = parties
        self._arrived = 0
        self._event = asyncio.Event()

    async def wait(self) -> None:
        self._arrived += 1
        if self._arrived == self._parties:
            self._event.set()
        await self._event.wait()


class BarrierUnitOfWorkFactory:
    def __init__(self, factory, gate: AsyncEntryGate) -> None:
        self._factory = factory
        self._gate = gate

    def __call__(self):
        return BarrierUnitOfWork(self._factory(), self._gate)


class BarrierUnitOfWork:
    def __init__(self, inner, gate: AsyncEntryGate) -> None:
        self._inner = inner
        self._gate = gate

    async def __aenter__(self):
        await self._inner.__aenter__()
        self.facts = self._inner.facts
        self.outbox = self._inner.outbox
        self.supersessions = self._inner.supersessions
        self.temporal_decisions = self._inner.temporal_decisions
        self.operation_receipts = self._inner.operation_receipts
        await self._gate.wait()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._inner.__aexit__(exc_type, exc, tb)

    async def lock_scope(self, scope) -> None:
        await self._inner.lock_scope(scope)

    async def coordinate_source_refs(self, *, scope, source_refs) -> None:
        await self._inner.coordinate_source_refs(scope=scope, source_refs=source_refs)

    async def commit(self) -> None:
        await self._inner.commit()

    async def rollback(self) -> None:
        await self._inner.rollback()
