"""Bounded PostgreSQL 18 proof that document listing indexes stay write-online."""

from __future__ import annotations

import asyncio
import json
import os
from time import perf_counter

import pytest
from infinity_context_adapters.postgres.migration_runner import _load_migrations
from postgres_test_database import PostgresTestDatabase
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through

_INDEX_DEFINITIONS = {
    "ix_memory_documents_scope_status_page": (
        "CREATE INDEX ix_memory_documents_scope_status_page ON public.memory_documents "
        "USING btree (space_id, memory_scope_id, status, updated_at DESC, id DESC)"
    ),
    "ix_memory_documents_scope_thread_status_page": (
        "CREATE INDEX ix_memory_documents_scope_thread_status_page "
        "ON public.memory_documents USING btree (space_id, memory_scope_id, thread_id, "
        "status, updated_at DESC, id DESC)"
    ),
    "ix_memory_documents_scope_thread_source_page": (
        "CREATE INDEX ix_memory_documents_scope_thread_source_page "
        "ON public.memory_documents USING btree (space_id, memory_scope_id, thread_id, "
        "source_external_id, status, updated_at DESC, id DESC)"
    ),
}
_SEED_ROWS = 20_000
_INSERTS_PER_INDEX = 3


def test_populated_document_listing_indexes_allow_concurrent_inserts() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(asyncio.wait_for(_qualify_online_indexes(database_url), timeout=60))


