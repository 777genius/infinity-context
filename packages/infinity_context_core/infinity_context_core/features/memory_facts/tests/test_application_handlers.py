"""Fake-backed tests for memory_facts lifecycle handlers."""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from types import TracebackType

import pytest

APPLICATION = importlib.import_module("infinity_context_core.features.memory_facts.application")
DOMAIN = importlib.import_module("infinity_context_core.features.memory_facts.domain")
PORTS = importlib.import_module("infinity_context_core.features.memory_facts.ports")

ForgetFactCommand = APPLICATION.ForgetFactCommand
ForgetFactHandler = APPLICATION.ForgetFactHandler
ForgetFactResult = APPLICATION.ForgetFactResult
MemoryFactIdentity = DOMAIN.MemoryFactIdentity
MemoryFactOutboxMessage = PORTS.MemoryFactOutboxMessage
MemoryFactScope = DOMAIN.MemoryFactScope
MemoryFactSnapshot = DOMAIN.MemoryFactSnapshot
MemoryFactSourceRef = DOMAIN.MemoryFactSourceRef
MemoryFactVisibility = DOMAIN.MemoryFactVisibility
RememberFactCommand = APPLICATION.RememberFactCommand
RememberFactHandler = APPLICATION.RememberFactHandler
RememberFactResult = APPLICATION.RememberFactResult
UpdateFactCommand = APPLICATION.UpdateFactCommand
UpdateFactHandler = APPLICATION.UpdateFactHandler
UpdateFactResult = APPLICATION.UpdateFactResult


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
EARLIER = datetime(2026, 1, 1, 2, 3, 4, tzinfo=UTC)


def test_remember_fact_handler_creates_fact_and_outbox_message() -> None:
    uow = FakeUnitOfWork()
    handler = RememberFactHandler(
        uow_factory=FakeUnitOfWorkFactory(uow),
        clock=FakeClock(NOW),
        ids=FakeIds(
            fact_ids=("fact-1",),
            outbox_message_ids=("outbox-1",),
        ),
    )
    source_ref = _source_ref("doc-1")
    command = RememberFactCommand(
        scope=_scope(),
        text="Ada owns the API runbook.",
        source_refs=(source_ref,),
        kind="ownership",
        category="operations",
        tags=("api", "runbook"),
    )

    result = asyncio.run(handler.execute(command))

    assert isinstance(result, RememberFactResult)
    assert result.outbox_message_ids == ("outbox-1",)
    assert result.fact == MemoryFactSnapshot(
        identity=MemoryFactIdentity(fact_id="fact-1", scope=command.scope),
        text=command.text,
        source_refs=(source_ref,),
        visibility=MemoryFactVisibility(status="active", version=1),
        kind="ownership",
        category="operations",
        tags=("api", "runbook"),
        created_at=NOW,
        updated_at=NOW,
    )
    assert uow.facts.calls == [("create", result.fact)]
    assert uow.outbox.messages == [
        MemoryFactOutboxMessage(
            message_id="outbox-1",
            event_type="fact.created",
            aggregate_id="fact-1",
            aggregate_version=1,
            occurred_at=NOW,
        )
    ]
    assert uow.events == ["enter", "commit", "exit:ok"]


def test_update_fact_handler_locks_updates_and_enqueues_projection_event() -> None:
    current = _fact_snapshot(version=3)
    uow = FakeUnitOfWork(current=current)
    handler = UpdateFactHandler(
        uow_factory=FakeUnitOfWorkFactory(uow),
        clock=FakeClock(NOW),
        ids=FakeIds(outbox_message_ids=("outbox-2",)),
    )
    source_ref = _source_ref("doc-2")
    command = UpdateFactCommand(
        identity=current.identity,
        expected_version=3,
        text="Ada owns the public API runbook.",
        source_refs=(source_ref,),
        kind="ownership",
        category="operations",
        tags=("api", "public"),
        reason="correction",
    )

    result = asyncio.run(handler.execute(command))

    assert isinstance(result, UpdateFactResult)
    assert result.outbox_message_ids == ("outbox-2",)
    assert result.fact == MemoryFactSnapshot(
        identity=current.identity,
        text=command.text,
        source_refs=(source_ref,),
        visibility=MemoryFactVisibility(status="active", version=4),
        kind="ownership",
        category="operations",
        tags=("api", "public"),
        created_at=EARLIER,
        updated_at=NOW,
    )
    assert uow.facts.calls == [
        ("get_for_update", current.identity),
        ("save", result.fact),
    ]
    assert uow.outbox.messages == [
        MemoryFactOutboxMessage(
            message_id="outbox-2",
            event_type="fact.updated",
            aggregate_id="fact-1",
            aggregate_version=4,
            occurred_at=NOW,
        )
    ]
    assert uow.events == ["enter", "commit", "exit:ok"]


