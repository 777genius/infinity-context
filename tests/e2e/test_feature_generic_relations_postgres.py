"""Disposable PostgreSQL acceptance for the generic feature relation transaction.

Pending execution until the coordinator supplies an explicitly test-only database.
SQLite adapter tests do not establish these lock/index/rollback guarantees.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

import pytest
from infinity_context_adapters.features.memory_facts.id_generator import MemoryFactIdAdapter
from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactUnitOfWorkFactory,
)
from infinity_context_adapters.noop import SystemClock
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_session_factory,
    upgrade_schema,
)
from infinity_context_adapters.postgres.models import (
    MemoryFactRelationRow,
    MemoryFactRow,
    MemoryFactVersionRow,
    MemoryOutboxRow,
    MemorySourceRefRow,
)
from infinity_context_core.features.memory_facts.public import (
    FactRelationConflict,
    LinkFactsCommand,
    LinkFactsHandler,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    UnlinkFactRelationCommand,
    UnlinkFactRelationHandler,
    link_facts_in_transaction,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from tests.adapters.feature_relation_thread_cases import exercise_thread_cases

NOW = datetime(2026, 9, 8, tzinfo=UTC)


def test_postgres_generic_relation_contention_uniqueness_and_atomicity():
    url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Coordinator must supply INFINITY_CONTEXT_TEST_POSTGRES_URL (test-only)")
    asyncio.run(_exercise(url))


async def _exercise(url):
    database = PostgresTestDatabase.from_url(
        url, prefix="generic_relations", asyncpg=pytest.importorskip("asyncpg")
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    pending = None
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        factory = PostgresMemoryFactUnitOfWorkFactory(session_factory=sessions, clock=SystemClock())
        scope = MemoryFactScope("relation-space", "relation-scope")
        facts = tuple(
            MemoryFactSnapshot(
                identity=MemoryFactIdentity(name, scope),
                text=f"Evidence {name}",
                source_refs=(MemoryFactSourceRef("manual", name),),
                created_at=NOW,
                updated_at=NOW,
            )
            for name in ("source", "target")
        )
        async with factory() as uow:
            for fact in facts:
                await uow.facts.create(fact)
            await uow.commit()
        ids = MemoryFactIdAdapter(lambda prefix: f"{prefix}-{uuid4().hex}")
        command = LinkFactsCommand(facts[0].identity, facts[1].identity, "supports", "evidence")
        async with factory() as first, factory() as second:
            winner = await link_facts_in_transaction(first, command, now=NOW, ids=ids)
            second_pid = await second._session.scalar(text("SELECT pg_backend_pid()"))
            pending = asyncio.create_task(
                link_facts_in_transaction(second, command, now=NOW, ids=ids)
            )
            deadline = monotonic() + 5
            async with sessions() as observer:
                while monotonic() < deadline:
                    blocked = await observer.scalar(
                        text(
                            "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": second_pid},
                    )
                    if blocked:
                        break
                    assert not pending.done(), "second writer escaped the canonical lock"
                    await asyncio.sleep(0.02)
                    await observer.rollback()
                else:
                    pytest.fail("second writer did not demonstrate PostgreSQL lock contention")
            await first.commit()
            replay = await asyncio.wait_for(pending, timeout=5)
            pending = None
            await second.commit()
            assert winner == replay
        handler = LinkFactsHandler(factory, SystemClock(), ids)
        with pytest.raises(FactRelationConflict, match="observed_at"):
            await handler.execute(
                LinkFactsCommand(
                    facts[0].identity,
                    facts[1].identity,
                    "supports",
                    "evidence",
                    observed_at=NOW + timedelta(days=1),
                )
            )
        # The existing partial index also rejects a writer bypassing feature locks.
        async with sessions() as session:
            existing = await session.get(MemoryFactRelationRow, winner.relation.relation_id)
            session.add(
                MemoryFactRelationRow(
                    id="bypass-duplicate",
                    space_id=scope.space_id,
                    memory_scope_id=scope.memory_scope_id,
                    source_fact_id="source",
                    target_fact_id="target",
                    relation_type="supports",
                    reason="bypass",
                    status="active",
                    observed_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            assert existing is not None
            with pytest.raises(IntegrityError) as error:
                await session.flush()
            assert "uq_memory_fact_relation_active" in str(error.value)
            await session.rollback()
        # Caller-owned transaction failure leaves no relation, revision or outbox write.
        with pytest.raises(RuntimeError, match="injected"):
            async with factory() as uow:
                await link_facts_in_transaction(
                    uow,
                    LinkFactsCommand(
                        facts[0].identity, facts[1].identity, "references", "rollback"
                    ),
                    now=NOW,
                    ids=ids,
                )
                unrelated = await uow._session.get(MemoryFactRow, "source")
                unrelated.text = "uncommitted canonical change"
                await uow._session.flush()
                raise RuntimeError("injected failure before commit")
        async with sessions() as session:
            assert (await session.get(MemoryFactRow, "source")).text == facts[0].text
            assert (
                await session.scalar(select(func.count()).select_from(MemoryFactRelationRow)) == 1
            )
            assert await session.scalar(select(func.count()).select_from(MemoryFactVersionRow)) == 2
            assert await session.scalar(select(func.count()).select_from(MemorySourceRefRow)) == 2
            assert await session.scalar(select(func.count()).select_from(MemoryOutboxRow)) == 0
        unlink = UnlinkFactRelationHandler(factory, SystemClock())
        deleted = await unlink.execute(
            UnlinkFactRelationCommand(winner.relation.relation_id, scope)
        )
        assert (
            await unlink.execute(UnlinkFactRelationCommand(winner.relation.relation_id, scope))
            == deleted
        )
        relinked = await handler.execute(command)
        assert relinked.relation.relation_id != winner.relation.relation_id
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryFactRelationRow)
                    .where(MemoryFactRelationRow.status == "active")
                )
                == 1
            )
        await exercise_thread_cases(engine, sessions, factory, SystemClock(), ids)
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await engine.dispose()
        await database.drop()
