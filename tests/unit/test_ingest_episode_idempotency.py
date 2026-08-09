import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from infinity_context_core.application import IngestEpisodeCommand, IngestEpisodeUseCase
from infinity_context_core.application.use_cases.ingest_episode import (
    episode_fingerprint,
    legacy_episode_fingerprint,
)
from infinity_context_core.domain.entities import (
    LifecycleStatus,
    MemoryEpisode,
    MemoryEpisodeId,
    MemoryScopeId,
    SpaceId,
    SpeakerRole,
    ThreadId,
    TrustLevel,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryInvariantError
from infinity_context_core.domain.idempotency import IdempotencyRecord
from infinity_context_core.ports.repositories import UpsertChunkResult

_NOW = datetime(2026, 8, 6, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize("cleanup_plan_state", [None, "recovery_blocked"])
def test_managed_episode_requires_sealed_plan_before_any_write(
    cleanup_plan_state: str | None,
) -> None:
    async def run() -> None:
        store = _Store()
        store.benchmark_run = (
            None
            if cleanup_plan_state is None
            else SimpleNamespace(
                state="active",
                projection_cleanup_state="unsealed",
                cleanup_plan_state=cleanup_plan_state,
                cleanup_plan_json=None,
                cleanup_plan_sha256=None,
            )
        )
        command = replace(
            _command(),
            space_id=SpaceId("benchmark-space-" + "a" * 48),
        )

        with pytest.raises(MemoryConflictError, match="episode admission is unsupported"):
            await _use_case(store).execute(command)

        assert store.episodes == {}
        assert store.chunks == {}
        assert store.outbox == []
        assert store.record is None

    asyncio.run(run())


@pytest.mark.parametrize("corruption", ["scope", "source"])
def test_managed_episode_rejects_unplanned_authority_before_any_write(
    corruption: str,
) -> None:
    async def run() -> None:
        store = _Store()
        space_id = "benchmark-space-" + "a" * 48
        scope_ref = "managed-corpus"
        command = replace(_command(), space_id=SpaceId(space_id))
        allowed_source = command.source_external_id if corruption == "scope" else "planned-source"
        store.benchmark_run = SimpleNamespace(
            state="active",
            projection_cleanup_state="unsealed",
            cleanup_plan_state="sealed",
            cleanup_plan_json={
                "corpora": [
                    {
                        "memory_scope_external_ref_sha256": sha256(scope_ref.encode()).hexdigest(),
                        "ordered_source_external_id_sha256": [
                            sha256(allowed_source.encode()).hexdigest()
                        ],
                        "expected_ingest_unit_count": 1,
                    }
                ]
            },
            cleanup_plan_sha256="1" * 64,
        )
        store.memory_scope = SimpleNamespace(
            id=MemoryScopeId("scope_1"),
            space_id=SpaceId(space_id),
            external_ref="foreign-corpus" if corruption == "scope" else scope_ref,
            status=LifecycleStatus.ACTIVE,
        )
        store.thread = SimpleNamespace(
            id=ThreadId("thread_1"),
            memory_scope_id=MemoryScopeId("scope_1"),
            external_ref="foreign-corpus" if corruption == "scope" else scope_ref,
            status=LifecycleStatus.ACTIVE,
        )

        with pytest.raises(MemoryConflictError, match="episode admission is unsupported"):
            await _use_case(store).execute(command)

        assert store.episodes == {}
        assert store.chunks == {}
        assert store.outbox == []
        assert store.record is None

    asyncio.run(run())


def test_concurrent_same_request_returns_one_canonical_episode() -> None:
    asyncio.run(_run_concurrent_same_request())


def test_concurrent_different_request_conflicts_after_commit_race() -> None:
    async def run() -> None:
        store = _Store(concurrent_initial_reads=2)
        use_case = _use_case(store)
        results = await asyncio.gather(
            use_case.execute(_command()),
            use_case.execute(replace(_command(), speaker=SpeakerRole.INTERVIEWER)),
            return_exceptions=True,
        )

        assert sum(not isinstance(result, Exception) for result in results) == 1
        conflicts = [result for result in results if isinstance(result, MemoryConflictError)]
        assert len(conflicts) == 1
        assert len(store.episodes) == 1
        assert len(store.outbox) == 1
        assert store.rollback_calls >= 1

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["add", "upsert", "commit"])
def test_write_conflict_at_any_persistence_stage_recovers(stage: str) -> None:
    async def run() -> None:
        store = _Store()
        use_case = _use_case(store)
        created = await use_case.execute(_command())
        assert created.episode is not None
        store.hide_next_find = True
        store.conflict_stage = stage

        replay = await use_case.execute(_command())

        assert replay.episode is not None
        assert replay.episode.id == created.episode.id
        assert replay.stored_chunks == 0
        assert replay.duplicate_chunks == 1
        assert store.rollback_calls >= 1

    asyncio.run(run())


def test_replay_rejects_cross_scope_episode_tamper() -> None:
    async def run() -> None:
        store = _Store()
        use_case = _use_case(store)
        command = _command()

        created = await use_case.execute(command)
        assert created.episode is not None
        canonical_id = str(created.episode.id)
        store.episodes[canonical_id] = MemoryEpisode.create(
            episode_id=MemoryEpisodeId(canonical_id),
            space_id=command.space_id,
            memory_scope_id=MemoryScopeId("scope_other"),
            thread_id=command.thread_id,
            source_type=command.source_type,
            source_external_id=command.source_external_id,
            text=command.text,
            speaker=command.speaker,
            trust_level=command.trust_level,
            occurred_at=_NOW,
            now=_NOW,
            metadata=command.metadata,
        )

        with pytest.raises(MemoryInvariantError, match="unrelated episode"):
            await use_case.execute(command)

    asyncio.run(run())


def test_replay_rejects_source_episode_tamper() -> None:
    async def run() -> None:
        store = _Store()
        use_case = _use_case(store)
        command = _command()

        created = await use_case.execute(command)
        assert created.episode is not None
        canonical_id = str(created.episode.id)
        store.episodes[canonical_id] = MemoryEpisode.create(
            episode_id=MemoryEpisodeId(canonical_id),
            space_id=command.space_id,
            memory_scope_id=command.memory_scope_id,
            thread_id=command.thread_id,
            source_type="different_source",
            source_external_id=command.source_external_id,
            text=command.text,
            speaker=command.speaker,
            trust_level=command.trust_level,
            occurred_at=_NOW,
            now=_NOW,
            metadata=command.metadata,
        )

        with pytest.raises(MemoryInvariantError, match="unrelated episode"):
            await use_case.execute(command)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    (
        ("text", "Tampered canonical episode text."),
        ("speaker", SpeakerRole.INTERVIEWER),
        ("trust_level", TrustLevel.HIGH),
        ("metadata", {"tampered": True}),
        ("occurred_at", _NOW - timedelta(minutes=1)),
    ),
)
def test_canonical_replay_rejects_stored_semantic_tamper(
    field: str,
    tampered_value: object,
) -> None:
    async def run() -> None:
        store = _Store()
        use_case = _use_case(store)
        command = _command()
        created = await use_case.execute(command)
        assert created.episode is not None
        canonical_id = str(created.episode.id)
        store.episodes[canonical_id] = replace(
            created.episode,
            **{field: tampered_value},
        )

        with pytest.raises(MemoryInvariantError, match="semantics are corrupted"):
            await use_case.execute(command)

    asyncio.run(run())


