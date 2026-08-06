import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from infinity_context_core.application import IngestEpisodeCommand, IngestEpisodeUseCase
from infinity_context_core.application.use_cases.ingest_episode import (
    episode_fingerprint,
    legacy_episode_fingerprint,
)
from infinity_context_core.domain.entities import (
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
        self._staged_episode: MemoryEpisode | None = None
        self._staged_record: IdempotencyRecord | None = None
        self._staged_outbox: list[object] = []
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
            self._store.record = self._staged_record
            self._store.outbox.extend(self._staged_outbox)
            self._committed = True

    async def rollback(self) -> None:
        self._store.rollback_calls += 1
        self._staged_episode = None
        self._staged_record = None
        self._staged_outbox.clear()


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


class _Chunks:
    def __init__(self, uow: _Uow) -> None:
        self._uow = uow

    async def upsert(self, chunk) -> UpsertChunkResult:
        if self._uow._store.conflict_stage == "upsert":
            self._uow._store.conflict_stage = None
            raise MemoryConflictError("Injected upsert conflict")
        return UpsertChunkResult(chunk_id=str(chunk.id), duplicate=False)


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
