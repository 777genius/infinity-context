"""Live PostgreSQL race coverage for document deletion and fact mutation."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from time import monotonic

import pytest
from document_fact_source_ref_race_support import (
    AdmissionGateUnitOfWorkFactory,
    CanonicalIds,
    FixedClock,
    TrackingCanonicalUnitOfWorkFactory,
    active_facts_solely_backed_by_document,
)
from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactUnitOfWorkFactory,
)
from infinity_context_adapters.noop import SystemClock, UuidIdGenerator
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.fact_repositories import PostgresFactRepository
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryFactRow,
    MemoryFactVersionRow,
    MemoryOutboxRow,
    MemoryThreadRow,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWork,
    build_session_factory,
)
from infinity_context_core.application.dto import (
    DeleteDocumentCommand,
    DeleteThreadMemoryCommand,
    IngestDocumentCommand,
    RememberFactCommand,
    UpdateFactCommand,
)
from infinity_context_core.application.use_cases.delete_document import DeleteDocumentUseCase
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
from infinity_context_core.features.memory_facts.public import (
    FactTemporalExtent,
    MemoryFactEvidenceRef,
    ReinstateSupersededFactCommand,
    ReinstateSupersededFactHandler,
    SupersedeFactCommand,
    SupersedeFactHandler,
    memory_fact_identity_lock_key,
)
from infinity_context_core.features.memory_facts.public import (
    MemoryFact as CanonicalMemoryFact,
)
from infinity_context_core.features.memory_facts.public import (
    MemoryFactIdentity as CanonicalMemoryFactIdentity,
)
from infinity_context_core.features.memory_facts.public import (
    MemoryFactScope as CanonicalMemoryFactScope,
)
from infinity_context_core.features.memory_facts.public import (
    MemoryFactSourceRef as CanonicalMemoryFactSourceRef,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import select, text

NOW = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.parametrize("move_evidence", (False, True))
def test_document_delete_serializes_with_fact_update_when_postgres_is_configured(
    move_evidence: bool,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(
        _assert_document_delete_serializes_with_fact_update(
            database_url,
            move_evidence=move_evidence,
        )
    )


def test_document_delete_uses_shared_two_fact_lock_order_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_document_delete_uses_shared_two_fact_lock_order(database_url))


@pytest.mark.parametrize("mutation", ("create", "update", "update_exact_thread"))
def test_document_delete_admission_rejects_late_document_source_ref_writer(
    mutation: str,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_delete_admission_rejects_late_source_ref_writer(database_url, mutation))


def test_document_delete_admission_rejects_late_fact_reinstatement() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_delete_admission_rejects_late_reinstatement(database_url))


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
        await _wait_for_row_lock(engine, create_pid[0])
        await _wait_for_row_lock(engine, update_pid[0])
        await _wait_for_row_lock(engine, ingest_pid[0])

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


async def _assert_delete_admission_rejects_late_reinstatement(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="doc_del_reinstate",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    deletion = reinstatement = None
    release_delete = asyncio.Event()
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        async with sessions.begin() as session:
            session.add(_document())
            await session.flush()
            session.add(_chunk())

        scope = CanonicalMemoryFactScope("space-race", "scope-race", None)
        source_ref = CanonicalMemoryFactSourceRef(
            source_type="document",
            source_id="document-race",
            chunk_id="chunk-race",
        )
        predecessor = CanonicalMemoryFact.remember(
            identity=CanonicalMemoryFactIdentity("fact-old", scope),
            text="The document originally supported version one.",
            source_refs=(source_ref,),
            now=NOW,
            temporal_extent=FactTemporalExtent.ongoing_state(
                observed_at=NOW,
                valid_from=NOW,
                basis="primary_evidence",
            ),
        ).to_snapshot()
        successor = CanonicalMemoryFact.remember(
            identity=CanonicalMemoryFactIdentity("fact-new", scope),
            text="The document later supported version two.",
            source_refs=(source_ref,),
            now=NOW + timedelta(seconds=2),
            temporal_extent=FactTemporalExtent.ongoing_state(
                observed_at=NOW + timedelta(seconds=2),
                valid_from=NOW + timedelta(seconds=2),
                basis="primary_evidence",
            ),
        ).to_snapshot()
        canonical_clock = FixedClock(NOW + timedelta(seconds=2))
        canonical_factory = PostgresMemoryFactUnitOfWorkFactory(
            session_factory=sessions,
            clock=canonical_clock,
        )
        async with canonical_factory() as uow:
            await uow.coordinate_source_refs(scope=scope, source_refs=(source_ref,))
            await uow.facts.create(predecessor)
            await uow.facts.create(successor)
            await uow.commit()
        superseded = await SupersedeFactHandler(
            uow_factory=canonical_factory,
            clock=canonical_clock,
            ids=CanonicalIds("supersede"),
        ).execute(
            SupersedeFactCommand(
                successor_identity=successor.identity,
                predecessor_identity=predecessor.identity,
                expected_successor_version=1,
                expected_predecessor_version=1,
                effective_at=NOW + timedelta(seconds=2),
                evidence_refs=(
                    MemoryFactEvidenceRef(
                        evidence_id="supersession-evidence",
                        source_ref=source_ref,
                    ),
                ),
                actor_id="reviewer",
                reason_code="accepted_replacement",
                idempotency_key="supersede-race",
            )
        )

        admitted = asyncio.Event()
        delete_clock = FixedClock(NOW + timedelta(seconds=3))
        deletion = asyncio.create_task(
            DeleteDocumentUseCase(
                uow_factory=AdmissionGateUnitOfWorkFactory(
                    session_factory=sessions,
                    clock=delete_clock,
                    admitted=admitted,
                    release=release_delete,
                ),
                clock=delete_clock,
            ).execute(DeleteDocumentCommand(document_id="document-race"))
        )
        await asyncio.wait_for(admitted.wait(), timeout=2)

        writer_pid_ready = asyncio.Event()
        writer_pid: list[int] = []
        reinstatement = asyncio.create_task(
            ReinstateSupersededFactHandler(
                uow_factory=TrackingCanonicalUnitOfWorkFactory(
                    session_factory=sessions,
                    clock=FixedClock(NOW + timedelta(seconds=4)),
                    pid_ready=writer_pid_ready,
                    pid=writer_pid,
                ),
                clock=FixedClock(NOW + timedelta(seconds=4)),
                ids=CanonicalIds("reinstate"),
            ).execute(
                ReinstateSupersededFactCommand(
                    scope=scope,
                    supersession_decision_id=superseded.decision.decision_id,
                    expected_rejected_successor_version=2,
                    expected_original_predecessor_version=2,
                    evidence_refs=(
                        MemoryFactEvidenceRef(
                            evidence_id="reinstatement-evidence",
                            source_ref=source_ref,
                        ),
                    ),
                    actor_id="reviewer",
                    reason_code="replacement_rejected",
                    idempotency_key="reinstate-race",
                )
            )
        )
        await asyncio.wait_for(writer_pid_ready.wait(), timeout=2)
        await _wait_for_row_lock(engine, writer_pid[0])

        release_delete.set()
        await asyncio.wait_for(deletion, timeout=5)
        deletion = None
        with pytest.raises(MemoryConflictError, match="deleted document"):
            await asyncio.wait_for(reinstatement, timeout=5)
        reinstatement = None
        async with sessions() as session:
            assert (
                await active_facts_solely_backed_by_document(
                    session,
                    document_id="document-race",
                )
                == 0
            )
    finally:
        release_delete.set()
        for task in (deletion, reinstatement):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (deletion, reinstatement) if task is not None),
            return_exceptions=True,
        )
        await engine.dispose()
        await database.drop()


async def _assert_delete_admission_rejects_late_source_ref_writer(
    database_url: str,
    mutation: str,
) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix=f"doc_del_{mutation}",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    deletion = writer = None
    release_delete = asyncio.Event()
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        async with sessions.begin() as session:
            if mutation == "update_exact_thread":
                session.add(_thread("thread-exact-writer"))
                await session.flush()
            session.add(_document())
            await session.flush()
            session.add(_chunk())
        if mutation in {"update", "update_exact_thread"}:
            async with sessions.begin() as session:
                await PostgresFactRepository(session, now=NOW).create(
                    _fact_with_ref(
                        fact_id="fact-update",
                        ref=SourceRef(source_type="manual", source_id="manual-before-delete"),
                        thread_id=(
                            "thread-exact-writer" if mutation == "update_exact_thread" else None
                        ),
                    )
                )

        admitted = asyncio.Event()
        clock = SystemClock()
        deletion = asyncio.create_task(
            DeleteDocumentUseCase(
                uow_factory=AdmissionGateUnitOfWorkFactory(
                    session_factory=sessions,
                    clock=clock,
                    admitted=admitted,
                    release=release_delete,
                ),
                clock=clock,
            ).execute(DeleteDocumentCommand(document_id="document-race"))
        )
        await asyncio.wait_for(admitted.wait(), timeout=2)

        writer_pid_ready = asyncio.Event()
        writer_pid: list[int] = []
        writer_factory = _TrackingUnitOfWorkFactory(
            session_factory=sessions,
            clock=clock,
            pid_ready=writer_pid_ready,
            pid=writer_pid,
        )
        ref = SourceRef(
            source_type="document",
            source_id="document-race",
            chunk_id="chunk-race",
        )
        if mutation == "create":
            writer = asyncio.create_task(
                RememberFactUseCase(
                    uow_factory=writer_factory,
                    clock=clock,
                    ids=UuidIdGenerator(),
                ).execute(
                    RememberFactCommand(
                        space_id=SpaceId("space-race"),
                        memory_scope_id=MemoryScopeId("scope-race"),
                        thread_id=None,
                        text="Late document-backed fact.",
                        kind=MemoryKind.NOTE,
                        source_refs=(ref,),
                    )
                )
            )
        else:
            writer = asyncio.create_task(
                UpdateFactUseCase(uow_factory=writer_factory, clock=clock).execute(
                    UpdateFactCommand(
                        fact_id="fact-update",
                        expected_version=1,
                        text="Late source-ref replacement.",
                        source_refs=(ref,),
                        reason="exercise document deletion admission",
                    )
                )
            )
        await asyncio.wait_for(writer_pid_ready.wait(), timeout=2)
        await _wait_for_row_lock(engine, writer_pid[0])

        release_delete.set()
        deleted = await asyncio.wait_for(deletion, timeout=5)
        deletion = None
        assert deleted.document.status.value == "deleted"
        with pytest.raises(MemoryConflictError, match="deleted document"):
            await asyncio.wait_for(writer, timeout=5)
        writer = None

        async with sessions() as session:
            phantom_count = await active_facts_solely_backed_by_document(
                session,
                document_id="document-race",
            )
        assert phantom_count == 0
    finally:
        release_delete.set()
        for task in (deletion, writer):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (deletion, writer) if task is not None),
            return_exceptions=True,
        )
        await engine.dispose()
        await database.drop()


async def _assert_document_delete_uses_shared_two_fact_lock_order(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="doc_del_two_fact_order",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    multi_fact_task = delete_task = None
    continue_multi_fact = asyncio.Event()
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        async with sessions.begin() as session:
            session.add_all((_thread("thread-a"), _thread("thread-z")))
            await session.flush()
            session.add(_document())
            await session.flush()
            session.add(_chunk())
        async with sessions.begin() as session:
            repository = PostgresFactRepository(session, now=NOW)
            await repository.create(_fact(fact_id="fact-a", thread_id="thread-z"))
            await repository.create(_fact(fact_id="fact-z", thread_id="thread-a"))

        first_locked = asyncio.Event()
        multi_fact_task = asyncio.create_task(
            _lock_two_facts_in_shared_order(
                sessions,
                first_locked=first_locked,
                continue_after_first=continue_multi_fact,
            )
        )
        await asyncio.wait_for(first_locked.wait(), timeout=2)
        pid_ready = asyncio.Event()
        delete_pid: list[int] = []
        clock = SystemClock()
        delete_task = asyncio.create_task(
            DeleteDocumentUseCase(
                uow_factory=_TrackingUnitOfWorkFactory(
                    session_factory=sessions,
                    clock=clock,
                    pid_ready=pid_ready,
                    pid=delete_pid,
                ),
                clock=clock,
            ).execute(DeleteDocumentCommand(document_id="document-race"))
        )
        await asyncio.wait_for(pid_ready.wait(), timeout=2)
        await _wait_for_row_lock(engine, delete_pid[0])
        continue_multi_fact.set()
        locked_ids = await asyncio.wait_for(multi_fact_task, timeout=5)
        assert locked_ids == ("fact-z", "fact-a")
        multi_fact_task = None
        result = await asyncio.wait_for(delete_task, timeout=5)
        delete_task = None
        assert (result.deleted_chunks, result.deleted_facts) == (1, 2)

        async with sessions() as session:
            facts = tuple(
                (await session.execute(select(MemoryFactRow).order_by(MemoryFactRow.id))).scalars()
            )
            versions = tuple(
                (
                    await session.execute(
                        select(MemoryFactVersionRow).order_by(
                            MemoryFactVersionRow.fact_id,
                            MemoryFactVersionRow.version,
                        )
                    )
                ).scalars()
            )
            outbox = tuple(
                (
                    await session.execute(
                        select(
                            MemoryOutboxRow.event_type,
                            MemoryOutboxRow.aggregate_id,
                        ).order_by(MemoryOutboxRow.id)
                    )
                ).all()
            )
        assert [(row.id, row.status, row.version) for row in facts] == [
            ("fact-a", "deleted", 2),
            ("fact-z", "deleted", 2),
        ]
        assert [(row.fact_id, row.version, row.status) for row in versions] == [
            ("fact-a", 1, "active"),
            ("fact-a", 2, "deleted"),
            ("fact-z", 1, "active"),
            ("fact-z", 2, "deleted"),
        ]
        assert outbox == (
            ("vector.delete_chunks", "document-race"),
            ("cognee.forget_document", "document-race"),
            ("graph.delete_fact", "fact-z"),
            ("graph.delete_fact", "fact-a"),
        )
    finally:
        continue_multi_fact.set()
        for task in (multi_fact_task, delete_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (multi_fact_task, delete_task) if task is not None),
            return_exceptions=True,
        )
        await engine.dispose()
        await database.drop()


async def _lock_two_facts_in_shared_order(
    sessions,
    *,
    first_locked: asyncio.Event,
    continue_after_first: asyncio.Event,
) -> tuple[str, ...]:
    identities = tuple(
        sorted(
            (
                CanonicalMemoryFactIdentity(
                    "fact-a",
                    CanonicalMemoryFactScope("space-race", "scope-race", "thread-z"),
                ),
                CanonicalMemoryFactIdentity(
                    "fact-z",
                    CanonicalMemoryFactScope("space-race", "scope-race", "thread-a"),
                ),
            ),
            key=memory_fact_identity_lock_key,
        )
    )
    async with sessions.begin() as session:
        repository = PostgresFactRepository(session, now=NOW)
        for index, identity in enumerate(identities):
            assert await repository.get_for_update(identity.fact_id) is not None
            if index == 0:
                first_locked.set()
                await continue_after_first.wait()
    return tuple(identity.fact_id for identity in identities)


async def _assert_document_delete_serializes_with_fact_update(
    database_url: str,
    *,
    move_evidence: bool,
) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix=f"doc_del_fact_{'move' if move_evidence else 'same'}",
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
            if move_evidence:
                session.add(_document(document_id="document-other"))
            await session.flush()
            session.add(_chunk())
            if move_evidence:
                session.add(_chunk(chunk_id="chunk-other", document_id="document-other"))
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
            source_refs=(SourceRef("document", "document-other", chunk_id="chunk-other"),)
            if move_evidence
            else current.source_refs,
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
        assert result.deleted_facts == (0 if move_evidence else 1)

        async with sessions() as session:
            document = await session.get(MemoryDocumentRow, "document-race")
            chunk = await session.get(MemoryChunkRow, "chunk-race")
            fact = await session.get(MemoryFactRow, "fact-race")
            other_document = await session.get(MemoryDocumentRow, "document-other")
            other_chunk = await session.get(MemoryChunkRow, "chunk-other")
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
            "active" if move_evidence else "deleted",
            2 if move_evidence else 3,
            "Concurrent version must survive into the deletion history.",
        )
        expected_versions = [(1, "active"), (2, "active")]
        if not move_evidence:
            expected_versions.append((3, "deleted"))
        assert [(row.version, row.status) for row in versions] == expected_versions
        expected_events = [
            "vector.delete_chunks",
            "cognee.forget_document",
        ]
        if not move_evidence:
            expected_events.append("graph.delete_fact")
        assert event_types == expected_events
        if move_evidence:
            assert other_document is not None and other_document.status == "active"
            assert other_chunk is not None and other_chunk.status == "active"
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


def _thread(thread_id: str = "thread-race") -> MemoryThreadRow:
    return MemoryThreadRow(
        id=thread_id,
        space_id="space-race",
        memory_scope_id="scope-race",
        external_ref=thread_id,
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )


def _document(*, document_id: str = "document-race") -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id=document_id,
        space_id="space-race",
        memory_scope_id="scope-race",
        thread_id=None,
        title=f"Document fact race {document_id}",
        source_type="document",
        source_external_id=document_id,
        content_hash=f"hash-{document_id}",
        classification="internal",
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )


def _chunk(
    *,
    chunk_id: str = "chunk-race",
    document_id: str = "document-race",
) -> MemoryChunkRow:
    return MemoryChunkRow(
        id=chunk_id,
        space_id="space-race",
        memory_scope_id="scope-race",
        thread_id=None,
        document_id=document_id,
        episode_id=None,
        source_type="document",
        source_external_id=document_id,
        source_hash=f"hash-{chunk_id}",
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


def _fact(
    *,
    fact_id: str = "fact-race",
    thread_id: str | None = None,
) -> MemoryFact:
    return MemoryFact.create(
        fact_id=MemoryFactId(fact_id),
        space_id=SpaceId("space-race"),
        memory_scope_id=MemoryScopeId("scope-race"),
        thread_id=ThreadId(thread_id) if thread_id is not None else None,
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


def _fact_with_ref(*, fact_id: str, ref: SourceRef, thread_id: str | None = None) -> MemoryFact:
    return MemoryFact.create(
        fact_id=MemoryFactId(fact_id),
        space_id=SpaceId("space-race"),
        memory_scope_id=MemoryScopeId("scope-race"),
        thread_id=ThreadId(thread_id) if thread_id is not None else None,
        text=f"Fact {fact_id} before concurrent mutation.",
        kind=MemoryKind.NOTE,
        source_refs=(ref,),
        now=NOW,
    )
