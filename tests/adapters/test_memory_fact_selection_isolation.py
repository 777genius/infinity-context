from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from infinity_context_adapters.features.memory_facts.in_memory_fact_store import (
    create_in_memory_memory_fact_store,
)
from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactStore,
)
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_session_factory,
    create_schema,
)
from infinity_context_core.features.memory_facts.public import (
    FactTemporalExtent,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSelectionQuery,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    MemoryFactVisibility,
)

NOW = datetime(2026, 8, 5, tzinfo=UTC)


def test_in_memory_selection_does_not_leak_other_threads() -> None:
    store = create_in_memory_memory_fact_store(_facts())

    assert asyncio.run(store.find_eligible(_query(thread_id=None))) == (_facts()[0],)
    assert {
        fact.identity.fact_id
        for fact in asyncio.run(store.find_eligible(_query(thread_id="thread-a")))
    } == {"global", "thread-a"}


def test_selection_does_not_treat_transaction_update_time_as_freshness() -> None:
    template = _facts()[0]
    older_transaction = replace(
        template,
        identity=MemoryFactIdentity("a-fact", template.identity.scope),
    )
    newer_transaction = replace(
        template,
        identity=MemoryFactIdentity("z-fact", template.identity.scope),
        updated_at=NOW.replace(year=2027),
    )
    store = create_in_memory_memory_fact_store((newer_transaction, older_transaction))

    selected = asyncio.run(store.find_eligible(_query(thread_id=None)))

    assert tuple(fact.identity.fact_id for fact in selected) == ("a-fact", "z-fact")


def test_postgres_selection_does_not_leak_other_threads(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'thread-scope.db'}")
        try:
            await create_schema(engine)
            sessions = build_session_factory(engine)
            async with sessions() as session:
                store = PostgresMemoryFactStore(session)
                for fact in _facts():
                    await store.create(fact)
                await session.commit()
            async with sessions() as session:
                store = PostgresMemoryFactStore(session)
                global_ids = {
                    fact.identity.fact_id
                    for fact in await store.find_eligible(_query(thread_id=None))
                }
                thread_ids = {
                    fact.identity.fact_id
                    for fact in await store.find_eligible(_query(thread_id="thread-a"))
                }
            assert global_ids == {"global"}
            assert thread_ids == {"global", "thread-a"}
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_postgres_as_of_returns_superseded_fact_inside_old_validity(tmp_path: Path) -> None:
    valid_from = NOW - timedelta(days=30)
    valid_to = NOW - timedelta(days=10)
    superseded = replace(
        _fact("old-state", thread_id=None),
        visibility=MemoryFactVisibility(status="superseded", version=2),
        temporal_extent=FactTemporalExtent(
            kind="state",
            observed_at=valid_from,
            valid_from=valid_from,
            valid_to=valid_to,
        ),
    )

    async def exercise() -> tuple[MemoryFactSnapshot, ...]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'as-of.db'}")
        try:
            await create_schema(engine)
            sessions = build_session_factory(engine)
            async with sessions() as session:
                store = PostgresMemoryFactStore(session)
                await store.create(superseded)
                await session.commit()
            async with sessions() as session:
                return await PostgresMemoryFactStore(session).find_eligible(
                    MemoryFactSelectionQuery(
                        space_id="space-1",
                        memory_scope_ids=("scope-1",),
                        temporal_mode="as_of",
                        reference_time=valid_from + timedelta(days=1),
                        limit=10,
                    )
                )
        finally:
            await engine.dispose()

    assert asyncio.run(exercise()) == (superseded,)


def _facts() -> tuple[MemoryFactSnapshot, ...]:
    return tuple(
        _fact(fact_id, thread_id=thread_id)
        for fact_id, thread_id in (
            ("global", None),
            ("thread-a", "thread-a"),
            ("thread-b", "thread-b"),
        )
    )


def _fact(fact_id: str, *, thread_id: str | None) -> MemoryFactSnapshot:
    return MemoryFactSnapshot(
        identity=MemoryFactIdentity(
            fact_id=fact_id,
            scope=MemoryFactScope(
                space_id="space-1",
                memory_scope_id="scope-1",
                thread_id=thread_id,
            ),
        ),
        text=f"Fact {fact_id}",
        source_refs=(MemoryFactSourceRef("manual", f"source-{fact_id}"),),
        visibility=MemoryFactVisibility(),
        created_at=NOW,
        updated_at=NOW,
        temporal_extent=FactTemporalExtent.ongoing_state(observed_at=NOW),
    )


def _query(*, thread_id: str | None) -> MemoryFactSelectionQuery:
    return MemoryFactSelectionQuery(
        space_id="space-1",
        memory_scope_ids=("scope-1",),
        temporal_mode="current",
        reference_time=NOW,
        limit=10,
        thread_id=thread_id,
    )
