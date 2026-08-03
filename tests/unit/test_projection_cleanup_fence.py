import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres.projection_fence import (
    PostgresProjectionFence,
    _projection_fence_query,
    _projection_state_query,
)
from infinity_context_core.domain.entities import FactStatus, LifecycleStatus
from infinity_context_core.ports.adapters import (
    AdapterCapabilities,
    EmbeddingResult,
    PortStatus,
    VectorWriteResult,
)
from infinity_context_core.ports.capabilities import (
    CapabilityDiagnostic,
    CapabilityStatus,
    ProjectionForgetResult,
    ProjectionWriteResult,
)
from infinity_context_core.ports.projection_fence import ProjectionFencePermit
from infinity_context_server.processes.outbox import ClaimedOutboxJob
from infinity_context_server.processes.projections import (
    OutboxProjectionError,
    ProjectionOutboxProcess,
)
from sqlalchemy.dialects import postgresql


class CoordinatedFence:
    def __init__(self, events: list[str]) -> None:
        self._condition = asyncio.Condition()
        self._active = 0
        self.cleanup_waiting = asyncio.Event()
        self._cleanup_waiting = False
        self._pending = False
        self._events = events

    @asynccontextmanager
    async def hold(self, _space_id: str):
        async with self._condition:
            await self._condition.wait_for(lambda: not self._cleanup_waiting)
            if self._pending:
                permit = ProjectionFencePermit(allow_upsert=False)
            else:
                self._active += 1
                permit = ProjectionFencePermit(allow_upsert=True)
        try:
            yield permit
        finally:
            if permit.allow_upsert:
                async with self._condition:
                    self._active -= 1
                    self._condition.notify_all()

    async def begin_cleanup(self) -> None:
        async with self._condition:
            self._cleanup_waiting = True
            self.cleanup_waiting.set()
            await self._condition.wait_for(lambda: self._active == 0)
            self._pending = True
            self._cleanup_waiting = False
            self._events.append("cleanup.commit")
            self._condition.notify_all()


class SequencedRepository:
    def __init__(self, *items) -> None:
        self._items = list(items)

    async def get_by_id(self, _item_id: str):
        if len(self._items) > 1:
            return self._items.pop(0)
        return self._items[0] if self._items else None


class DocumentRepository(SequencedRepository):
    def __init__(self, *items, chunks: tuple[object, ...]) -> None:
        super().__init__(*items)
        self._chunks = chunks

    async def list_chunks(self, _document_id: str):
        return list(self._chunks)


class FakeUnitOfWork:
    def __init__(self, *, chunk, fact, document, document_chunks) -> None:
        self.chunks = chunk
        self.facts = fact
        self.documents = DocumentRepository(*document, chunks=document_chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None


class FakeUnitOfWorkFactory:
    def __init__(self, *, chunks, facts, documents, document_chunks) -> None:
        self._uow = FakeUnitOfWork(
            chunk=SequencedRepository(*chunks),
            fact=SequencedRepository(*facts),
            document=documents,
            document_chunks=document_chunks,
        )

    def __call__(self):
        return self._uow


class RecordingAdapters:
    def __init__(self, lane: str, events: list[str]) -> None:
        self.lane = lane
        self.events = events
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name="recording-vector",
            enabled=True,
            healthy=True,
            supports_upsert=True,
            supports_delete=True,
            supports_search=False,
            supports_filters=False,
        )

    async def embed_texts(self, _texts: tuple[str, ...]) -> EmbeddingResult:
        return EmbeddingResult(status=PortStatus.OK, vectors=((0.25, 0.75),))

    async def upsert_chunks(self, _items) -> VectorWriteResult:
        await self._record_upsert("vector")
        return VectorWriteResult.ok(1)

    async def delete_chunks(self, _chunk_ids) -> VectorWriteResult:
        self.events.append("vector.delete")
        return VectorWriteResult.ok(1)

    async def upsert_fact(self, _fact_id, _text, _metadata) -> VectorWriteResult:
        await self._record_upsert("graph")
        return VectorWriteResult.ok(1)

    async def delete_fact(self, _fact_id) -> VectorWriteResult:
        self.events.append("graph.delete")
        return VectorWriteResult.ok(1)

    async def ingest_document(self, command) -> ProjectionWriteResult:
        await self._record_upsert("cognee")
        return ProjectionWriteResult(
            status=CapabilityStatus.OK,
            affected_ids=(command.document_id,),
        )

    async def forget_document(self, command) -> ProjectionForgetResult:
        self.events.append("cognee.delete")
        return ProjectionForgetResult(
            status=CapabilityStatus.OK,
            forgotten_ids=command.canonical_ids,
        )

    async def _record_upsert(self, lane: str) -> None:
        if lane != self.lane:
            raise AssertionError(f"unexpected lane {lane}")
        self.events.append(f"{lane}.upsert.start")
        self.started.set()
        await self.release.wait()
        self.events.append(f"{lane}.upsert.finish")


