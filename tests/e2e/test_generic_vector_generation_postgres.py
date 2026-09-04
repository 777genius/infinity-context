from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from infinity_context_adapters.noop import SystemClock
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryOutboxRow,
    MemoryVectorRebuildOperationRow,
)
from infinity_context_adapters.postgres.repositories import (
    PostgresChunkRepository,
    PostgresDocumentRepository,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_session_factory,
)
from infinity_context_core.application.dto import DeleteDocumentCommand
from infinity_context_core.application.use_cases.delete_document import DeleteDocumentUseCase
from infinity_context_server.processes.outbox import ClaimedOutboxJob
from infinity_context_server.processes.vector_rebuild import (
    GenericVectorRebuildProcess,
    _RebuildPage,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def test_generic_chunk_generation_and_delete_event_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_generic_generation_lifecycle(database_url))


def test_document_delete_locks_exact_chunks_in_order_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_document_delete_row_locks(database_url))


def test_generic_rebuild_uses_commit_watermark_snapshot_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_rebuild_commit_watermark_snapshot(database_url))


def test_rebuild_processed_commit_reconciliation_when_postgres_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_rebuild_processed_commit_reconciliation(database_url, monkeypatch))


async def _assert_document_delete_row_locks(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="generic_document_delete_locks",
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
            session.add_all((_chunk("chunk-z", 1), _chunk("chunk-a", 0)))

        owner = sessions()
        contender = sessions()
        await owner.begin()
        try:
            deleted = await PostgresDocumentRepository(owner).soft_delete_with_chunks(
                document_id="document-generic",
                now=NOW,
            )
            assert deleted is not None
            assert tuple(item.chunk_id for item in deleted[1]) == ("chunk-a", "chunk-z")
            assert tuple(item.canonical_version for item in deleted[1]) == (1, 1)

            await contender.begin()
            await contender.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError):
                await contender.execute(
                    select(MemoryChunkRow).where(MemoryChunkRow.id == "chunk-a").with_for_update()
                )
            await contender.rollback()
        finally:
            await owner.rollback()
            await owner.close()
            await contender.close()
    finally:
        await engine.dispose()
        await database.drop()


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
            assert delete_event.payload_json["space_id"] == "space"
            assert delete_event.payload_json["memory_scope_id"] == "scope"
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


