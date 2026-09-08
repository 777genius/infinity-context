"""SQL adapter parity on SQLite; live PostgreSQL acceptance is a separate test."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactTransaction,
    PostgresMemoryFactUnitOfWorkFactory,
)
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_session_factory,
    create_schema,
)
from infinity_context_adapters.postgres.fact_repositories import (
    PostgresFactRelationRepository as LegacyRelationRepository,
)
from infinity_context_adapters.postgres.models import (
    MemoryFactRelationRow,
    MemoryFactRow,
    MemoryFactVersionRow,
    MemoryOutboxRow,
    MemorySourceRefRow,
)
from infinity_context_core.features.memory_facts.public import (
    FactCodeScopeReference,
    FactRelationType,
    LinkFactsCommand,
    LinkFactsHandler,
    ListFactRelationsHandler,
    ListFactRelationsQuery,
    MemoryFactSourceRef,
    UnlinkFactRelationCommand,
    UnlinkFactRelationHandler,
    link_facts_in_transaction,
)
from memory_fact_test_support import NOW, FakeClock, FakeIds, _fact_snapshot
from sqlalchemy import func, select


def test_existing_rows_session_rollback_hydration_and_legacy_order(tmp_path):
    async def run():
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'relations.db'}")
        try:
            await create_schema(engine)
            sessions = build_session_factory(engine)
            factory = PostgresMemoryFactUnitOfWorkFactory(
                session_factory=sessions, clock=FakeClock(NOW)
            )
            facts = tuple(
                replace(
                    _fact_snapshot(fact_id=name),
                    source_refs=(MemoryFactSourceRef("manual", name, char_start=1, char_end=5),),
                    code_scope=FactCodeScopeReference("repo", "branch")
                    if name == "project"
                    else None,
                )
                for name in ("source", "target", "project")
            )
            async with factory() as uow:
                for fact in facts:
                    await uow.facts.create(fact)
                await uow.commit()
            command = LinkFactsCommand(facts[0].identity, facts[1].identity, "supports", "evidence")
            handler = LinkFactsHandler(
                factory, FakeClock(NOW), FakeIds(fact_relation_ids=("a", "b", "c"))
            )
            first = await handler.execute(command)
            await handler.execute(replace(command, target_identity=facts[2].identity))
            await handler.execute(
                replace(
                    command, source_identity=facts[1].identity, target_identity=facts[0].identity
                )
            )
            replay = await handler.execute(replace(command, reason="different"))
            assert replay.relation.relation_id == first.relation.relation_id
            reader = ListFactRelationsHandler(factory)
            for repo, branch in [
                (None, None),
                ("repo", None),
                ("repo", "branch"),
                ("other", "branch"),
            ]:
                query = ListFactRelationsQuery(
                    facts[0].identity,
                    enforce_code_scope=True,
                    repository_id=repo,
                    code_scope_id=branch,
                )
                result = await reader.execute(query)
                async with sessions() as session:
                    legacy = await LegacyRelationRepository(session).list_for_fact(
                        fact_id="source",
                        status="active",
                        limit=50,
                        enforce_code_scope=True,
                        repository_id=repo,
                        code_scope_id=branch,
                    )
                assert [item.relation.relation_id for item in result.items] == [
                    str(item.id) for item in legacy
                ]
                assert all(item.related_fact.source_refs[0].char_end == 5 for item in result.items)
            # Joining the supplied session must roll back with unrelated canonical work.
            async with sessions() as session:
                transaction = PostgresMemoryFactTransaction(session, now=NOW)
                assert transaction.relations._session is session
                await link_facts_in_transaction(
                    transaction,
                    replace(command, relation_type="references"),
                    now=NOW,
                    ids=FakeIds(fact_relation_ids=("rollback",)),
                )
                await session.rollback()
            async with sessions() as session:
                assert await session.get(MemoryFactRelationRow, "rollback") is None
                assert await session.scalar(select(func.count()).select_from(MemoryFactRow)) == 3
                assert (
                    await session.scalar(select(func.count()).select_from(MemoryFactVersionRow))
                    == 3
                )
                assert (
                    await session.scalar(select(func.count()).select_from(MemorySourceRefRow)) == 3
                )
                assert await session.scalar(select(func.count()).select_from(MemoryOutboxRow)) == 0
                # Existing temporal rows are readable; unlink cannot overwrite their audit.
                row = await session.get(MemoryFactRelationRow, "a")
                row.relation_type = "supersedes"
                await session.commit()
            async with factory() as uow:
                relation = await uow.relations.get("a", scope=facts[0].identity.scope)
                assert relation.relation_type == FactRelationType.SUPERSEDES
            import pytest

            with pytest.raises(ValueError, match="immutable"):
                await UnlinkFactRelationHandler(factory, FakeClock(NOW)).execute(
                    UnlinkFactRelationCommand("a", facts[0].identity.scope)
                )
            await UnlinkFactRelationHandler(factory, FakeClock(NOW)).execute(
                UnlinkFactRelationCommand("b", facts[0].identity.scope)
            )
            async with sessions() as session:
                assert (await session.get(MemoryFactRelationRow, "b")).status == "deleted"
        finally:
            await engine.dispose()

    asyncio.run(run())