def test_forget_fact_handler_tombstones_fact_and_returns_tombstone_id() -> None:
    current = _fact_snapshot(version=2)
    uow = FakeUnitOfWork(current=current)
    handler = ForgetFactHandler(
        uow_factory=FakeUnitOfWorkFactory(uow),
        clock=FakeClock(NOW),
        ids=FakeIds(
            tombstone_ids=("tombstone-1",),
            outbox_message_ids=("outbox-3",),
        ),
    )
    command = ForgetFactCommand(
        identity=current.identity,
        expected_version=2,
        reason="obsolete",
    )

    result = asyncio.run(handler.execute(command))

    assert isinstance(result, ForgetFactResult)
    assert result.tombstone_id == "tombstone-1"
    assert result.outbox_message_ids == ("outbox-3",)
    assert result.fact == MemoryFactSnapshot(
        identity=current.identity,
        text=current.text,
        source_refs=current.source_refs,
        visibility=MemoryFactVisibility(status="deleted", version=3),
        kind=current.kind,
        evidence_refs=current.evidence_refs,
        category=current.category,
        tags=current.tags,
        created_at=EARLIER,
        updated_at=NOW,
    )
    assert uow.facts.calls == [
        ("get_for_update", current.identity),
        ("save", result.fact),
    ]
    assert uow.outbox.messages == [
        MemoryFactOutboxMessage(
            message_id="outbox-3",
            event_type="fact.deleted",
            aggregate_id="fact-1",
            aggregate_version=3,
            occurred_at=NOW,
        )
    ]
    assert uow.events == ["enter", "commit", "exit:ok"]


def test_update_fact_handler_rejects_stale_expected_version_before_save() -> None:
    current = _fact_snapshot(version=2)
    uow = FakeUnitOfWork(current=current)
    handler = UpdateFactHandler(
        uow_factory=FakeUnitOfWorkFactory(uow),
        clock=FakeClock(NOW),
        ids=FakeIds(outbox_message_ids=("outbox-unused",)),
    )
    command = UpdateFactCommand(
        identity=current.identity,
        expected_version=1,
        text="Ada owns the API runbook.",
        source_refs=(_source_ref("doc-2"),),
    )

    with pytest.raises(ValueError, match="expected 1, actual 2"):
        asyncio.run(handler.execute(command))

    assert uow.facts.calls == [("get_for_update", current.identity)]
    assert uow.outbox.messages == []
    assert uow.events == ["enter", "rollback", "exit:error"]


def _scope() -> MemoryFactScope:
    return MemoryFactScope(space_id="space-1", memory_scope_id="scope-1")


def _source_ref(source_id: str) -> MemoryFactSourceRef:
    return MemoryFactSourceRef(source_type="document", source_id=source_id)


def _fact_snapshot(*, version: int) -> MemoryFactSnapshot:
    return MemoryFactSnapshot(
        identity=MemoryFactIdentity(fact_id="fact-1", scope=_scope()),
        text="Ada owns the API runbook.",
        source_refs=(_source_ref("doc-1"),),
        visibility=MemoryFactVisibility(status="active", version=version),
        kind="ownership",
        category="operations",
        tags=("api",),
        created_at=EARLIER,
        updated_at=EARLIER,
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
    ) -> None:
        self._fact_ids = list(fact_ids)
        self._outbox_message_ids = list(outbox_message_ids)
        self._tombstone_ids = list(tombstone_ids)

    def new_fact_id(self) -> str:
        return self._fact_ids.pop(0)

    def new_outbox_message_id(self) -> str:
        return self._outbox_message_ids.pop(0)

    def new_tombstone_id(self) -> str:
        return self._tombstone_ids.pop(0)


class FakeRepository:
    def __init__(self, current: MemoryFactSnapshot | None = None) -> None:
        self.current = current
        self.calls: list[tuple[str, object]] = []

    async def create(self, fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        self.calls.append(("create", fact))
        self.current = fact
        return fact

    async def get(self, identity: MemoryFactIdentity) -> MemoryFactSnapshot | None:
        self.calls.append(("get", identity))
        return self.current

    async def get_for_update(
        self,
        identity: MemoryFactIdentity,
    ) -> MemoryFactSnapshot | None:
        self.calls.append(("get_for_update", identity))
        return self.current

    async def save(self, fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        self.calls.append(("save", fact))
        self.current = fact
        return fact


class FakeOutbox:
    def __init__(self) -> None:
        self.messages: list[MemoryFactOutboxMessage] = []

    async def enqueue(self, message: MemoryFactOutboxMessage) -> None:
        self.messages.append(message)


class FakeUnitOfWork:
    def __init__(self, current: MemoryFactSnapshot | None = None) -> None:
        self.facts = FakeRepository(current)
        self.outbox = FakeOutbox()
        self.events: list[str] = []

    async def __aenter__(self) -> FakeUnitOfWork:
        self.events.append("enter")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
            self.events.append("exit:error")
            return
        self.events.append("exit:ok")

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


class FakeUnitOfWorkFactory:
    def __init__(self, uow: FakeUnitOfWork) -> None:
        self.uow = uow
        self.calls = 0

    def __call__(self) -> FakeUnitOfWork:
        self.calls += 1
        return self.uow
