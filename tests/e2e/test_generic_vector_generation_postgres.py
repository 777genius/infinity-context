from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.noop import SystemClock
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryOutboxRow,
)
from infinity_context_adapters.postgres.repositories import PostgresChunkRepository
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_session_factory,
)
from infinity_context_core.application.dto import DeleteDocumentCommand
from infinity_context_core.application.use_cases.delete_document import DeleteDocumentUseCase
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import select

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def test_generic_chunk_generation_and_delete_event_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_generic_generation_lifecycle(database_url))


async def _assert_generic_generation_lifecycle(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="generic_vector_generation",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        async with sessions.begin() as session:
            session.add(_document())
        async with sessions.begin() as session:
            session.add(_chunk())

        # A canonical mutation advances the same generation used by generic
        # vector points even though the row has no retrieval locator.
        async with sessions.begin() as session:
            row = await session.get(MemoryChunkRow, "chunk-generic")
            assert row is not None
            row.text = "generic generation two"
            row.normalized_text = "generic generation two"
        async with sessions() as session:
            mapped = await PostgresChunkRepository(session).get_by_id("chunk-generic")
            assert mapped is not None
            assert mapped.canonical_version == 2
            assert "_canonical_retrieval_projection" not in mapped.metadata

        use_case = DeleteDocumentUseCase(
            uow_factory=PostgresUnitOfWorkFactory(
                session_factory=sessions,
                clock=SystemClock(),
            ),
            clock=SystemClock(),
        )
        result = await use_case.execute(DeleteDocumentCommand(document_id="document-generic"))
        assert result.deleted_chunks == 1

        async with sessions() as session:
            row = await session.get(MemoryChunkRow, "chunk-generic")
            assert row is not None
            assert row.status == "deleted"
            assert row.retrieval_version == 3
            delete_event = (
                await session.execute(
                    select(MemoryOutboxRow).where(
                        MemoryOutboxRow.event_type == "vector.delete_chunks"
                    )
                )
            ).scalar_one()
            assert delete_event.payload_json["chunk_versions"] == [
                {"chunk_id": "chunk-generic", "canonical_version": 2}
            ]
            visible = await PostgresChunkRepository(session).hydrate_visible_chunks(
                chunk_ids=("chunk-generic",),
                space_id="space",
                memory_scope_ids=("scope",),
                thread_id=None,
            )
            assert visible == []
    finally:
        await engine.dispose()
        await database.drop()


def _document() -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id="document-generic",
        space_id="space",
        memory_scope_id="scope",
        thread_id=None,
        title="Generic generation",
        source_type="document",
        source_external_id="generic-source",
        content_hash="generic-document-hash",
        classification="internal",
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )


def _chunk() -> MemoryChunkRow:
    return MemoryChunkRow(
        id="chunk-generic",
        space_id="space",
        memory_scope_id="scope",
        thread_id=None,
        document_id="document-generic",
        episode_id=None,
        source_type="document",
        source_external_id="generic-source",
        source_hash="generic-chunk-hash",
        kind="document_section",
        text="generic generation one",
        normalized_text="generic generation one",
        status="active",
        sequence=0,
        char_start=0,
        char_end=22,
        token_estimate=4,
        classification="internal",
        created_at=NOW,
        updated_at=NOW,
        metadata_json={},
        retrieval_locator=None,
        retrieval_source_key=None,
        retrieval_projection_generation=None,
        retrieval_sequence_ordinal=None,
        retrieval_kind=None,
        retrieval_actor_keys_json=[],
        retrieval_category=None,
        retrieval_tags_json=[],
    )
