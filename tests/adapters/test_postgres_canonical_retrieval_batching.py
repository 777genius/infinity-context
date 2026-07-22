"""Scalar-equivalence and bind-safety tests for canonical retrieval batching."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from math import ceil

from infinity_context_adapters.postgres.canonical_retrieval_batching import (
    _MAX_SQL_BINDS,
    _active_anchor_key_conditions,
    _anchor_scope_conditions,
    _chunk_conditions,
    _keyword_batch_statement,
    _keyword_fragments,
)
from infinity_context_adapters.postgres.models import Base, MemoryAnchorRow, MemoryChunkRow
from infinity_context_adapters.postgres.repositories import (
    PostgresAnchorRepository,
    PostgresChunkRepository,
)
from infinity_context_adapters.postgres.repository_helpers import _terms
from infinity_context_core.ports.repositories import (
    ActiveAnchorKey,
    AnchorScopeQuery,
    ChunkKeywordSearch,
)
from sqlalchemy import and_, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


def test_batches_are_exactly_scalar_equivalent_for_order_duplicates_and_edges() -> None:
    asyncio.run(_assert_batches_are_exactly_scalar_equivalent())


async def _assert_batches_are_exactly_scalar_equivalent() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(_anchor_rows(now) + _chunk_rows(now))
        await session.commit()
        anchors = PostgresAnchorRepository(session)
        chunks = PostgresChunkRepository(session)

        anchor_ids = ("a2", "missing", "", "a2", "a1")
        scalar_ids = [
            anchor
            for anchor_id in anchor_ids
            if (anchor := await anchors.get_by_id(anchor_id)) is not None
        ]
        assert await anchors.get_by_ids(anchor_ids) == scalar_ids
        assert [str(anchor.id) for anchor in scalar_ids] == ["a2", "", "a2", "a1"]

        keys = (
            ActiveAnchorKey("space-a", "scope-a", "person", "ada"),
            ActiveAnchorKey("space-a", "scope-a", "person", "missing"),
            ActiveAnchorKey("space-a", "scope-a", "person", "ada"),
            ActiveAnchorKey("space-b", "scope-a", "person", "ada"),
        )
        scalar_keys = [
            await anchors.find_active_by_key(
                space_id=item.space_id,
                memory_scope_id=item.memory_scope_id,
                kind=item.kind,
                normalized_key=item.normalized_key,
            )
            for item in keys
        ]
        assert await anchors.find_active_by_keys(keys) == scalar_keys
        assert [str(item.id) if item else None for item in scalar_keys] == [
            "a2",
            None,
            "a2",
            "a4",
        ]

        scopes = (
            AnchorScopeQuery("space-a", "scope-a", None, "active", 2),
            AnchorScopeQuery("space-a", "scope-a", None, None, -1),
            AnchorScopeQuery("space-a", "scope-a", None, None, 0),
            AnchorScopeQuery("space-a", "scope-a", "person", "active", 2),
            AnchorScopeQuery("space-a", "scope-a", None, "active", 2),
        )
        scalar_scopes = [
            await anchors.list_for_scope(
                space_id=item.space_id,
                memory_scope_id=item.memory_scope_id,
                kind=item.kind,
                status=item.status,
                limit=item.limit,
            )
            for item in scopes
        ]
        assert await anchors.list_for_scopes(scopes) == scalar_scopes
        assert [str(item.id) for item in scalar_scopes[0]] == ["a2", "a1"]
        assert [str(item.id) for item in scalar_scopes[1]] == ["a3", "a2", "a1", ""]
        assert scalar_scopes[2] == []

        searches = (
            ChunkKeywordSearch("space-a", ("scope-rank",), None, "banana orange", 2),
            ChunkKeywordSearch("space-a", ("scope-leak",), None, "banana", 10),
            ChunkKeywordSearch("space-a", ("scope-leak",), None, "", 10),
            ChunkKeywordSearch("space-a", ("scope-visible",), "thread-a", "banana", 10),
            ChunkKeywordSearch("space-a", ("scope-visible",), None, "banana", 10),
            ChunkKeywordSearch("space-a", ("scope-ties",), None, "banana", 10),
            ChunkKeywordSearch("space-a", ("scope-ties",), None, "", 10),
            ChunkKeywordSearch("space-a", ("scope-rank",), None, "banana orange", 2),
            ChunkKeywordSearch("space-a", ("missing",), None, "banana", 10),
            ChunkKeywordSearch("space-a", ("scope-rank",), None, "banana", 0),
            ChunkKeywordSearch("space-a", ("scope-rank",), None, "banana", -1),
        )
        scalar_searches = [
            await chunks.keyword_search(
                space_id=item.space_id,
                memory_scope_ids=item.memory_scope_ids,
                thread_id=item.thread_id,
                query=item.query,
                limit=item.limit,
            )
            for item in searches
        ]
        batched_searches = await chunks.keyword_search_many(searches)
        assert batched_searches == scalar_searches
        assert _ids(batched_searches[0]) == ["exact-both", "approx-second-term"]
        assert "typo-only" not in _ids(batched_searches[1])
        assert "typo-only" in _ids(batched_searches[2])
        assert _ids(batched_searches[3]) == ["global", "thread-a"]
        assert _ids(batched_searches[4]) == ["global", "thread-a", "thread-b"]
        assert "restricted" not in _ids(batched_searches[4])
        assert "deleted" not in _ids(batched_searches[4])
        assert _ids(batched_searches[5]) == ["tie-a", "tie-b"]
        assert _ids(batched_searches[6]) == ["tie-b", "tie-a"]
        assert batched_searches[8:] == [[], [], []]
    await engine.dispose()


def test_batch_queries_are_grouped_and_empty_outer_inputs_execute_no_sql() -> None:
    asyncio.run(_assert_batch_query_counts())


async def _assert_batch_query_counts() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    statements = 0

    def count_statement(*_args: object) -> None:
        nonlocal statements
        statements += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count_statement)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(_anchor_rows(now) + _chunk_rows(now))
        await session.commit()
        anchors = PostgresAnchorRepository(session)
        chunks = PostgresChunkRepository(session)
        statements = 0

        assert await anchors.get_by_ids(()) == []
        assert await anchors.find_active_by_keys(()) == []
        assert await anchors.list_for_scopes(()) == []
        assert await chunks.keyword_search_many(()) == []
        assert statements == 0

        await anchors.get_by_ids(("a1", "a2", "missing", "a1"))
        assert statements == 1
        statements = 0
        await anchors.find_active_by_keys(
            (
                ActiveAnchorKey("space-a", "scope-a", "person", "ada"),
                ActiveAnchorKey("space-a", "scope-a", "person", "grace"),
            )
        )
        assert statements == 1
        statements = 0
        await anchors.list_for_scopes(
            (
                AnchorScopeQuery("space-a", "scope-a", None, None, 3),
                AnchorScopeQuery("space-a", "scope-a", "person", "active", 2),
            )
        )
        assert statements == 1
        statements = 0
        await chunks.keyword_search_many(
            (
                ChunkKeywordSearch("space-a", ("scope-rank",), None, "banana orange", 2),
                ChunkKeywordSearch("space-a", ("scope-leak",), None, "banana", 2),
                ChunkKeywordSearch("space-a", ("scope-leak",), None, "", 2),
            )
        )
        assert statements == 1
    await engine.dispose()


def test_eight_oversized_scope_queries_bound_actual_sql_binds_and_query_count() -> None:
    asyncio.run(_assert_oversized_scope_queries_are_bind_bounded())


async def _assert_oversized_scope_queries_are_bind_bounded() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    bind_counts: list[int] = []

    def record_bind_count(
        _connection: object,
        _cursor: object,
        _statement: object,
        parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        bind_counts.append(len(parameters))  # type: ignore[arg-type]

    event.listen(engine.sync_engine, "before_cursor_execute", record_bind_count)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    async with AsyncSession(engine) as session:
        session.add_all(
            (
                _chunk_row(
                    now,
                    item_id="oversized-exact",
                    scope="scope-0-0",
                    text="banana orange",
                    sequence=9,
                    minute=1,
                ),
                _chunk_row(
                    now,
                    item_id="oversized-approx",
                    scope="scope-0-8999",
                    text="banena orange",
                    sequence=0,
                    minute=0,
                ),
            )
        )
        await session.commit()
    bind_counts.clear()
    requests = tuple(
        ChunkKeywordSearch(
            space_id="space-a",
            memory_scope_ids=tuple(f"scope-{request_index}-{index}" for index in range(9_000)),
            thread_id=None,
            query="banana orange",
            limit=5,
        )
        for request_index in range(8)
    )
    async with AsyncSession(engine) as session:
        results = await PostgresChunkRepository(session).keyword_search_many(requests)

    assert _ids(results[0]) == ["oversized-exact", "oversized-approx"]
    assert results[1:] == [[] for _ in requests[1:]]

    term_binds = 1 + 2 * sum(len(term.variants) + 1 for term in _terms("banana orange"))
    scopes_per_statement = _MAX_SQL_BINDS - 3 - term_binds
    assert len(bind_counts) == 8 * ceil(9_000 / scopes_per_statement) == 88
    assert max(bind_counts) == _MAX_SQL_BINDS
    assert all(count <= _MAX_SQL_BINDS for count in bind_counts)
    await engine.dispose()


def test_postgres_and_sqlite_batch_shapes_retain_scalar_predicates() -> None:
    request = ChunkKeywordSearch(
        "space-a",
        ("scope-a", "scope-b"),
        "thread-a",
        "banana orange",
        5,
    )
    fragments = _keyword_fragments(0, request, _terms(request.query))
    sql = _postgres_sql(_keyword_batch_statement(fragments, (request,)))
    for predicate in (
        "memory_chunks.space_id",
        "memory_chunks.memory_scope_id IN",
        "memory_chunks.status",
        "memory_chunks.classification !=",
        "memory_chunks.thread_id",
        "memory_chunks.thread_id IS NULL",
        "memory_chunks.normalized_text",
        "canonical_keyword_candidates",
    ):
        assert predicate in sql

    key_sql = _postgres_sql(
        select(MemoryAnchorRow).where(
            and_(
                *_active_anchor_key_conditions(
                    ActiveAnchorKey("space-a", "scope-a", "person", "ada")
                )
            )
        )
    )
    for predicate in (
        "memory_anchors.space_id",
        "memory_anchors.memory_scope_id",
        "memory_anchors.kind",
        "memory_anchors.normalized_key",
        "memory_anchors.status",
    ):
        assert predicate in key_sql

    scope_sql = _postgres_sql(
        select(MemoryAnchorRow).where(
            and_(*_anchor_scope_conditions(AnchorScopeQuery("s", "m", None, None, 5)))
        )
    )
    scope_where = scope_sql.split("WHERE", maxsplit=1)[1]
    assert "memory_anchors.space_id" in scope_where
    assert "memory_anchors.memory_scope_id" in scope_where
    assert "memory_anchors.kind" not in scope_where
    assert "memory_anchors.status" not in scope_where

    chunk_sql = _postgres_sql(
        select(MemoryChunkRow).where(and_(*_chunk_conditions(request, ("m",))))
    )
    assert "memory_chunks.thread_id IS NULL" in chunk_sql


def _postgres_sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _ids(items) -> list[str]:
    return [str(item.id) for item in items]


def _anchor_rows(now: datetime) -> list[MemoryAnchorRow]:
    values = [
        ("", "space-a", "scope-a", "person", "blank", "active", 0),
        ("a1", "space-a", "scope-a", "person", "grace", "active", 1),
        ("a2", "space-a", "scope-a", "person", "ada", "active", 1),
        ("a3", "space-a", "scope-a", "project", "atlas", "deleted", 2),
        ("a4", "space-b", "scope-a", "person", "ada", "active", 3),
    ]
    return [
        MemoryAnchorRow(
            id=item_id,
            space_id=space,
            memory_scope_id=scope,
            kind=kind,
            normalized_key=key,
            label=key.title(),
            aliases_json=[],
            description=None,
            status=status,
            confidence="medium",
            evidence_refs_json=[],
            observed_at=None,
            valid_from=None,
            valid_to=None,
            metadata_json={},
            created_at=now,
            updated_at=now + timedelta(minutes=minute),
        )
        for item_id, space, scope, kind, key, status, minute in values
    ]


def _chunk_rows(now: datetime) -> list[MemoryChunkRow]:
    values = [
        ("exact-both", "scope-rank", None, "banana orange", "active", "internal", 5, 0),
        (
            "approx-second-term",
            "scope-rank",
            None,
            "banena orange",
            "active",
            "internal",
            0,
            1,
        ),
        ("typo-only", "scope-leak", None, "banena", "active", "internal", 0, 2),
        ("banana-only", "scope-leak", None, "banana", "active", "internal", 0, 3),
        ("global", "scope-visible", None, "banana", "active", "internal", 0, 4),
        ("thread-a", "scope-visible", "thread-a", "banana", "active", "internal", 0, 5),
        ("thread-b", "scope-visible", "thread-b", "banana", "active", "internal", 0, 6),
        ("restricted", "scope-visible", None, "banana", "active", "restricted", 0, 7),
        ("deleted", "scope-visible", None, "banana", "deleted", "internal", 0, 8),
        ("tie-a", "scope-ties", None, "banana", "active", "internal", 0, 9),
        ("tie-b", "scope-ties", None, "banana", "active", "internal", 0, 9),
    ]
    return [
        _chunk_row(
            now,
            item_id=item_id,
            scope=scope,
            thread=thread,
            text=text,
            status=status,
            classification=classification,
            sequence=sequence,
            minute=minute,
        )
        for item_id, scope, thread, text, status, classification, sequence, minute in values
    ]


def _chunk_row(
    now: datetime,
    *,
    item_id: str,
    scope: str,
    text: str,
    sequence: int,
    minute: int,
    thread: str | None = None,
    status: str = "active",
    classification: str = "internal",
) -> MemoryChunkRow:
    return MemoryChunkRow(
        id=item_id,
        space_id="space-a",
        memory_scope_id=scope,
        thread_id=thread,
        document_id=None,
        episode_id=None,
        source_type="manual",
        source_external_id=item_id,
        source_hash=f"hash-{item_id}",
        kind="document_section",
        text=text,
        normalized_text=text,
        status=status,
        sequence=sequence,
        char_start=0,
        char_end=len(text),
        token_estimate=2,
        classification=classification,
        created_at=now + timedelta(minutes=minute),
        updated_at=now + timedelta(minutes=minute),
        metadata_json={},
    )
