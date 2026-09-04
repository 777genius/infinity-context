"""Live PostgreSQL gates for canonical fact source-reference completeness."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.noop import UuidIdGenerator
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.document_source_ref_coordination import (
    coordinate_document_source_ref_write,
)
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryEpisodeRow,
    MemoryThreadRow,
)
from infinity_context_adapters.postgres.repositories import PostgresCaptureRepository
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWork,
    PostgresUnitOfWorkFactory,
    build_session_factory,
)
from infinity_context_core.application.dto import (
    ConsolidateCaptureCommand,
    RememberFactCommand,
)
from infinity_context_core.application.use_cases.consolidate_capture import (
    ConsolidateCaptureUseCase,
)
from infinity_context_core.application.use_cases.remember_fact import RememberFactUseCase
from infinity_context_core.domain.capture import (
    CanonicalCapture,
    CaptureActorRole,
    CaptureSensitivity,
    CaptureSourceKind,
    MemoryCaptureId,
    SourceAuthority,
)
from infinity_context_core.domain.entities import (
    Confidence,
    DataClassification,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
    TrustLevel,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.auto_memory import MemoryCandidate, SourceProvenance
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text

NOW = datetime(2026, 9, 2, tzinfo=UTC)


@pytest.mark.parametrize(
    ("case", "source_ref", "fact_thread_id"),
    (
        (
            "missing_chunk",
            SourceRef("document", "document-local", chunk_id="chunk-missing"),
            None,
        ),
        (
            "cross_scope_chunk",
            SourceRef("document", "document-foreign", chunk_id="chunk-foreign"),
            None,
        ),
        ("missing_document", SourceRef("document", "document-missing"), None),
        ("cross_scope_document", SourceRef("document", "document-foreign"), None),
        (
            "inactive_chunk",
            SourceRef("document", "document-inactive-chunk", chunk_id="chunk-inactive"),
            None,
        ),
        ("inactive_document", SourceRef("document", "document-inactive"), None),
        (
            "cross_thread_chunk",
            SourceRef("document", "document-foreign-thread", chunk_id="chunk-foreign-thread"),
            "thread-local",
        ),
        (
            "cross_thread_document",
            SourceRef("document", "document-foreign-thread"),
            "thread-local",
        ),
        (
            "global_fact_private_document",
            SourceRef("document", "document-private"),
            None,
        ),
    ),
)
def test_canonical_source_ref_completeness_fails_before_fact_write(
    case: str,
    source_ref: SourceRef,
    fact_thread_id: str | None,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(
        _assert_invalid_reference_fails_closed(
            database_url,
            case,
            source_ref,
            fact_thread_id,
        )
    )


def test_thread_fact_accepts_exact_and_global_document_evidence() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_thread_fact_accepts_visible_evidence(database_url))


def test_thread_fact_accepts_live_episode_chunk_evidence() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_thread_fact_accepts_episode_evidence(database_url))


def test_chunk_parent_change_between_resolution_and_lock_fails_closed() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_chunk_parent_change_fails_closed(database_url))


def test_opposing_order_consolidations_lock_document_union_once() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_opposing_order_consolidations_complete(database_url))


async def _assert_invalid_reference_fails_closed(
    database_url: str,
    case: str,
    source_ref: SourceRef,
    fact_thread_id: str | None,
) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix=f"fact_ref_{case[:16]}",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        async with sessions.begin() as session:
            if fact_thread_id is not None:
                session.add(_thread(fact_thread_id))
            if "cross_scope" in case:
                session.add(_document("document-foreign", scope_id="scope-foreign"))
            if case == "inactive_chunk":
                session.add(_document("document-inactive-chunk"))
            if case == "inactive_document":
                session.add(_document("document-inactive", status="deleted"))
            if "cross_thread" in case:
                session.add(_document("document-foreign-thread", thread_id="thread-foreign"))
            if case == "global_fact_private_document":
                session.add(_document("document-private", thread_id="thread-private"))
            await session.flush()
            if case == "cross_scope_chunk":
                session.add(
                    _chunk(
                        "chunk-foreign",
                        "document-foreign",
                        scope_id="scope-foreign",
                    )
                )
            if case == "inactive_chunk":
                session.add(
                    _chunk(
                        "chunk-inactive",
                        "document-inactive-chunk",
                        status="deleted",
                    )
                )
            if case == "cross_thread_chunk":
                session.add(
                    _chunk(
                        "chunk-foreign-thread",
                        "document-foreign-thread",
                        thread_id="thread-foreign",
                    )
                )

        use_case = RememberFactUseCase(
            uow_factory=PostgresUnitOfWorkFactory(
                session_factory=sessions,
                clock=_FixedClock(),
            ),
            clock=_FixedClock(),
            ids=UuidIdGenerator(),
        )
        with pytest.raises(MemoryConflictError):
            await use_case.execute(
                RememberFactCommand(
                    space_id=SpaceId("space-local"),
                    memory_scope_id=MemoryScopeId("scope-local"),
                    thread_id=fact_thread_id,
                    text="This write must fail before becoming canonical.",
                    kind=MemoryKind.NOTE,
                    source_refs=(source_ref,),
                )
            )

        async with sessions() as session:
            assert await session.scalar(text("SELECT count(*) FROM memory_facts")) == 0
            assert await session.scalar(text("SELECT count(*) FROM memory_source_refs")) == 0
    finally:
        await engine.dispose()
        await database.drop()


async def _assert_thread_fact_accepts_visible_evidence(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="fact_ref_visibility",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        async with sessions.begin() as session:
            session.add(_thread("thread-local"))
            await session.flush()
            session.add_all(
                (
                    _document("document-global"),
                    _document("document-exact", thread_id="thread-local"),
                )
            )
            await session.flush()
            session.add_all(
                (
                    _chunk("chunk-global", "document-global"),
                    _chunk("chunk-exact", "document-exact", thread_id="thread-local"),
                )
            )
        use_case = RememberFactUseCase(
            uow_factory=PostgresUnitOfWorkFactory(
                session_factory=sessions,
                clock=_FixedClock(),
            ),
            clock=_FixedClock(),
            ids=UuidIdGenerator(),
        )
        result = await use_case.execute(
            RememberFactCommand(
                space_id=SpaceId("space-local"),
                memory_scope_id=MemoryScopeId("scope-local"),
                thread_id="thread-local",
                text="Thread facts may use exact and shared evidence.",
                kind=MemoryKind.NOTE,
                source_refs=(
                    SourceRef("document", "document-global", chunk_id="chunk-global"),
                    SourceRef("document", "document-exact", chunk_id="chunk-exact"),
                ),
            )
        )
        assert str(result.fact.thread_id) == "thread-local"
    finally:
        await engine.dispose()
        await database.drop()


async def _assert_thread_fact_accepts_episode_evidence(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="fact_ref_episode",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        async with sessions.begin() as session:
            session.add(_thread("thread-local"))
            session.add(_episode("episode-local", "thread-local"))
            await session.flush()
            session.add(_episode_chunk("chunk-episode", "episode-local", "thread-local"))
        result = await RememberFactUseCase(
            uow_factory=PostgresUnitOfWorkFactory(
                session_factory=sessions,
                clock=_FixedClock(),
            ),
            clock=_FixedClock(),
            ids=UuidIdGenerator(),
        ).execute(
            RememberFactCommand(
                space_id=SpaceId("space-local"),
                memory_scope_id=MemoryScopeId("scope-local"),
                thread_id="thread-local",
                text="Live episode evidence remains canonical.",
                kind=MemoryKind.NOTE,
                source_refs=(
                    SourceRef(
                        "system_audio",
                        "episode-source",
                        chunk_id="chunk-episode",
                    ),
                ),
            )
        )
        assert str(result.fact.thread_id) == "thread-local"
    finally:
        await engine.dispose()
        await database.drop()


async def _assert_chunk_parent_change_fails_closed(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="fact_ref_parent_change",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    coordinator_session = None
    task = None
    release = asyncio.Event()
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        async with sessions.begin() as session:
            session.add_all(
                (
                    _document("document-initial"),
                    _document("document-late"),
                )
            )
            await session.flush()
            session.add(_chunk("chunk-moving", "document-initial"))

        resolved = asyncio.Event()
        coordinator_session = sessions()
        await coordinator_session.begin()
        gated_session = _InitialResolutionGateSession(
            coordinator_session,
            resolved=resolved,
            release=release,
        )
        task = asyncio.create_task(
            coordinate_document_source_ref_write(
                gated_session,
                space_id="space-local",
                memory_scope_id="scope-local",
                thread_id=None,
                source_refs=(
                    SourceRef(
                        "document",
                        "document-initial",
                        chunk_id="chunk-moving",
                    ),
                ),
            )
        )
        await asyncio.wait_for(resolved.wait(), timeout=2)
        async with sessions.begin() as updater:
            moving = await updater.get(MemoryChunkRow, "chunk-moving")
            assert moving is not None
            moving.document_id = "document-late"
        release.set()
        with pytest.raises(MemoryConflictError, match="parent changed"):
            await asyncio.wait_for(task, timeout=5)
        task = None
    finally:
        release.set()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if coordinator_session is not None:
            await coordinator_session.rollback()
            await coordinator_session.close()
        await engine.dispose()
        await database.drop()


class _InitialResolutionGateSession:
    def __init__(self, inner, *, resolved, release) -> None:
        self._inner = inner
        self._resolved = resolved
        self._release = release
        self._gated = False

    def get_bind(self):
        return self._inner.get_bind()

    async def execute(self, statement, *args, **kwargs):
        result = await self._inner.execute(statement, *args, **kwargs)
        rendered = str(statement).upper()
        is_initial_chunk_parent_resolution = (
            "MEMORY_CHUNKS.ID" in rendered
            and "MEMORY_CHUNKS.DOCUMENT_ID" in rendered
            and "FOR UPDATE" not in rendered
        )
        if not self._gated and is_initial_chunk_parent_resolution:
            self._gated = True
            self._resolved.set()
            await self._release.wait()
        return result


async def _assert_opposing_order_consolidations_complete(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="capture_doc_union",
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
                    _document("document-z"),
                )
            )
            await session.flush()
            session.add_all(
                (
                    _chunk("chunk-a", "document-a"),
                    _chunk("chunk-z", "document-z"),
                )
            )
            captures = (_capture("capture-a"), _capture("capture-z"))
            repository = PostgresCaptureRepository(session)
            for capture in captures:
                await repository.create(capture)

        coordination_counts: dict[str, int] = {}
        factory = _CoordinationBarrierFactory(
            session_factory=sessions,
            clock=_FixedClock(),
            coordination_counts=coordination_counts,
            participants=2,
        )
        candidates = {
            "capture-a": _candidates(("a", "z")),
            "capture-z": _candidates(("z", "a")),
        }

        async def consolidate(capture_id: str):
            return await ConsolidateCaptureUseCase(
                uow_factory=factory,
                clock=_FixedClock(),
                ids=UuidIdGenerator(),
                extractor=_MappedExtractor(candidates),
                auto_apply_safe_enabled=True,
            ).execute(ConsolidateCaptureCommand(capture_id=capture_id))

        results = await asyncio.wait_for(
            asyncio.gather(consolidate("capture-a"), consolidate("capture-z")),
            timeout=8,
        )
        assert [result.auto_applied_facts for result in results] == [2, 2]
        assert coordination_counts == {"capture-a": 1, "capture-z": 1}

        async with sessions() as session:
            assert await session.scalar(text("SELECT count(*) FROM memory_facts")) == 4
            dangling = await session.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM memory_source_refs ref
                    JOIN memory_facts fact
                      ON fact.id = ref.fact_id AND fact.version = ref.fact_version
                    LEFT JOIN memory_chunks chunk ON chunk.id = ref.chunk_id
                    LEFT JOIN memory_documents document ON document.id = chunk.document_id
                    WHERE fact.status = 'active'
                      AND (
                        chunk.id IS NULL OR chunk.status <> 'active'
                        OR document.id IS NULL OR document.status <> 'active'
                        OR chunk.space_id <> fact.space_id
                        OR chunk.memory_scope_id <> fact.memory_scope_id
                      )
                    """
                )
            )
            assert dangling == 0
    finally:
        await engine.dispose()
        await database.drop()


