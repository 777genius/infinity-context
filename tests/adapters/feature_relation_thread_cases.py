"""Shared actual SQL adapter checks, also run against coordinator PostgreSQL."""

from dataclasses import replace

import pytest
from infinity_context_adapters.postgres.models import Base, MemoryFactRelationRow, MemoryThreadRow
from infinity_context_core.features.memory_facts.public import (
    FactRelationConflict,
    LinkFactsCommand,
    LinkFactsHandler,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
)
from sqlalchemy import event, select, text


async def exercise_thread_cases(engine, sessions, factory, clock, ids):
    scope = MemoryFactScope("thread-case-space", "thread-case-scope")
    facts = tuple(
        MemoryFactSnapshot(
            identity=MemoryFactIdentity(name, replace(scope, thread_id=thread)),
            text=name,
            source_refs=(MemoryFactSourceRef("manual", name),),
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        for name, thread in (
            ("global-a", None),
            ("global-b", None),
            ("thread-a", "one"),
            ("thread-b", "one"),
            ("thread-c", "two"),
        )
    )
    async with sessions() as session:
        for thread_id in ("one", "two"):
            session.add(
                MemoryThreadRow(
                    id=thread_id,
                    space_id=scope.space_id,
                    memory_scope_id=scope.memory_scope_id,
                    external_ref=thread_id,
                    status="active",
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )
        await session.commit()
    async with factory() as uow:
        for fact in facts:
            await uow.facts.create(fact)
        await uow.commit()
    handler = LinkFactsHandler(factory, clock, ids)
    for source, target in ((facts[0], facts[1]), (facts[2], facts[3])):
        command = LinkFactsCommand(source.identity, target.identity, "supports", "evidence")
        result = await handler.execute(command)
        assert result.relation.thread_id == source.identity.scope.thread_id
        replay = await handler.execute(command)
        assert replay.relation.relation_id == result.relation.relation_id
        assert replay.relation.thread_id == result.relation.thread_id
        async with sessions() as session:
            row = await session.get(MemoryFactRelationRow, result.relation.relation_id)
            assert row.thread_id == source.identity.scope.thread_id
            assert row.thread_scope_key == (
                "global" if row.thread_id is None else "thread:" + row.thread_id
            )

    async def canonical_state():
        async with sessions() as session:
            return {
                table.name: tuple(
                    sorted(repr(tuple(row)) for row in (await session.execute(select(table))).all())
                )
                for table in Base.metadata.sorted_tables
            }

    before = await canonical_state()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        for source, target in (
            (facts[0], facts[2]),
            (facts[2], facts[0]),
            (facts[2], facts[4]),
            (facts[4], facts[2]),
        ):
            with pytest.raises(FactRelationConflict, match="cross thread boundaries"):
                await handler.execute(
                    LinkFactsCommand(source.identity, target.identity, "supports", "rejected")
                )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert not {"INSERT", "UPDATE", "DELETE"}.intersection(statements)
    assert await canonical_state() == before

    if engine.dialect.name == "sqlite":
        async with sessions() as session:
            assert (
                await session.execute(text("PRAGMA foreign_key_check(memory_fact_relations)"))
            ).all() == []