def test_replay_conflicts_when_canonical_request_fields_change() -> None:
    async def run() -> None:
        store = _Store()
        use_case = _use_case(store)
        command = _command()
        await use_case.execute(command)

        variants = (
            replace(command, occurred_at=_NOW + timedelta(seconds=1)),
            replace(command, speaker=SpeakerRole.INTERVIEWER),
            replace(command, trust_level=TrustLevel.HIGH),
            replace(command, metadata={"nested": {"b": 2}, "final_answer": False}),
            replace(command, metadata={"nested": {"a": 1}, "final_answer": True}),
        )
        for changed in variants:
            with pytest.raises(MemoryConflictError):
                await use_case.execute(changed)

    asyncio.run(run())


def test_episode_fingerprint_is_stable_for_metadata_order_and_timezone() -> None:
    reordered = replace(
        _command(),
        occurred_at=datetime(2026, 8, 6, 12, 30, tzinfo=UTC),
        metadata={"nested": {"b": 2, "a": 1}, "labels": ["x", "y"]},
    )
    equivalent = replace(
        reordered,
        occurred_at=datetime.fromisoformat("2026-08-06T15:30:00+03:00"),
        metadata={"labels": ["x", "y"], "nested": {"a": 1, "b": 2}},
    )
    assert episode_fingerprint(reordered) == episode_fingerprint(equivalent)


