"""Import and placeholder checks for memory_facts adapter seams."""

from __future__ import annotations

import asyncio
import importlib
import sys
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from infinity_context_core.features.memory_facts.public import (
    FEATURE_ID,
    ForgetFactCommand,
    ForgetFactHandler,
    MemoryFactIdentity,
    MemoryFactOutboxMessage,
    MemoryFactScope,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    MemoryFactVisibility,
    RememberFactCommand,
    RememberFactHandler,
    UpdateFactCommand,
    UpdateFactHandler,
)
from infinity_context_core.ports.capabilities import CapabilityStatus

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
EARLIER = datetime(2026, 1, 1, 2, 3, 4, tzinfo=UTC)


def test_memory_facts_adapter_package_mirrors_feature_id() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")

    assert module.FEATURE_ID == FEATURE_ID == "memory_facts"
    assert module.InMemoryMemoryFactRepository.feature_id == FEATURE_ID
    assert module.InMemoryMemoryFactOutbox.feature_id == FEATURE_ID
    assert module.InMemoryMemoryFactUnitOfWork.feature_id == FEATURE_ID
    assert module.InMemoryMemoryFactUnitOfWorkFactory.feature_id == FEATURE_ID
    assert module.PostgresMemoryFactStore.feature_id == FEATURE_ID
    assert module.QdrantMemoryFactProjection.feature_id == FEATURE_ID
    assert module.GraphitiMemoryFactProjection.feature_id == FEATURE_ID


def test_memory_facts_adapter_imports_do_not_load_provider_sdks() -> None:
    for module_name in ("sqlalchemy", "qdrant_client", "graphiti", "openai", "fastapi"):
        sys.modules.pop(module_name, None)

    importlib.import_module("infinity_context_adapters.features.memory_facts")

    assert "sqlalchemy" not in sys.modules
    assert "qdrant_client" not in sys.modules
    assert "graphiti" not in sys.modules
    assert "openai" not in sys.modules
    assert "fastapi" not in sys.modules


def test_in_memory_fact_store_uses_full_identity_and_requires_existing_on_save() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    seed = _fact_snapshot(
        fact_id="fact-1",
        scope=_scope(thread_id="thread-1"),
    )
    store = module.create_in_memory_memory_fact_store((seed,))

    assert asyncio.run(store.get(seed.identity)) == seed
    assert asyncio.run(store.get_for_update(seed.identity)) == seed
    assert (
        asyncio.run(
            store.get(
                MemoryFactIdentity(
                    fact_id="fact-1",
                    scope=_scope(thread_id="thread-2"),
                )
            )
        )
        is None
    )

    with pytest.raises(ValueError, match="memory_fact_already_exists"):
        asyncio.run(store.create(seed))

    same_fact_id_in_other_scope = _fact_snapshot(
        fact_id="fact-1",
        scope=_scope(memory_scope_id="scope-2"),
    )
    created = _fact_snapshot(fact_id="fact-2")
    updated = replace(
        created,
        text="Ada owns the public API runbook.",
        visibility=replace(created.visibility, version=2),
    )

    assert asyncio.run(store.create(same_fact_id_in_other_scope)) == same_fact_id_in_other_scope
    assert asyncio.run(store.create(created)) == created
    assert asyncio.run(store.save(updated)) == updated

    with pytest.raises(KeyError, match="memory_fact_not_found"):
        asyncio.run(store.save(_fact_snapshot(fact_id="missing")))


def test_in_memory_fact_unit_of_work_factory_seeds_snapshots() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    seed = _fact_snapshot(fact_id="seed-fact")
    factory = module.create_in_memory_memory_fact_unit_of_work_factory((seed,))

    async def load_seed() -> MemoryFactSnapshot | None:
        async with factory() as uow:
            return await uow.facts.get(seed.identity)

    assert asyncio.run(load_seed()) == seed