class _FixedClock:
    def now(self) -> datetime:
        return NOW


class _MappedExtractor:
    version = "opposing-order-test-v1"
    prompt_version = None
    requires_external_ai = False

    def __init__(self, candidates: dict[str, tuple[MemoryCandidate, ...]]) -> None:
        self._candidates = candidates

    async def extract_facts(
        self,
        *,
        text: str,
        source: SourceProvenance,
    ) -> tuple[MemoryCandidate, ...]:
        del text
        return self._candidates[source.source_id]


class _TrackingCaptureRepository:
    def __init__(self, inner, owner) -> None:
        self._inner = inner
        self._owner = owner

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    async def get_for_update(self, capture_id: str):
        capture = await self._inner.get_for_update(capture_id)
        self._owner._capture_id = capture_id
        return capture


class _CoordinationBarrierUnitOfWork(PostgresUnitOfWork):
    def __init__(self, *, coordination_counts, arrived, release, participants, **kwargs) -> None:
        super().__init__(**kwargs)
        self._coordination_counts = coordination_counts
        self._arrived = arrived
        self._release = release
        self._participants = participants
        self._capture_id: str | None = None

    async def __aenter__(self):
        entered = await super().__aenter__()
        self.captures = _TrackingCaptureRepository(self.captures, self)
        return entered

    async def coordinate_fact_source_refs(self, **kwargs) -> None:
        assert self._capture_id is not None
        capture_id = self._capture_id
        self._coordination_counts[capture_id] = self._coordination_counts.get(capture_id, 0) + 1
        self._arrived.add(capture_id)
        if len(self._arrived) == self._participants:
            self._release.set()
        await self._release.wait()
        await super().coordinate_fact_source_refs(**kwargs)