class ConfigurableCogneeMemory:
    def __init__(self, result: ProjectionForgetResult) -> None:
        self._result = result
        self.requests: list[object] = []

    async def forget_document(self, command) -> ProjectionForgetResult:
        self.requests.append(command)
        return self._result


def _chunk(space_id: str = "benchmark-space") -> SimpleNamespace:
    return SimpleNamespace(
        id="chunk-1",
        space_id=space_id,
        memory_scope_id="scope-1",
        thread_id="thread-1",
        document_id="document-1",
        status=LifecycleStatus.ACTIVE,
        classification="internal",
        text="chunk text",
        metadata={},
        source_type="document",
        source_external_id="source-1",
        kind=SimpleNamespace(value="document"),
        token_estimate=2,
        char_start=0,
        char_end=10,
    )


def _fact(space_id: str = "benchmark-space") -> SimpleNamespace:
    return SimpleNamespace(
        id="fact-1",
        space_id=space_id,
        memory_scope_id="scope-1",
        status=FactStatus.ACTIVE,
        version=1,
        text="fact text",
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _document(space_id: str = "benchmark-space") -> SimpleNamespace:
    return SimpleNamespace(
        id="document-1",
        space_id=space_id,
        memory_scope_id="scope-1",
        status=LifecycleStatus.ACTIVE,
        classification="internal",
        title="Document",
        source_type="document",
    )


def _process(
    lane: str,
    fence: CoordinatedFence,
    events: list[str],
    *,
    moved: bool = False,
) -> tuple[ProjectionOutboxProcess, RecordingAdapters]:
    second_space = "other-space" if moved else "benchmark-space"
    chunks = (_chunk(), _chunk(second_space))
    facts = (_fact(), _fact(second_space))
    documents = (_document(), _document(second_space))
    uow_factory = FakeUnitOfWorkFactory(
        chunks=chunks,
        facts=facts,
        documents=documents,
        document_chunks=(_chunk(second_space),),
    )
    adapters = RecordingAdapters(lane, events)
    container = SimpleNamespace(
        projection_fence=fence,
        uow_factory=uow_factory,
        vector_index=adapters,
        graph_index=adapters,
        cognee_memory=adapters,
        embedder=adapters,
        settings=SimpleNamespace(max_embedding_tokens_per_document=100),
    )
    return ProjectionOutboxProcess(container), adapters


def _job(lane: str, *, delete: bool = False) -> ClaimedOutboxJob:
    values = {
        "vector": (
            "vector.delete_chunks" if delete else "vector.upsert_chunk",
            "chunk-1",
            {"chunk_ids": ["chunk-1"]} if delete else {"chunk_id": "chunk-1"},
        ),
        "graph": (
            "graph.delete_fact" if delete else "graph.upsert_fact",
            "fact-1",
            {"fact_id": "fact-1"} if delete else {},
        ),
        "cognee": (
            "cognee.forget_document" if delete else "cognee.ingest_document",
            "document-1",
            {"document_id": "document-1"} if delete else {},
        ),
    }
    event_type, aggregate_id, payload = values[lane]
    return ClaimedOutboxJob(
        id=1 if not delete else 2,
        event_type=event_type,
        aggregate_id=aggregate_id,
        aggregate_version=1 if lane == "graph" and not delete else None,
        attempt_count=0,
        workload_class="projection",
        fairness_key=f"{lane}:{aggregate_id}",
        payload_json=payload,
    )


async def _dispatch(process: ProjectionOutboxProcess, job: ClaimedOutboxJob) -> None:
    await process.handlers()[job.event_type](job)


def _cognee_forget_job(
    *,
    cleanup_run_id_sha256: str | None = None,
) -> ClaimedOutboxJob:
    payload: dict[str, object] = {
        "document_id": "document-1",
        "chunk_ids": ["chunk-1"],
    }
    if cleanup_run_id_sha256 is not None:
        payload["cleanup_run_id_sha256"] = cleanup_run_id_sha256
    return ClaimedOutboxJob(
        id=3,
        event_type="cognee.forget_document",
        aggregate_id="document-1",
        aggregate_version=None,
        attempt_count=0,
        workload_class="projection",
        fairness_key="cognee:document-1",
        payload_json=payload,
    )


@pytest.mark.parametrize(
    ("status", "cleanup_run_id_sha256", "expected_diagnostic_code"),
    [
        (CapabilityStatus.DISABLED, None, None),
        (CapabilityStatus.DISABLED, "a" * 64, "cognee.disabled"),
        (CapabilityStatus.OK, "a" * 64, None),
        (CapabilityStatus.DEGRADED, None, "cognee.degraded"),
    ],
)
def test_cognee_forget_handler_preserves_ordinary_and_benchmark_status_semantics(
    status: CapabilityStatus,
    cleanup_run_id_sha256: str | None,
    expected_diagnostic_code: str | None,
) -> None:
    async def run() -> tuple[str | None, ConfigurableCogneeMemory]:
        diagnostics = (
            ()
            if status == CapabilityStatus.OK
            else (
                CapabilityDiagnostic(
                    code=f"cognee.{status.value}",
                    safe_message="Safe projection status.",
                ),
            )
        )
        adapter = ConfigurableCogneeMemory(
            ProjectionForgetResult(
                status=status,
                forgotten_ids=(),
                diagnostics=diagnostics,
            )
        )
        process = ProjectionOutboxProcess(SimpleNamespace(cognee_memory=adapter))
        try:
            await _dispatch(
                process,
                _cognee_forget_job(
                    cleanup_run_id_sha256=cleanup_run_id_sha256,
                ),
            )
        except OutboxProjectionError as error:
            return error.diagnostic_code, adapter
        return None, adapter

    diagnostic_code, adapter = asyncio.run(run())

    assert diagnostic_code == expected_diagnostic_code
    assert len(adapter.requests) == 1
    assert adapter.requests[0].canonical_ids == ("document-1", "chunk-1")


def test_cognee_benchmark_forget_rejects_invalid_cleanup_run_hash_before_delete() -> None:
    adapter = ConfigurableCogneeMemory(
        ProjectionForgetResult(status=CapabilityStatus.OK, forgotten_ids=())
    )
    process = ProjectionOutboxProcess(SimpleNamespace(cognee_memory=adapter))

    with pytest.raises(OutboxProjectionError) as caught:
        asyncio.run(
            _dispatch(
                process,
                _cognee_forget_job(cleanup_run_id_sha256="not-a-sha256"),
            )
        )

    assert caught.value.diagnostic_code == "benchmark.cleanup_run_id_sha256_invalid"
    assert adapter.requests == []


@pytest.mark.parametrize("lane", ["vector", "graph", "cognee"])
def test_cleanup_delete_runs_after_active_projection_upsert(lane: str) -> None:
    async def run() -> list[str]:
        events: list[str] = []
        fence = CoordinatedFence(events)
        process, adapters = _process(lane, fence, events)
        upsert_task = asyncio.create_task(_dispatch(process, _job(lane)))
        await adapters.started.wait()

        async def cleanup_and_delete() -> None:
            await fence.begin_cleanup()
            await _dispatch(process, _job(lane, delete=True))

        cleanup_task = asyncio.create_task(cleanup_and_delete())
        await fence.cleanup_waiting.wait()
        assert "cleanup.commit" not in events
        adapters.release.set()
        await asyncio.gather(upsert_task, cleanup_task)
        return events

    events = asyncio.run(run())

    assert events == [
        f"{lane}.upsert.start",
        f"{lane}.upsert.finish",
        "cleanup.commit",
        f"{lane}.delete",
    ]


@pytest.mark.parametrize("lane", ["vector", "graph", "cognee"])
def test_claimed_job_deletes_when_cleanup_wins_fence(lane: str) -> None:
    async def run() -> list[str]:
        events: list[str] = []
        fence = CoordinatedFence(events)
        process, _adapters = _process(lane, fence, events)
        await fence.begin_cleanup()
        await _dispatch(process, _job(lane))
        return events

    events = asyncio.run(run())

    assert events == ["cleanup.commit", f"{lane}.delete"]


@pytest.mark.parametrize("lane", ["vector", "graph", "cognee"])
def test_space_change_during_fence_is_retryable_without_delete(lane: str) -> None:
    async def run() -> tuple[str, list[str]]:
        events: list[str] = []
        fence = CoordinatedFence(events)
        process, adapters = _process(lane, fence, events, moved=True)
        adapters.release.set()
        with pytest.raises(OutboxProjectionError) as caught:
            await _dispatch(process, _job(lane))
        return caught.value.diagnostic_code, events

    diagnostic_code, events = asyncio.run(run())

    assert diagnostic_code == "projection.space_changed_during_fence"
    assert events == []


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None


class FakeSession:
    def __init__(self, factory: "FakeSessionFactory") -> None:
        self.factory = factory
        self.closed = False

    def begin(self) -> FakeTransaction:
        return FakeTransaction()

    async def scalar(self, query):
        space_id = next(
            str(value)
            for value in query.compile().params.values()
            if str(value) in self.factory.states
        )
        locked = query._for_update_arg is not None  # noqa: SLF001
        self.factory.lookups.append((space_id, locked))
        if locked:
            self.factory.locked_lookup_count += 1
        else:
            self.factory.short_lookup_count += 1
            if self.factory.short_lookup_count >= 2:
                self.factory.two_short_lookups.set()
        registry = (
            self.factory.locked_states.get(space_id)
            if locked
            else self.factory.states.get(space_id)
        )
        if registry is None:
            return None
        return registry == ("active", "unsealed")

    async def close(self) -> None:
        self.closed = True


class FakeSessionFactory:
    def __init__(
        self,
        states: dict[str, tuple[str, str] | None],
        *,
        locked_states: dict[str, tuple[str, str] | None] | None = None,
    ) -> None:
        self.states = states
        self.locked_states = states if locked_states is None else locked_states
        self.sessions: list[FakeSession] = []
        self.lookups: list[tuple[str, bool]] = []
        self.short_lookup_count = 0
        self.locked_lookup_count = 0
        self.two_short_lookups = asyncio.Event()

    def __call__(self) -> FakeSession:
        session = FakeSession(self)
        self.sessions.append(session)
        return session


@pytest.mark.parametrize(
    ("registry", "allowed", "open_inside", "session_count"),
    [
        (None, True, 0, 1),
        (("active", "unsealed"), True, 1, 2),
        (("active", "sealed"), False, 0, 1),
        (("active", "pending"), False, 0, 1),
        (("active", "blocked"), False, 0, 1),
        (("cleanup_pending", "unsealed"), False, 0, 1),
    ],
)
def test_postgres_fence_decision_and_session_lifetime(
    registry: tuple[str, str] | None,
    allowed: bool,
    open_inside: int,
    session_count: int,
) -> None:
    async def run() -> tuple[bool, int, FakeSessionFactory]:
        factory = FakeSessionFactory({"space-1": registry})
        fence = PostgresProjectionFence(factory)  # type: ignore[arg-type]
        async with fence.hold("space-1") as permit:
            active_sessions = sum(not session.closed for session in factory.sessions)
        return permit.allow_upsert, active_sessions, factory

    allow_upsert, active_sessions, factory = asyncio.run(run())

    assert allow_upsert is allowed
    assert active_sessions == open_inside
    assert len(factory.sessions) == session_count
    assert all(session.closed for session in factory.sessions)


def test_projection_fence_rechecks_manifest_seal_under_shared_lock() -> None:
    async def run() -> tuple[bool, FakeSessionFactory]:
        factory = FakeSessionFactory(
            {"space-1": ("active", "unsealed")},
            locked_states={"space-1": ("active", "sealed")},
        )
        fence = PostgresProjectionFence(factory)  # type: ignore[arg-type]
        async with fence.hold("space-1") as permit:
            return permit.allow_upsert, factory

    allow_upsert, factory = asyncio.run(run())

    assert allow_upsert is False
    assert factory.lookups == [("space-1", False), ("space-1", True)]
    assert all(session.closed for session in factory.sessions)


def test_active_hold_semaphore_does_not_consume_waiting_or_nonbenchmark_sessions() -> None:
    async def run() -> tuple[int, int, int, bool]:
        factory = FakeSessionFactory(
            {
                "benchmark-space": ("active", "unsealed"),
                "regular-space": None,
            }
        )
        fence = PostgresProjectionFence(factory)  # type: ignore[arg-type]
        first_entered = asyncio.Event()
        first_release = asyncio.Event()
        second_entered = asyncio.Event()
        regular_entered = asyncio.Event()

        async def first_active() -> None:
            async with fence.hold("benchmark-space") as permit:
                assert permit.allow_upsert is True
                first_entered.set()
                await first_release.wait()

        async def second_active() -> None:
            async with fence.hold("benchmark-space") as permit:
                assert permit.allow_upsert is True
                second_entered.set()

        async def regular() -> None:
            async with fence.hold("regular-space") as permit:
                assert permit.allow_upsert is True
                regular_entered.set()

        first_task = asyncio.create_task(first_active())
        await first_entered.wait()
        second_task = asyncio.create_task(second_active())
        await factory.two_short_lookups.wait()

        locked_while_waiting = factory.locked_lookup_count
        open_while_waiting = sum(not session.closed for session in factory.sessions)
        regular_task = asyncio.create_task(regular())
        await regular_entered.wait()
        regular_bypassed = not second_entered.is_set()

        first_release.set()
        await asyncio.gather(first_task, second_task, regular_task)
        return (
            locked_while_waiting,
            open_while_waiting,
            factory.locked_lookup_count,
            regular_bypassed,
        )

    locked_while_waiting, open_while_waiting, final_locked, regular_bypassed = asyncio.run(run())

    assert locked_while_waiting == 1
    assert open_while_waiting == 1
    assert final_locked == 2
    assert regular_bypassed is True


def test_postgres_projection_fence_query_uses_shared_row_lock() -> None:
    sql = str(
        _projection_fence_query("space-1").compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "FOR SHARE" in sql
    assert "space-1" in sql

    assert "state = 'active'" in sql
    assert "projection_cleanup_state = 'unsealed'" in sql


def test_postgres_projection_state_query_is_unlocked() -> None:
    sql = str(
        _projection_state_query("space-1").compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "FOR SHARE" not in sql
    assert "state = 'active'" in sql
    assert "projection_cleanup_state = 'unsealed'" in sql