def test_first_non_durable_request_creates_no_canonical_state() -> None:
    async def run() -> None:
        store = _Store()
        result = await _use_case(store).execute(
            replace(_command(), metadata={"final_answer": True})
        )

        assert result.durability == "ignore"
        assert result.episode is None
        assert store.record is None
        assert store.episodes == {}
        assert store.outbox == []

    asyncio.run(run())


def test_episode_fingerprint_has_no_delimiter_ambiguity() -> None:
    left = replace(
        _command(),
        source_type="source",
        source_external_id="external:part",
    )
    right = replace(
        _command(),
        source_type="source:external",
        source_external_id="part",
    )

    assert episode_fingerprint(left) != episode_fingerprint(right)


def test_replay_rejects_missing_or_divergent_chunk_projection() -> None:
    async def run() -> None:
        missing_store = _Store()
        missing_use_case = _use_case(missing_store)
        await missing_use_case.execute(_command())
        missing_store.chunks.clear()
        with pytest.raises(MemoryInvariantError, match="projection is incomplete"):
            await missing_use_case.execute(_command())

        divergent_store = _Store()
        divergent_use_case = _use_case(divergent_store)
        await divergent_use_case.execute(_command())
        chunk_id, chunk = next(iter(divergent_store.chunks.items()))
        divergent_store.chunks[chunk_id] = replace(chunk, normalized_text="tampered")
        with pytest.raises(MemoryInvariantError, match="projection is divergent"):
            await divergent_use_case.execute(_command())

    asyncio.run(run())


def test_legacy_fingerprint_replays_only_the_same_semantic_request() -> None:
    async def run() -> None:
        store = _Store()
        use_case = _use_case(store)
        command = _command()
        created = await use_case.execute(command)
        assert created.episode is not None
        assert store.record is not None
        store.record = replace(
            store.record,
            fingerprint=legacy_episode_fingerprint(command),
        )

        replay = await use_case.execute(command)
        assert replay.episode is not None
        assert replay.episode.id == created.episode.id
        assert replay.stored_chunks == 0
        assert replay.duplicate_chunks == 1

        with pytest.raises(MemoryConflictError, match="Legacy idempotency request differs"):
            await use_case.execute(replace(command, metadata={"changed": True}))

    asyncio.run(run())


def test_legacy_fingerprint_replays_future_occurred_at_after_historical_clamp() -> None:
    async def run() -> None:
        store = _Store()
        use_case = _use_case(store)
        command = replace(_command(), occurred_at=_NOW + timedelta(days=30))
        created = await use_case.execute(command)
        assert created.episode is not None
        assert created.episode.occurred_at == created.episode.created_at
        assert store.record is not None
        store.record = replace(
            store.record,
            fingerprint=legacy_episode_fingerprint(command),
        )

        replay = await use_case.execute(command)
        assert replay.episode is not None
        assert replay.episode.id == created.episode.id

        with pytest.raises(MemoryConflictError, match="Legacy idempotency request differs"):
            await use_case.execute(replace(command, occurred_at=_NOW - timedelta(days=1)))

    asyncio.run(run())