async def _qualify_online_indexes(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    try:
        database = PostgresTestDatabase.from_url(
            database_url,
            prefix="document_listing_online_indexes",
            asyncpg=asyncpg,
        )
    except ValueError:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")

    try:
        await database.recreate()
        await _install_versioned_schema_through(database, "0032_")
        await _seed_populated_clone(database)
        report = await _build_indexes_with_writes(database)
        print(
            "document_listing_online_index_qualification=" + json.dumps(report, sort_keys=True),
            flush=True,
        )
    finally:
        await database.drop()


async def _seed_populated_clone(database: PostgresTestDatabase) -> None:
    connection = await database.connect()
    try:
        version = int(await connection.fetchval("SHOW server_version_num"))
        assert 180000 <= version < 190000, (
            f"qualification requires PostgreSQL 18, observed server_version_num={version}"
        )
        await connection.execute(
            """
            INSERT INTO memory_documents (
                id, space_id, memory_scope_id, thread_id, title, source_type,
                source_external_id, content_hash, classification, status,
                created_at, updated_at
            )
            SELECT
                'seed-' || value,
                'space-' || (value % 8),
                'scope-' || (value % 32),
                CASE WHEN value % 5 = 0 THEN NULL ELSE 'thread-' || (value % 128) END,
                'Seed document ' || value,
                'qualification',
                'seed-source-' || value,
                'seed-hash-' || value,
                'internal',
                CASE WHEN value % 11 = 0 THEN 'deleted' ELSE 'active' END,
                clock_timestamp() - ((value % 1000) * interval '1 second'),
                clock_timestamp() - ((value % 1000) * interval '1 second')
            FROM generate_series(1, $1) AS value
            """,
            _SEED_ROWS,
        )
        await connection.execute("ANALYZE memory_documents")
    finally:
        await connection.close()


async def _build_indexes_with_writes(database: PostgresTestDatabase) -> dict[str, object]:
    migration = next(
        item
        for item in _load_migrations()
        if item.migration_id == "0033_document_scope_listing_indexes"
    )
    statements = migration.statements()
    assert len(statements) == len(_INDEX_DEFINITIONS) == 3

    blocker = await database.connect()
    builder = await database.connect()
    writer = await database.connect()
    observer = await database.connect()
    insert_latencies: list[float] = []
    started = perf_counter()
    try:
        pre_row_count = await observer.fetchval("SELECT count(*) FROM memory_documents")
        for index_ordinal, statement in enumerate(statements):
            index_name = migration.recoverable_indexes()[index_ordinal]
            await blocker.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
            await blocker.fetchval("SELECT count(*) FROM memory_documents")
            build = asyncio.create_task(builder.execute(statement))
            try:
                await _wait_for_old_snapshot(observer, builder.get_server_pid(), index_name)
                for insert_ordinal in range(_INSERTS_PER_INDEX):
                    latency_started = perf_counter()
                    await asyncio.wait_for(
                        _insert_document(writer, index_ordinal, insert_ordinal), timeout=5
                    )
                    insert_latencies.append(perf_counter() - latency_started)
            finally:
                await blocker.execute("ROLLBACK")
            await asyncio.wait_for(build, timeout=20)

        wall_time = perf_counter() - started
        post_row_count = await observer.fetchval("SELECT count(*) FROM memory_documents")
        index_rows = await observer.fetch(
            """
            SELECT index_class.relname AS index_name,
                   index_state.indisready,
                   index_state.indisvalid,
                   pg_get_indexdef(index_state.indexrelid) AS definition
            FROM pg_catalog.pg_index AS index_state
            JOIN pg_catalog.pg_class AS index_class
              ON index_class.oid = index_state.indexrelid
            JOIN pg_catalog.pg_namespace AS index_namespace
              ON index_namespace.oid = index_class.relnamespace
            WHERE index_namespace.nspname = 'public'
              AND index_class.relname = ANY($1::text[])
            ORDER BY index_class.relname
            """,
            list(_INDEX_DEFINITIONS),
        )
        observed_indexes = {
            row["index_name"]: {
                "indisready": row["indisready"],
                "indisvalid": row["indisvalid"],
                "definition": row["definition"],
            }
            for row in index_rows
        }
        assert observed_indexes == {
            name: {
                "indisready": True,
                "indisvalid": True,
                "definition": definition,
            }
            for name, definition in _INDEX_DEFINITIONS.items()
        }
        concurrent_inserts = len(insert_latencies)
        assert concurrent_inserts == len(statements) * _INSERTS_PER_INDEX
        assert post_row_count == pre_row_count + concurrent_inserts
        return {
            "concurrent_inserts": concurrent_inserts,
            "indexes": observed_indexes,
            "maximum_insert_latency_seconds": round(max(insert_latencies), 6),
            "post_row_count": post_row_count,
            "pre_row_count": pre_row_count,
            "wall_time_seconds": round(wall_time, 6),
        }
    finally:
        await asyncio.gather(
            blocker.close(),
            builder.close(),
            writer.close(),
            observer.close(),
            return_exceptions=True,
        )


async def _wait_for_old_snapshot(observer, builder_pid: int, index_name: str) -> None:
    deadline = perf_counter() + 10
    while perf_counter() < deadline:
        progress = await observer.fetchrow(
            """
            SELECT index_progress.phase, activity.query
            FROM pg_catalog.pg_stat_progress_create_index AS index_progress
            JOIN pg_catalog.pg_stat_activity AS activity
              ON activity.pid = index_progress.pid
            WHERE index_progress.pid = $1
              AND index_progress.relid = 'public.memory_documents'::regclass
            """,
            builder_pid,
        )
        if (
            progress is not None
            and progress["phase"] == "waiting for old snapshots"
            and "CREATE INDEX CONCURRENTLY" in progress["query"]
            and index_name in progress["query"]
        ):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"concurrent build for {index_name} did not wait for the qualification snapshot"
    )


async def _insert_document(writer, index_ordinal: int, insert_ordinal: int) -> None:
    suffix = f"{index_ordinal}-{insert_ordinal}"
    await writer.execute(
        """
        INSERT INTO memory_documents (
            id, space_id, memory_scope_id, thread_id, title, source_type,
            source_external_id, content_hash, classification, status,
            created_at, updated_at
        ) VALUES (
            $1, 'space-live', 'scope-live', 'thread-live', $2, 'qualification',
            $3, $4, 'internal', 'active', clock_timestamp(), clock_timestamp()
        )
        """,
        f"concurrent-{suffix}",
        f"Concurrent document {suffix}",
        f"concurrent-source-{suffix}",
        f"concurrent-hash-{suffix}",
    )