def test_in_memory_fact_uow_drives_core_lifecycle_handlers() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    factory = module.create_in_memory_memory_fact_unit_of_work_factory()
    ids = FakeIds(
        fact_ids=("fact-1",),
        outbox_message_ids=("outbox-1", "outbox-2", "outbox-3"),
        tombstone_ids=("tombstone-1",),
    )
    clock = FakeClock(NOW)
    source_ref = _source_ref("doc-1")
    remember = RememberFactHandler(uow_factory=factory, clock=clock, ids=ids)

    remembered = asyncio.run(
        remember.execute(
            RememberFactCommand(
                scope=_scope(),
                text="Ada owns the API runbook.",
                source_refs=(source_ref,),
                kind="ownership",
                category="operations",
                tags=("api",),
            )
        )
    )
    updated = asyncio.run(
        UpdateFactHandler(uow_factory=factory, clock=clock, ids=ids).execute(
            UpdateFactCommand(
                identity=remembered.fact.identity,
                expected_version=1,
                text="Ada owns the public API runbook.",
                source_refs=(_source_ref("doc-2"),),
                kind="ownership",
                category="operations",
                tags=("api", "public"),
            )
        )
    )
    forgotten = asyncio.run(
        ForgetFactHandler(uow_factory=factory, clock=clock, ids=ids).execute(
            ForgetFactCommand(
                identity=remembered.fact.identity,
                expected_version=2,
            )
        )
    )

    async def load_current() -> MemoryFactSnapshot | None:
        async with factory() as uow:
            return await uow.facts.get(remembered.fact.identity)

    assert remembered.fact.visibility == MemoryFactVisibility(status="active", version=1)
    assert updated.fact.visibility == MemoryFactVisibility(status="active", version=2)
    assert forgotten.tombstone_id == "tombstone-1"
    assert forgotten.fact.visibility == MemoryFactVisibility(status="deleted", version=3)
    assert asyncio.run(load_current()) == forgotten.fact
    assert factory.outbox_messages == (
        _outbox_message("outbox-1", "fact.created", remembered.fact),
        _outbox_message("outbox-2", "fact.updated", updated.fact),
        _outbox_message("outbox-3", "fact.deleted", forgotten.fact),
    )


def test_in_memory_fact_uow_rolls_back_facts_and_outbox_messages_unless_committed() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    factory = module.create_in_memory_memory_fact_unit_of_work_factory()
    rolled_back = _fact_snapshot(fact_id="fact-rolled-back")
    not_committed = _fact_snapshot(fact_id="fact-not-committed")
    committed = _fact_snapshot(fact_id="fact-committed")
    rolled_back_message = _outbox_message("outbox-rolled-back", "fact.created", rolled_back)
    not_committed_message = _outbox_message("outbox-not-committed", "fact.created", not_committed)
    committed_message = _outbox_message("outbox-committed", "fact.created", committed)

    async def exercise() -> None:
        async with factory() as uow:
            await uow.facts.create(rolled_back)
            await uow.outbox.enqueue(rolled_back_message)
            await uow.rollback()

        async with factory() as uow:
            await uow.facts.create(not_committed)
            await uow.outbox.enqueue(not_committed_message)

        async with factory() as uow:
            assert await uow.facts.get(rolled_back.identity) is None
            assert await uow.facts.get(not_committed.identity) is None
            await uow.facts.create(committed)
            await uow.outbox.enqueue(committed_message)
            await uow.commit()

        async with factory() as uow:
            assert await uow.facts.get(rolled_back.identity) is None
            assert await uow.facts.get(not_committed.identity) is None
            assert await uow.facts.get(committed.identity) == committed

    asyncio.run(exercise())

    assert factory.outbox_messages == (committed_message,)


def test_postgres_fact_store_is_explicit_placeholder() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.postgres_fact_store"
    )
    identity = MemoryFactIdentity(
        fact_id="fact-1",
        scope=MemoryFactScope(space_id="space-1", memory_scope_id="scope-1"),
    )

    with pytest.raises(NotImplementedError, match="canonical persistence wiring is deferred"):
        asyncio.run(module.PostgresMemoryFactStore().get(identity))

    factory = module.create_postgres_memory_fact_unit_of_work_factory()
    assert factory.feature_id == FEATURE_ID
    assert factory().facts.feature_id == FEATURE_ID


def test_fact_projection_seams_report_disabled_health() -> None:
    qdrant = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.qdrant_fact_projection"
    ).QdrantMemoryFactProjection()
    graphiti = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.graphiti_fact_projection"
    ).GraphitiMemoryFactProjection()

    qdrant_health = asyncio.run(qdrant.health())
    graphiti_health = asyncio.run(graphiti.health())

    assert qdrant_health.status is CapabilityStatus.DISABLED
    assert graphiti_health.status is CapabilityStatus.DISABLED
    assert all(
        descriptor.metadata["feature_id"] == FEATURE_ID
        for descriptor in qdrant_health.capabilities
    )
    assert all(
        descriptor.metadata["feature_id"] == FEATURE_ID
        for descriptor in graphiti_health.capabilities
    )


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
