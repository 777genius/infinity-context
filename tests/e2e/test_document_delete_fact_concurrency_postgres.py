"""Live PostgreSQL race coverage for document deletion and fact mutation."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from time import monotonic

import pytest
from infinity_context_adapters.noop import SystemClock
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.fact_repositories import PostgresFactRepository
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryFactRow,
    MemoryFactVersionRow,
    MemoryOutboxRow,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWork,
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

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def test_document_delete_serializes_with_fact_update_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_document_delete_serializes_with_fact_update(database_url))


async def _assert_document_delete_serializes_with_fact_update(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="document_delete_fact_race",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    updater = None
    delete_task = None
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        async with sessions.begin() as session:
            session.add(_document())
            session.add(_chunk())
        async with sessions.begin() as session:
            await PostgresFactRepository(session, now=NOW).create(_fact())

        updater = sessions()
        await updater.begin()
        updater_facts = PostgresFactRepository(updater, now=NOW)
        current = await updater_facts.get_for_update("fact-race")
        assert current is not None
        concurrent = current.update(
            expected_version=1,
            text="Concurrent version must survive into the deletion history.",
            source_refs=current.source_refs,
            reason="exercise document deletion race",
            now=NOW + timedelta(seconds=1),
        )
        await updater_facts.save(concurrent)

        pid_ready = asyncio.Event()
        delete_pid: list[int] = []
        clock = SystemClock()
        use_case = DeleteDocumentUseCase(
            uow_factory=_TrackingUnitOfWorkFactory(
                session_factory=sessions,
                clock=clock,
                pid_ready=pid_ready,
                pid=delete_pid,
            ),
            clock=clock,
        )
        delete_task = asyncio.create_task(
            use_case.execute(DeleteDocumentCommand(document_id="document-race"))
        )
        await asyncio.wait_for(pid_ready.wait(), timeout=2)
        await _wait_for_row_lock(engine, delete_pid[0])

        await updater.commit()
        await updater.close()
        updater = None

        result = await asyncio.wait_for(delete_task, timeout=5)
        delete_task = None
        assert result.deleted_chunks == 1
        assert result.deleted_facts == 1

        async with sessions() as session:
            document = await session.get(MemoryDocumentRow, "document-race")
            chunk = await session.get(MemoryChunkRow, "chunk-race")
            fact = await session.get(MemoryFactRow, "fact-race")
            versions = list(
                (
                    await session.execute(
                        select(MemoryFactVersionRow)
                        .where(MemoryFactVersionRow.fact_id == "fact-race")
                        .order_by(MemoryFactVersionRow.version)
                    )
                ).scalars()
            )
            event_types = list(
                (
                    await session.execute(
                        select(MemoryOutboxRow.event_type).order_by(MemoryOutboxRow.id)
                    )
                ).scalars()
            )

        assert document is not None and document.status == "deleted"
        assert chunk is not None and chunk.status == "deleted"
        assert fact is not None
        assert (fact.status, fact.version, fact.text) == (
            "deleted",
            3,
            "Concurrent version must survive into the deletion history.",
        )
        assert [(row.version, row.status) for row in versions] == [
            (1, "active"),
            (2, "active"),
            (3, "deleted"),
        ]
        assert event_types == [
            "vector.delete_chunks",
            "cognee.forget_document",
            "graph.delete_fact",
        ]
    finally:
        if delete_task is not None:
            delete_task.cancel()
            await asyncio.gather(delete_task, return_exceptions=True)
        if updater is not None:
            await updater.rollback()
            await updater.close()
        await engine.dispose()
        await database.drop()


async def _wait_for_row_lock(engine, pid: int) -> None:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        async with engine.connect() as observer:
            wait_event_type = await observer.scalar(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            )
        if wait_event_type == "Lock":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("document deletion did not wait for the concurrent fact row lock")


class _TrackingUnitOfWork(PostgresUnitOfWork):
    def __init__(self, *, pid_ready: asyncio.Event, pid: list[int], **kwargs) -> None:
        super().__init__(**kwargs)
        self._pid_ready = pid_ready
        self._pid = pid

    async def __aenter__(self):
        entered = await super().__aenter__()
        assert self._session is not None
        backend_pid = await self._session.scalar(text("SELECT pg_backend_pid()"))
        assert backend_pid is not None
        self._pid.append(backend_pid)
        self._pid_ready.set()
        return entered


class _TrackingUnitOfWorkFactory:
    def __init__(
        self,
        *,
        session_factory,
        clock,
        pid_ready: asyncio.Event,
        pid: list[int],
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._pid_ready = pid_ready
        self._pid = pid

    def __call__(self) -> _TrackingUnitOfWork:
        return _TrackingUnitOfWork(
            session_factory=self._session_factory,
            clock=self._clock,
            pid_ready=self._pid_ready,
            pid=self._pid,
        )


def _document() -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id="document-race",
        space_id="space-race",
        memory_scope_id="scope-race",
        thread_id=None,
        title="Document fact race",
        source_type="document",
        source_external_id="document-fact-race",
        content_hash="document-fact-race-hash",
        classification="internal",
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )


def _chunk() -> MemoryChunkRow:
    return MemoryChunkRow(
        id="chunk-race",
        space_id="space-race",
        memory_scope_id="scope-race",
        thread_id=None,
        document_id="document-race",
        episode_id=None,
        source_type="document",
        source_external_id="document-fact-race",
        source_hash="document-fact-race-chunk-hash",
        kind="document_section",
        text="Document fact race evidence.",
        normalized_text="document fact race evidence.",
        status="active",
        sequence=0,
        char_start=0,
        char_end=28,
        token_estimate=5,
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


def _fact() -> MemoryFact:
    return MemoryFact.create(
        fact_id=MemoryFactId("fact-race"),
        space_id=SpaceId("space-race"),
        memory_scope_id=MemoryScopeId("scope-race"),
        text="Document-backed fact before concurrent update.",
        kind=MemoryKind.NOTE,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="document-race",
                chunk_id="chunk-race",
            ),
        ),
        now=NOW,
    )