async def _run_concurrent_same_request() -> None:
    store = _Store(concurrent_initial_reads=2)
    classifier = _Classifier()
    use_case = _use_case(store, classifier=classifier, auto_suggestions_enabled=True)
    first, second = await asyncio.gather(
        use_case.execute(_command()),
        use_case.execute(_command()),
    )

    assert first.episode is not None
    assert second.episode is not None
    assert first.episode.id == second.episode.id
    assert len(store.episodes) == 1
    assert store.record is not None
    assert store.record.result_id == str(first.episode.id)
    assert sorted((first.stored_chunks, second.stored_chunks)) == [0, 1]
    assert sorted((first.duplicate_chunks, second.duplicate_chunks)) == [0, 1]
    assert len(store.outbox) == 1
    assert classifier.calls == 2
    assert store.rollback_calls >= 1
    assert store.open_count == 3


def _command() -> IngestEpisodeCommand:
    return IngestEpisodeCommand(
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("scope_1"),
        thread_id=ThreadId("thread_1"),
        source_type="system_audio",
        source_external_id="episode-source-1",
        text="Canonical concurrent episode evidence.",
        occurred_at=_NOW,
        speaker=SpeakerRole.USER,
        trust_level=TrustLevel.MEDIUM,
        language="en",
        metadata={"labels": ["x", "y"], "nested": {"a": 1, "b": 2}},
        idempotency_key="episode-key-1",
    )


def _use_case(
    store: "_Store",
    *,
    classifier: "_Classifier | None" = None,
    auto_suggestions_enabled: bool = False,
) -> IngestEpisodeUseCase:
    return IngestEpisodeUseCase(
        uow_factory=_Factory(store),
        clock=_Clock(),
        ids=_Ids(),
        classifier=classifier,
        auto_suggestions_enabled=auto_suggestions_enabled,
    )


class _Clock:
    def now(self) -> datetime:
        return _NOW


class _Ids:
    def __init__(self) -> None:
        self._next = 0

    def new_id(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}_{self._next}"


class _Classifier:
    def __init__(self) -> None:
        self.calls = 0

    async def classify(self, **_kwargs) -> tuple[()]:
        self.calls += 1
        return ()


class _Store:
    def __init__(self, *, concurrent_initial_reads: int = 0) -> None:
        self.episodes: dict[str, MemoryEpisode] = {}
        self.chunks: dict[str, object] = {}
        self.record: IdempotencyRecord | None = None
        self.outbox: list[object] = []
        self.open_count = 0
        self.rollback_calls = 0
        self.hide_next_find = False
        self.conflict_stage: str | None = None
        self._commit_lock = asyncio.Lock()
        self._read_target = concurrent_initial_reads
        self._read_count = 0
        self._read_barrier = asyncio.Event()
        self.benchmark_run = None
        self.memory_scope = None
        self.thread = None

    async def synchronize_initial_read(self) -> None:
        if self._read_target == 0:
            return
        self._read_count += 1
        if self._read_count >= self._read_target:
            self._read_barrier.set()
        await self._read_barrier.wait()


class _Factory:
    def __init__(self, store: _Store) -> None:
        self._store = store

    def __call__(self) -> "_Uow":
        self._store.open_count += 1
        return _Uow(
            self._store,
            synchronize_find=self._store.open_count <= self._store._read_target,
        )


