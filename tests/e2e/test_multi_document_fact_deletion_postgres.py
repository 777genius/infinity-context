"""Live PostgreSQL proofs for facts backed by a document union."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.noop import SystemClock
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.fact_repositories import PostgresFactRepository
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryFactRow,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_session_factory,
)
from infinity_context_core.application.dto import DeleteDocumentCommand
from infinity_context_core.application.use_cases.delete_document import DeleteDocumentUseCase
from infinity_context_core.domain.entities import (
    MemoryFact,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import select, text

NOW = datetime(2026, 9, 2, tzinfo=UTC)


@pytest.mark.parametrize("concurrent", (False, True))
def test_document_union_deletion_cannot_leave_active_orphan(concurrent: bool) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_union_deletion(database_url, concurrent=concurrent))


async def _assert_union_deletion(database_url: str, *, concurrent: bool) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix=f"document_union_{'concurrent' if concurrent else 'sequential'}",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        async with sessions.begin() as session:
            session.add_all(
                (
                    _document("document-a"),
                    _document("document-b"),
                )
            )
            await session.flush()
            session.add_all(
                (
                    _chunk("chunk-a", "document-a"),
                    _chunk("chunk-b", "document-b"),
                )
            )
        fact = MemoryFact.create(
            fact_id=MemoryFactId("fact-union"),
            space_id=SpaceId("space-union"),
            memory_scope_id=MemoryScopeId("scope-union"),
            thread_id=None,
            text="Both documents support this fact.",
            kind=MemoryKind.NOTE,
            source_refs=(
                SourceRef("document", "document-a", chunk_id="chunk-a"),
                SourceRef("document", "document-b", chunk_id="chunk-b"),
            ),
            now=NOW,
        )
        async with sessions.begin() as session:
            await PostgresFactRepository(session, now=NOW).create(fact)

        factory = PostgresUnitOfWorkFactory(session_factory=sessions, clock=SystemClock())

        async def delete(document_id: str):
            return await DeleteDocumentUseCase(
                uow_factory=factory,
                clock=SystemClock(),
            ).execute(DeleteDocumentCommand(document_id=document_id))

        if concurrent:
            results = await asyncio.wait_for(
                asyncio.gather(delete("document-b"), delete("document-a")),
                timeout=8,
            )
        else:
            first = await delete("document-a")
            async with sessions() as session:
                retained = await session.get(MemoryFactRow, "fact-union")
                assert retained is not None and retained.status == "active"
            results = (first, await delete("document-b"))
        assert sum(result.deleted_facts for result in results) == 1

        async with sessions() as session:
            current = await session.get(MemoryFactRow, "fact-union")
            dangling = await session.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM memory_facts fact
                    JOIN memory_source_refs ref
                      ON ref.fact_id = fact.id AND ref.fact_version = fact.version
                    LEFT JOIN memory_chunks chunk ON chunk.id = ref.chunk_id
                    LEFT JOIN memory_documents document ON document.id = chunk.document_id
                    WHERE fact.status = 'active'
                      AND (chunk.status <> 'active' OR document.status <> 'active')
                    """
                )
            )
            statuses = tuple(
                (
                    await session.execute(
                        select(MemoryDocumentRow.status).order_by(MemoryDocumentRow.id)
                    )
                ).scalars()
            )
        assert current is not None and (current.status, current.version) == ("deleted", 2)
        assert statuses == ("deleted", "deleted")
        assert dangling == 0
    finally:
        await engine.dispose()
        await database.drop()


def _document(document_id: str) -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id=document_id,
        space_id="space-union",
        memory_scope_id="scope-union",
        thread_id=None,
        title=document_id,
        source_type="document",
        source_external_id=document_id,
        content_hash=f"hash-{document_id}",
        classification="internal",
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )


def _chunk(chunk_id: str, document_id: str) -> MemoryChunkRow:
    return MemoryChunkRow(
        id=chunk_id,
        space_id="space-union",
        memory_scope_id="scope-union",
        thread_id=None,
        document_id=document_id,
        episode_id=None,
        source_type="document",
        source_external_id=document_id,
        source_hash=f"hash-{chunk_id}",
        kind="document_section",
        text=chunk_id,
        normalized_text=chunk_id,
        status="active",
        sequence=0,
        char_start=0,
        char_end=len(chunk_id),
        token_estimate=1,
        classification="internal",
        created_at=NOW,
        updated_at=NOW,
        metadata_json={},
    )