async def _assert_rebuild_commit_watermark_snapshot(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="generic_rebuild_wm",
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
            session.add(_chunk("chunk-a"))
        async with sessions() as session:
            first = await session.get(MemoryChunkRow, "chunk-a")
            assert first is not None and first.retrieval_commit_watermark > 0
            watermark = first.retrieval_commit_watermark

        # Both ids sort on opposite sides of the initial row. Their later
        # canonical watermarks, rather than random id order, exclude them.
        async with sessions.begin() as session:
            session.add_all((_chunk("chunk-0", 1), _chunk("chunk-z", 2)))
        async with sessions.begin() as session:
            session.add(
                MemoryVectorRebuildOperationRow(
                    operation_id="watermark-operation",
                    space_id="space",
                    memory_scope_id="scope",
                    status="running",
                    canonical_watermark=watermark,
                    dead_event_watermark=0,
                    cursor_watermark=0,
                    cursor_chunk_id=None,
                    processed_count=0,
                    failed_count=0,
                    batch_size=10,
                    created_at=NOW,
                    updated_at=NOW,
                    completed_at=None,
                )
            )
        page = _RebuildPage.from_job(
            ClaimedOutboxJob(
                id=1,
                event_type="vector.rebuild_scope_page",
                aggregate_type="vector_rebuild",
                aggregate_id="watermark-operation",
                aggregate_version=None,
                attempt_count=0,
                workload_class="projection",
                fairness_key="vector-rebuild:watermark-operation",
                payload_json={
                    "operation_id": "watermark-operation",
                    "space_id": "space",
                    "memory_scope_id": "scope",
                    "canonical_watermark": watermark,
                    "dead_event_watermark": 0,
                    "batch_size": 10,
                },
            )
        )
        process = GenericVectorRebuildProcess(SimpleNamespace(engine=engine))
        operation = await process._load_operation(page)
        rows = await process._load_page(page, operation)
        assert [row.id for row in rows] == ["chunk-a"]
        assert all(row.retrieval_commit_watermark <= watermark for row in rows)
    finally:
        await engine.dispose()
        await database.drop()


async def _assert_rebuild_processed_commit_reconciliation(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="generic_rebuild_commit",
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
            session.add(_chunk("chunk-reconcile"))
        async with sessions() as session:
            chunk = await session.get(MemoryChunkRow, "chunk-reconcile")
            assert chunk is not None
            session.expunge(chunk)

        watermark = int(chunk.retrieval_commit_watermark)
        process = GenericVectorRebuildProcess(SimpleNamespace(engine=engine, clock=SystemClock()))
        original_commit = AsyncSession.commit

        definite_page = _rebuild_page("definite-operation", watermark)
        async with sessions.begin() as session:
            session.add(_rebuild_operation("definite-operation", watermark))

        definite_calls = 0

        async def fail_first_commit(session: AsyncSession) -> None:
            nonlocal definite_calls
            definite_calls += 1
            if definite_calls == 1:
                raise RuntimeError("definite processed cursor failure")
            await original_commit(session)

        with monkeypatch.context() as patch:
            patch.setattr(AsyncSession, "commit", fail_first_commit)
            with pytest.raises(RuntimeError, match="definite processed cursor failure"):
                await process._record_processed(definite_page, chunk)

        async with sessions() as session:
            operation = await session.get(
                MemoryVectorRebuildOperationRow,
                "definite-operation",
            )
            assert operation is not None
            assert operation.cursor_watermark == 0
            assert operation.cursor_chunk_id is None
            assert operation.processed_count == 0
            assert operation.failed_count == 1

        await process._record_processed(definite_page, chunk)
        await process._record_processed(definite_page, chunk)
        async with sessions() as session:
            operation = await session.get(
                MemoryVectorRebuildOperationRow,
                "definite-operation",
            )
            assert operation is not None
            assert (operation.cursor_watermark, operation.cursor_chunk_id) == (
                watermark,
                "chunk-reconcile",
            )
            assert operation.processed_count == 1
            assert operation.failed_count == 1

        ambiguous_page = _rebuild_page("ambiguous-operation", watermark)
        async with sessions.begin() as session:
            session.add(_rebuild_operation("ambiguous-operation", watermark))

        ambiguous_calls = 0

        async def commit_then_raise(session: AsyncSession) -> None:
            nonlocal ambiguous_calls
            ambiguous_calls += 1
            await original_commit(session)
            if ambiguous_calls == 1:
                raise RuntimeError("ambiguous processed cursor failure")

        with monkeypatch.context() as patch:
            patch.setattr(AsyncSession, "commit", commit_then_raise)
            await process._record_processed(ambiguous_page, chunk)

        async with sessions() as session:
            operation = await session.get(
                MemoryVectorRebuildOperationRow,
                "ambiguous-operation",
            )
            assert operation is not None
            assert (operation.cursor_watermark, operation.cursor_chunk_id) == (
                watermark,
                "chunk-reconcile",
            )
            assert operation.processed_count == 1
            assert operation.failed_count == 0
    finally:
        await engine.dispose()
        await database.drop()


def _rebuild_page(operation_id: str, watermark: int) -> _RebuildPage:
    return _RebuildPage(
        operation_id=operation_id,
        space_id="space",
        memory_scope_id="scope",
        canonical_watermark=watermark,
        dead_event_watermark=0,
        batch_size=10,
    )


def _rebuild_operation(operation_id: str, watermark: int) -> MemoryVectorRebuildOperationRow:
    return MemoryVectorRebuildOperationRow(
        operation_id=operation_id,
        space_id="space",
        memory_scope_id="scope",
        status="running",
        canonical_watermark=watermark,
        dead_event_watermark=0,
        cursor_watermark=0,
        cursor_chunk_id=None,
        processed_count=0,
        failed_count=0,
        batch_size=10,
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
    )


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


def _chunk(chunk_id: str = "chunk-generic", sequence: int = 0) -> MemoryChunkRow:
    return MemoryChunkRow(
        id=chunk_id,
        space_id="space",
        memory_scope_id="scope",
        thread_id=None,
        document_id="document-generic",
        episode_id=None,
        source_type="document",
        source_external_id="generic-source",
        source_hash=f"generic-chunk-hash-{chunk_id}",
        kind="document_section",
        text="generic generation one",
        normalized_text="generic generation one",
        status="active",
        sequence=sequence,
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
