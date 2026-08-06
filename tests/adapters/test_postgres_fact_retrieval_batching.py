"""Bounded query and hydration tests for canonical fact retrieval batching."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import infinity_context_adapters.postgres.fact_repositories as fact_repositories
import pytest
from infinity_context_adapters.postgres.fact_repositories import (
    _MAX_FACT_HYDRATION_BINDS,
    PostgresFactRepository,
)
from infinity_context_adapters.postgres.models import (
    Base,
    MemoryFactRow,
    MemorySourceRefRow,
)
from infinity_context_core.ports.repositories import (
    ActiveFactSearch,
    FactRepositoryPort,
)
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


def test_find_active_many_ranks_queries_and_batches_hydration() -> None:
    asyncio.run(_assert_find_active_many_ranks_queries_and_batches_hydration())


async def _assert_find_active_many_ranks_queries_and_batches_hydration() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 7, 30, tzinfo=UTC)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            (
                _fact_row(
                    "pottery",
                    "Melanie signed up for a pottery class and enjoys ceramics.",
                    now=now,
                    tags=("creative",),
                ),
                _fact_row(
                    "camping",
                    "Melanie went camping with her family and kids.",
                    now=now - timedelta(minutes=1),
                    tags=("outdoors",),
                ),
                _fact_row(
                    "noise",
                    "Caroline discussed a different decision at work.",
                    now=now - timedelta(minutes=2),
                    tags=("work",),
                ),
            )
        )
        session.add_all(
            (
                _source_ref("pottery", "locomo:test:D5:4:turn"),
                _source_ref("camping", "locomo:test:D9:1:turn"),
            )
        )
        await session.commit()
        repository = PostgresFactRepository(session, now=now)
        searches = (
            _search("pottery ceramics", limit=2),
            _search("camping family", limit=2),
            _search("", limit=2),
            _search("pottery", limit=0),
        )
        select_count = 0

        def count_selects(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            nonlocal select_count
            if statement.lstrip().upper().startswith("SELECT"):
                select_count += 1

        event.listen(engine.sync_engine, "before_cursor_execute", count_selects)
        try:
            results = await repository.find_active_many(searches)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count_selects)

        assert [[str(fact.id) for fact in group] for group in results] == [
            ["pottery"],
            ["camping"],
            ["pottery", "camping"],
            [],
        ]
        assert results[0][0].source_refs[0].source_id == "locomo:test:D5:4:turn"
        assert results[1][0].source_refs[0].source_id == "locomo:test:D9:1:turn"
        assert select_count == 3
    await engine.dispose()


def test_find_active_many_preserves_scalar_results_and_candidate_windows() -> None:
    asyncio.run(_assert_find_active_many_preserves_scalar_results_and_candidate_windows())


async def _assert_find_active_many_preserves_scalar_results_and_candidate_windows() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 7, 30, tzinfo=UTC)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            _fact_row(
                f"fact-{index}",
                "oldmarker only in the old row" if index == 249 else f"ordinary row {index}",
                now=now - timedelta(minutes=index),
                tags=("allowed",),
            )
            for index in range(250)
        )
        session.add(
            _fact_row(
                "thread-category",
                "needle in the matching category",
                now=now,
                tags=("allowed", "preferred"),
                thread_id="thread-a",
                category="profile",
            )
        )
        await session.commit()
        repository = PostgresFactRepository(session, now=now)
        searches = (
            _search("oldmarker", limit=1),
            _search("", limit=120),
            ActiveFactSearch(
                space_id="space-a",
                memory_scope_ids=("scope-a",),
                thread_id="thread-a",
                query="needle",
                limit=2,
                category="profile",
                tags_any=("preferred",),
                tags_none=("blocked",),
            ),
        )
        scalar = [
            await repository.find_active(
                space_id=search.space_id,
                memory_scope_ids=search.memory_scope_ids,
                thread_id=search.thread_id,
                query=search.query,
                limit=search.limit,
                category=search.category,
                tags_any=search.tags_any,
                tags_all=search.tags_all,
                tags_none=search.tags_none,
            )
            for search in searches
        ]
        batch = await repository.find_active_many(searches)

        assert batch == scalar
        assert batch[0] == []
        assert len(batch[1]) == 120
        assert [str(fact.id) for fact in batch[2]] == ["thread-category"]
    await engine.dispose()


def test_find_active_many_bounds_oversized_hydration_in_binds() -> None:
    asyncio.run(_assert_find_active_many_bounds_oversized_hydration_in_binds())


def test_legacy_candidate_search_uses_as_of_before_ranking() -> None:
    asyncio.run(_assert_legacy_candidate_search_uses_as_of_before_ranking())


async def _assert_legacy_candidate_search_uses_as_of_before_ranking() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 8, 10, tzinfo=UTC)
    boundary = datetime(2026, 8, 5, tzinfo=UTC)
    predecessor = _fact_row("predecessor", "database engine", now=now, tags=())
    predecessor.status = "superseded"
    predecessor.temporal_kind = "state"
    predecessor.observed_at = datetime(2026, 7, 1, tzinfo=UTC)
    predecessor.valid_from = datetime(2026, 7, 1, tzinfo=UTC)
    predecessor.valid_to = boundary
    successor = _fact_row("successor", "database engine", now=now, tags=())
    successor.temporal_kind = "state"
    successor.observed_at = boundary
    successor.valid_from = boundary

    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all((predecessor, successor))
        await session.commit()
        repository = PostgresFactRepository(session, now=now)

        before, after = await repository.find_active_many(
            (
                _search_as_of(datetime(2026, 8, 1, tzinfo=UTC)),
                _search_as_of(datetime(2026, 8, 6, tzinfo=UTC)),
            )
        )

    assert [str(fact.id) for fact in before] == ["predecessor"]
    assert [str(fact.id) for fact in after] == ["successor"]
    await engine.dispose()


async def _assert_find_active_many_bounds_oversized_hydration_in_binds() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 7, 30, tzinfo=UTC)
    fact_hydration_binds: list[int] = []
    ref_hydration_binds: list[int] = []

    def record_hydration_binds(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        bind_count = len(parameters)  # type: ignore[arg-type]
        if "WHERE memory_facts.id IN" in statement:
            fact_hydration_binds.append(bind_count)
        if "WHERE memory_source_refs.fact_id IN" in statement:
            ref_hydration_binds.append(bind_count)

    event.listen(engine.sync_engine, "before_cursor_execute", record_hydration_binds)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            _fact_row(
                f"oversized-{index:04d}",
                f"fact {index}",
                now=now - timedelta(microseconds=index),
                tags=(),
            )
            for index in range(_MAX_FACT_HYDRATION_BINDS + 105)
        )
        await session.commit()
        fact_hydration_binds.clear()
        ref_hydration_binds.clear()

        result = await PostgresFactRepository(session, now=now).find_active_many(
            (_search("", limit=_MAX_FACT_HYDRATION_BINDS + 105),)
        )

    assert len(result[0]) == _MAX_FACT_HYDRATION_BINDS + 105
    assert fact_hydration_binds == [_MAX_FACT_HYDRATION_BINDS, 105]
    assert ref_hydration_binds == [_MAX_FACT_HYDRATION_BINDS, 105]
    await engine.dispose()


@pytest.mark.parametrize(
    "mutation_values",
    [
        {"space_id": "space-other"},
        {"memory_scope_id": "scope-other"},
        {"status": "deleted"},
        {"classification": "restricted"},
        {"thread_id": "thread-b"},
        {"category": "category-other"},
        {"tags_json": ["blocked"]},
        {"expires_at": datetime(2026, 7, 29, tzinfo=UTC)},
    ],
)
def test_find_active_many_rechecks_all_visibility_after_hydration(
    monkeypatch: pytest.MonkeyPatch,
    mutation_values: dict[str, object],
) -> None:
    asyncio.run(
        _assert_find_active_many_rechecks_all_visibility_after_hydration(
            monkeypatch,
            mutation_values,
        )
    )


async def _assert_find_active_many_rechecks_all_visibility_after_hydration(
    monkeypatch: pytest.MonkeyPatch,
    mutation_values: dict[str, object],
) -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 7, 30, tzinfo=UTC)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(
            _fact_row(
                "visibility-candidate",
                "visible needle",
                now=now,
                tags=("allowed",),
                thread_id="thread-a",
                category="category-a",
            )
        )
        await session.commit()
        original_hydrator = fact_repositories._hydrate_fact_rows_by_ids
        did_mutate = False

        async def hydrate_after_visibility_change(
            hydrate_session: AsyncSession,
            fact_ids: tuple[str, ...],
        ):
            nonlocal did_mutate
            if not did_mutate:
                did_mutate = True
                await hydrate_session.execute(
                    update(MemoryFactRow)
                    .where(MemoryFactRow.id == "visibility-candidate")
                    .values(**mutation_values)
                    .execution_options(synchronize_session=False)
                )
                await hydrate_session.flush()
            return await original_hydrator(hydrate_session, fact_ids)

        monkeypatch.setattr(
            fact_repositories,
            "_hydrate_fact_rows_by_ids",
            hydrate_after_visibility_change,
        )
        result = await PostgresFactRepository(session, now=now).find_active_many(
            (
                ActiveFactSearch(
                    space_id="space-a",
                    memory_scope_ids=("scope-a",),
                    thread_id="thread-a",
                    query="needle",
                    limit=1,
                    category="category-a",
                    tags_all=("allowed",),
                    tags_none=("blocked",),
                ),
            )
        )

    assert did_mutate
    assert result == [[]]
    await engine.dispose()


def test_scalar_fact_port_does_not_inherit_optional_batch_callable() -> None:
    class ScalarOnlyFactRepository(FactRepositoryPort):
        pass

    repository = ScalarOnlyFactRepository()

    assert not callable(getattr(repository, "find_active_many", None))


def _search(query: str, *, limit: int) -> ActiveFactSearch:
    return ActiveFactSearch(
        space_id="space-a",
        memory_scope_ids=("scope-a",),
        thread_id=None,
        query=query,
        limit=limit,
    )


def _search_as_of(reference_time: datetime) -> ActiveFactSearch:
    return ActiveFactSearch(
        space_id="space-a",
        memory_scope_ids=("scope-a",),
        thread_id=None,
        query="database",
        limit=5,
        reference_time=reference_time,
        temporal_mode="as_of",
    )


def _fact_row(
    fact_id: str,
    text: str,
    *,
    now: datetime,
    tags: tuple[str, ...],
    thread_id: str | None = None,
    category: str | None = None,
) -> MemoryFactRow:
    return MemoryFactRow(
        id=fact_id,
        space_id="space-a",
        memory_scope_id="scope-a",
        thread_id=thread_id,
        kind="note",
        text=text,
        status="active",
        confidence="high",
        trust_level="high",
        classification="internal",
        category=category,
        tags_json=list(tags),
        ttl_policy=None,
        expires_at=None,
        temporal_kind="state",
        observed_at=now,
        valid_from=now,
        temporal_basis="migrated_legacy",
        temporal_precision="unknown",
        version=1,
        created_at=now,
        updated_at=now,
    )


def _source_ref(fact_id: str, source_id: str) -> MemorySourceRefRow:
    return MemorySourceRefRow(
        fact_id=fact_id,
        fact_version=1,
        source_type="locomo_turn",
        source_id=source_id,
        chunk_id=None,
        char_start=None,
        char_end=None,
        quote_preview=None,
        page_number=None,
        time_start_ms=None,
        time_end_ms=None,
        bbox_json=None,
    )