class _Uow:
    def __init__(self, store: _Store, *, synchronize_find: bool) -> None:
        self._store = store
        self._synchronize_find = synchronize_find
        self.episodes = _Episodes(self)
        self.chunks = _Chunks(self)
        self.idempotency = _Idempotency(self)
        self.outbox = _Outbox(self)
        self.suggestions = _Suggestions()
        self.benchmark_runs = _BenchmarkRuns(store)
        self.scope = _Scope(store)
        self._staged_episode: MemoryEpisode | None = None
        self._staged_record: IdempotencyRecord | None = None
        self._staged_outbox: list[object] = []
        self._staged_chunks: list[object] = []
        self._committed = False

    async def __aenter__(self) -> "_Uow":
        return self

    async def __aexit__(self, exc_type, *_args) -> None:
        if exc_type is not None:
            await self.rollback()
            return
        if not self._committed:
            self._staged_episode = None
            self._staged_record = None
            self._staged_outbox.clear()
            self._staged_chunks.clear()

    async def commit(self) -> None:
        async with self._store._commit_lock:
            if self._store.conflict_stage == "commit":
                self._store.conflict_stage = None
                raise MemoryConflictError("Injected commit conflict")
            if self._store.record is not None:
                raise MemoryConflictError("Concurrent idempotency insert")
            assert self._staged_episode is not None
            assert self._staged_record is not None
            self._store.episodes[str(self._staged_episode.id)] = self._staged_episode
            self._store.chunks.update({str(chunk.id): chunk for chunk in self._staged_chunks})
            self._store.record = self._staged_record
            self._store.outbox.extend(self._staged_outbox)
            self._committed = True

    async def rollback(self) -> None:
        self._store.rollback_calls += 1
        self._staged_episode = None
        self._staged_record = None
        self._staged_outbox.clear()
        self._staged_chunks.clear()


class _BenchmarkRuns:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def get_by_space_id(self, _space_id: str):
        return self._store.benchmark_run


class _Scope:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def get_memory_scope(self, _memory_scope_id: str):
        return self._store.memory_scope

    async def get_thread(self, _thread_id: str):
        return self._store.thread


class _Episodes:
    def __init__(self, uow: _Uow) -> None:
        self._uow = uow

    async def create(self, episode: MemoryEpisode) -> MemoryEpisode:
        if self._uow._store.conflict_stage == "add":
            self._uow._store.conflict_stage = None
            raise MemoryConflictError("Injected add conflict")
        self._uow._staged_episode = episode
        return episode

    async def get_by_id(self, episode_id: str) -> MemoryEpisode | None:
        return self._uow._store.episodes.get(episode_id)

    async def list_for_scope(self, **_kwargs) -> list[MemoryEpisode]:
        episodes = list(self._uow._store.episodes.values())
        if self._uow._staged_episode is not None:
            episodes.append(self._uow._staged_episode)
        return episodes


class _Chunks:
    def __init__(self, uow: _Uow) -> None:
        self._uow = uow

    async def upsert(self, chunk) -> UpsertChunkResult:
        if self._uow._store.conflict_stage == "upsert":
            self._uow._store.conflict_stage = None
            raise MemoryConflictError("Injected upsert conflict")
        self._uow._staged_chunks.append(chunk)
        return UpsertChunkResult(chunk_id=str(chunk.id), duplicate=False)

    async def list_for_episode(self, episode_id: str, *, limit: int = 10000):
        chunks = (*self._uow._store.chunks.values(), *self._uow._staged_chunks)
        return [chunk for chunk in chunks if str(chunk.episode_id) == episode_id][:limit]


class _Idempotency:
    def __init__(self, uow: _Uow) -> None:
        self._uow = uow

    async def find(self, **_kwargs) -> IdempotencyRecord | None:
        snapshot = self._uow._store.record
        if self._uow._store.hide_next_find:
            self._uow._store.hide_next_find = False
            snapshot = None
        if self._uow._synchronize_find:
            await self._uow._store.synchronize_initial_read()
        return snapshot

    async def save(self, record: IdempotencyRecord) -> None:
        self._uow._staged_record = record


class _Outbox:
    def __init__(self, uow: _Uow) -> None:
        self._uow = uow

    async def enqueue(self, event: object) -> None:
        self._uow._staged_outbox.append(event)


class _Suggestions:
    async def create(self, suggestion):
        return suggestion