class _CoordinationBarrierFactory:
    def __init__(self, *, session_factory, clock, coordination_counts, participants) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._coordination_counts = coordination_counts
        self._participants = participants
        self._arrived: set[str] = set()
        self._release = asyncio.Event()

    def __call__(self) -> _CoordinationBarrierUnitOfWork:
        return _CoordinationBarrierUnitOfWork(
            session_factory=self._session_factory,
            clock=self._clock,
            coordination_counts=self._coordination_counts,
            arrived=self._arrived,
            release=self._release,
            participants=self._participants,
        )


def _capture(capture_id: str) -> CanonicalCapture:
    text_value = "Alpha document fact. Zulu document fact."
    return CanonicalCapture.create(
        capture_id=MemoryCaptureId(capture_id),
        space_id=SpaceId("space-local"),
        memory_scope_id=MemoryScopeId("scope-local"),
        thread_id=None,
        source_agent="test",
        source_kind=CaptureSourceKind.MANUAL,
        event_type="memory.capture",
        actor_role=CaptureActorRole.USER,
        text=text_value,
        evidence_refs=(),
        payload_hash=f"hash-{capture_id}",
        idempotency_key=f"key-{capture_id}",
        trust_level=TrustLevel.HIGH,
        source_authority=SourceAuthority.EXPLICIT_USER_COMMAND,
        sensitivity=CaptureSensitivity.LOW,
        data_classification=DataClassification.INTERNAL,
        occurred_at=NOW,
        now=NOW,
        metadata={"admission_reason": "accepted"},
    )


