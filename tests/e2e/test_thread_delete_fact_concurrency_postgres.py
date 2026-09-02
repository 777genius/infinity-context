"""Live PostgreSQL race coverage for thread deletion and late writers."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from time import monotonic

import pytest
from infinity_context_adapters.noop import SystemClock, UuidIdGenerator
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.fact_repositories import PostgresFactRepository
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryFactRow,
    MemoryThreadRow,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWork,
    build_session_factory,
)
from infinity_context_core.application.dto import (
    DeleteThreadMemoryCommand,
    IngestDocumentCommand,
    RememberFactCommand,
    UpdateFactCommand,
)
from infinity_context_core.application.use_cases.delete_thread_memory import (
    DeleteThreadMemoryUseCase,
)
from infinity_context_core.application.use_cases.ingest_document import IngestDocumentUseCase
from infinity_context_core.application.use_cases.remember_fact import RememberFactUseCase
from infinity_context_core.application.use_cases.update_fact import UpdateFactUseCase
from infinity_context_core.domain.entities import (
    MemoryFact,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
    ThreadId,
)
from infinity_context_core.domain.errors import MemoryConflictError
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import select, text

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def test_thread_delete_rejects_concurrent_late_fact_create_and_update() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_thread_delete_rejects_late_fact_writers(database_url))


async def _assert_thread_delete_rejects_late_fact_writers(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="thr_del_late_writers",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    deletion = create_writer = update_writer = ingest_writer = None
    release_delete = asyncio.Event()
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        document = _document()
        document.thread_id = "thread-race"
        chunk = _chunk()
        chunk.thread_id = "thread-race"
        async with sessions.begin() as session:
            session.add(_thread())
            await session.flush()
            session.add(document)
            await session.flush()
            session.add(chunk)
        async with sessions.begin() as session:
            await PostgresFactRepository(session, now=NOW).create(
                _fact(fact_id="fact-update", thread_id="thread-race")
            )

        admitted = asyncio.Event()
        clock = SystemClock()
        deletion = asyncio.create_task(
            DeleteThreadMemoryUseCase(
                uow_factory=_ThreadDeleteGateUnitOfWorkFactory(
                    session_factory=sessions,
                    clock=clock,
                    admitted=admitted,
                    release=release_delete,
                )
            ).execute(
                DeleteThreadMemoryCommand(
                    space_id=SpaceId("space-race"),
                    memory_scope_id=MemoryScopeId("scope-race"),
                    thread_id=ThreadId("thread-race"),
                )
            )
        )
        await asyncio.wait_for(admitted.wait(), timeout=2)

        document_ref = SourceRef("document", "document-race", chunk_id="chunk-race")
        manual_ref = SourceRef("manual", "manual-race")
        create_pid_ready = asyncio.Event()
        update_pid_ready = asyncio.Event()
        ingest_pid_ready = asyncio.Event()
        create_pid: list[int] = []
        update_pid: list[int] = []
        ingest_pid: list[int] = []
        create_factory = _TrackingUnitOfWorkFactory(
            session_factory=sessions,
            clock=clock,
            pid_ready=create_pid_ready,
            pid=create_pid,
        )
        update_factory = _TrackingUnitOfWorkFactory(
            session_factory=sessions,
            clock=clock,
            pid_ready=update_pid_ready,
            pid=update_pid,
        )
        ingest_factory = _TrackingUnitOfWorkFactory(
            session_factory=sessions,
            clock=clock,
            pid_ready=ingest_pid_ready,
            pid=ingest_pid,
        )
        create_writer = asyncio.create_task(
            RememberFactUseCase(
                uow_factory=create_factory,
                clock=clock,
                ids=UuidIdGenerator(),
            ).execute(
                RememberFactCommand(
                    space_id=SpaceId("space-race"),
                    memory_scope_id=MemoryScopeId("scope-race"),
                    thread_id=ThreadId("thread-race"),
                    text="Late thread fact must not survive deletion.",
                    kind=MemoryKind.NOTE,
                    source_refs=(manual_ref,),
                )
            )
        )
        update_writer = asyncio.create_task(
            UpdateFactUseCase(uow_factory=update_factory, clock=clock).execute(
                UpdateFactCommand(
                    fact_id="fact-update",
                    expected_version=1,
                    text="Late update must not survive thread deletion.",
                    source_refs=(document_ref,),
                    reason="exercise thread deletion admission",
                )
            )
        )
        ingest_writer = asyncio.create_task(
            IngestDocumentUseCase(
                uow_factory=ingest_factory,
                clock=clock,
                ids=UuidIdGenerator(),
            ).execute(
                IngestDocumentCommand(
                    space_id=SpaceId("space-race"),
                    memory_scope_id=MemoryScopeId("scope-race"),
                    thread_id=ThreadId("thread-race"),
                    title="Late document",
                    text="Late document content must not survive thread deletion.",
                    source_type="document",
                    source_external_id="late-document",
                )
            )
        )
        await asyncio.wait_for(create_pid_ready.wait(), timeout=2)
        await asyncio.wait_for(update_pid_ready.wait(), timeout=2)
        await asyncio.wait_for(ingest_pid_ready.wait(), timeout=2)
        await _wait_for_lock(engine, create_pid[0])
        await _wait_for_lock(engine, update_pid[0])
        await _wait_for_lock(engine, ingest_pid[0])

        release_delete.set()
        result = await asyncio.wait_for(deletion, timeout=5)
        deletion = None
        assert result.deleted_facts == 1
        for writer in (create_writer, update_writer):
            with pytest.raises(MemoryConflictError, match="lifecycle|deleted document"):
                await asyncio.wait_for(writer, timeout=5)
        with pytest.raises(MemoryConflictError, match="lifecycle"):
            await asyncio.wait_for(ingest_writer, timeout=5)
        create_writer = update_writer = ingest_writer = None

        async with sessions() as session:
            assert (
                await session.scalar(
                    select(MemoryFactRow.id).where(
                        MemoryFactRow.thread_id == "thread-race",
                        MemoryFactRow.status == "active",
                    )
                )
                is None
            )
            assert (
                await session.scalar(
                    select(MemoryDocumentRow.id).where(
                        MemoryDocumentRow.thread_id == "thread-race",
                        MemoryDocumentRow.status == "active",
                    )
                )
                is None
            )
    finally:
        release_delete.set()
        for task in (deletion, create_writer, update_writer, ingest_writer):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(
                task
                for task in (deletion, create_writer, update_writer, ingest_writer)
                if task is not None
            ),
            return_exceptions=True,
        )
        await engine.dispose()
        await database.drop()


class _ThreadDeleteGateScopeRepository:
    def __init__(self, inner, *, admitted, release) -> None:
        self._inner = inner
        self._admitted = admitted
        self._release = release

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def delete_thread_memory(self, **kwargs):
        result = await self._inner.delete_thread_memory(**kwargs)
        self._admitted.set()
        await self._release.wait()
        return result


class _ThreadDeleteGateUnitOfWork(PostgresUnitOfWork):
    def __init__(self, *, admitted, release, **kwargs) -> None:
        super().__init__(**kwargs)
        self._admitted = admitted
        self._release = release

    async def __aenter__(self):
        entered = await super().__aenter__()
        self.scope = _ThreadDeleteGateScopeRepository(
            self.scope,
            admitted=self._admitted,
            release=self._release,
        )
        return entered


class _ThreadDeleteGateUnitOfWorkFactory:
    def __init__(self, *, session_factory, clock, admitted, release) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._admitted = admitted
        self._release = release

    def __call__(self):
        return _ThreadDeleteGateUnitOfWork(
            session_factory=self._session_factory,
            clock=self._clock,
            admitted=self._admitted,
            release=self._release,
        )


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
    def __init__(self, *, session_factory, clock, pid_ready, pid) -> None:
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


async def _wait_for_lock(engine, pid: int) -> None:
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
    raise AssertionError("late exact-thread writer did not wait for the lifecycle fence")


def _thread() -> MemoryThreadRow:
    return MemoryThreadRow(
        id="thread-race",
        space_id="space-race",
        memory_scope_id="scope-race",
        external_ref="thread-race",
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )


def _document() -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id="document-race",
        space_id="space-race",
        memory_scope_id="scope-race",
        thread_id=None,
        title="Document fact race",
        source_type="document",
        source_external_id="document-race",
        content_hash="hash-document-race",
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
        source_external_id="document-race",
        source_hash="hash-chunk-race",
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


def _fact(*, fact_id: str, thread_id: str) -> MemoryFact:
    return MemoryFact.create(
        fact_id=MemoryFactId(fact_id),
        space_id=SpaceId("space-race"),
        memory_scope_id=MemoryScopeId("scope-race"),
        thread_id=ThreadId(thread_id),
        text=f"Document-backed fact {fact_id} before concurrent update.",
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