def _candidates(order: tuple[str, str]) -> tuple[MemoryCandidate, ...]:
    labels = {"a": "Alpha", "z": "Zulu"}
    return tuple(
        MemoryCandidate(
            text=f"{labels[key]} document fact.",
            kind=MemoryKind.NOTE,
            confidence=Confidence.HIGH,
            source_refs=(
                SourceRef(
                    "document",
                    f"document-{key}",
                    chunk_id=f"chunk-{key}",
                    quote_preview=f"{labels[key]} document fact.",
                ),
            ),
            safe_reason="Explicit durable user memory.",
            ttl_policy="durable",
        )
        for key in order
    )


def _document(
    document_id: str,
    *,
    scope_id: str = "scope-local",
    thread_id: str | None = None,
    status: str = "active",
) -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id=document_id,
        space_id="space-local",
        memory_scope_id=scope_id,
        thread_id=thread_id,
        title=document_id,
        source_type="document",
        source_external_id=document_id,
        content_hash=f"hash-{document_id}",
        classification="internal",
        status=status,
        retrieval_projected=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _thread(thread_id: str) -> MemoryThreadRow:
    return MemoryThreadRow(
        id=thread_id,
        space_id="space-local",
        memory_scope_id="scope-local",
        external_ref=thread_id,
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )


def _episode(episode_id: str, thread_id: str) -> MemoryEpisodeRow:
    return MemoryEpisodeRow(
        id=episode_id,
        space_id="space-local",
        memory_scope_id="scope-local",
        thread_id=thread_id,
        source_type="system_audio",
        source_external_id="episode-source",
        text="Live episode evidence remains canonical.",
        speaker="user",
        trust_level="high",
        status="active",
        occurred_at=NOW,
        created_at=NOW,
        metadata_json={},
    )


def _episode_chunk(chunk_id: str, episode_id: str, thread_id: str) -> MemoryChunkRow:
    row = _chunk(chunk_id, "unused", thread_id=thread_id)
    row.document_id = None
    row.episode_id = episode_id
    row.source_type = "system_audio"
    row.source_external_id = "episode-source"
    row.kind = "episode_excerpt"
    return row


def _chunk(
    chunk_id: str,
    document_id: str,
    *,
    scope_id: str = "scope-local",
    thread_id: str | None = None,
    status: str = "active",
) -> MemoryChunkRow:
    return MemoryChunkRow(
        id=chunk_id,
        space_id="space-local",
        memory_scope_id=scope_id,
        thread_id=thread_id,
        document_id=document_id,
        episode_id=None,
        source_type="document",
        source_external_id=document_id,
        source_hash=f"hash-{chunk_id}",
        kind="document_section",
        text=f"Evidence for {document_id}.",
        normalized_text=f"evidence for {document_id}.",
        status=status,
        sequence=0,
        char_start=0,
        char_end=24,
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
