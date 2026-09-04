"""Bounded PostgreSQL 18 proof that document listing indexes stay write-online."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
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
_DATABASE_PREFIX = "doc_idx_pg18"
_ROLLBACK_TIMEOUT_SECONDS = 2
_BUILDER_TIMEOUT_SECONDS = 20
_BUILDER_CLEANUP_TIMEOUT_SECONDS = 2
_CONNECTION_CLOSE_TIMEOUT_SECONDS = 2
_DATABASE_DROP_TIMEOUT_SECONDS = 5


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
            prefix=_DATABASE_PREFIX,
            asyncpg=asyncpg,
        )
    except ValueError:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")

    primary_error: BaseException | None = None
    try:
        await database.recreate()
        await _install_versioned_schema_through(database, "0051_")
        await _seed_populated_clone(database)
        report = await _build_indexes_with_writes(database)
        print(
            "document_listing_online_index_qualification=" + json.dumps(report, sort_keys=True),
            flush=True,
        )
    except BaseException as error:
        primary_error = error

    cleanup_errors = await _collect_cleanup_errors(
        (
            "qualification database drop",
            database.drop(),
            _DATABASE_DROP_TIMEOUT_SECONDS,
        ),
    )
    _raise_after_cleanup(primary_error, cleanup_errors)


async def _seed_populated_clone(database: PostgresTestDatabase) -> None:
    connection = None
    primary_error: BaseException | None = None
    try:
        connection = await database.connect()
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
    except BaseException as error:
        primary_error = error

    cleanup_errors = []
    if connection is not None:
        cleanup_errors = await _collect_cleanup_errors(
            ("seed connection close", connection.close(), _CONNECTION_CLOSE_TIMEOUT_SECONDS)
        )
    _raise_after_cleanup(primary_error, cleanup_errors)


async def _build_indexes_with_writes(database: PostgresTestDatabase) -> dict[str, object]:
    migration = next(
        item
        for item in _load_migrations()
        if item.migration_id == "0052_document_scope_listing_indexes"
    )
    statements = migration.statements()
    assert len(statements) == len(_INDEX_DEFINITIONS) == 3

    connections = []
    primary_error: BaseException | None = None
    report: dict[str, object] | None = None
    insert_latencies: list[float] = []
    started = perf_counter()
    try:
        blocker = await database.connect()
        connections.append(("blocker connection close", blocker))
        builder = await database.connect()
        connections.append(("builder connection close", builder))
        writer = await database.connect()
        connections.append(("writer connection close", writer))
        observer = await database.connect()
        connections.append(("observer connection close", observer))
        pre_row_count = await observer.fetchval("SELECT count(*) FROM memory_documents")
        for index_ordinal, statement in enumerate(statements):
            index_name = migration.recoverable_indexes()[index_ordinal]
            insert_latencies.extend(
                await _build_one_index_with_writes(
                    blocker,
                    builder,
                    writer,
                    observer,
                    statement,
                    index_name,
                    index_ordinal,
                )
            )

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
        report = {
            "concurrent_inserts": concurrent_inserts,
            "indexes": observed_indexes,
            "maximum_insert_latency_seconds": round(max(insert_latencies), 6),
            "post_row_count": post_row_count,
            "pre_row_count": pre_row_count,
            "wall_time_seconds": round(wall_time, 6),
        }
    except BaseException as error:
        primary_error = error

    cleanup_errors = await _collect_cleanup_errors(
        *(
            (label, connection.close(), _CONNECTION_CLOSE_TIMEOUT_SECONDS)
            for label, connection in connections
        )
    )
    _raise_after_cleanup(primary_error, cleanup_errors)
    assert report is not None
    return report


async def _build_one_index_with_writes(
    blocker,
    builder,
    writer,
    observer,
    statement: str,
    index_name: str,
    index_ordinal: int,
) -> list[float]:
    build: asyncio.Task | None = None
    primary_error: BaseException | None = None
    insert_latencies: list[float] = []
    try:
        await blocker.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
        await blocker.fetchval("SELECT count(*) FROM memory_documents")
        build = asyncio.create_task(builder.execute(statement))
        await _wait_for_old_snapshot(observer, builder.get_server_pid(), index_name)
        for insert_ordinal in range(_INSERTS_PER_INDEX):
            latency_started = perf_counter()
            await asyncio.wait_for(
                _insert_document(writer, index_ordinal, insert_ordinal), timeout=5
            )
            insert_latencies.append(perf_counter() - latency_started)
    except BaseException as error:
        primary_error = error

    cleanup_errors = await _collect_cleanup_errors(
        ("old-snapshot blocker rollback", blocker.execute("ROLLBACK"), _ROLLBACK_TIMEOUT_SECONDS)
    )
    if primary_error is not None or cleanup_errors:
        if build is not None:
            cleanup_errors.extend(await _cancel_and_settle_builder(build))
        _raise_after_cleanup(primary_error, cleanup_errors)

    assert build is not None
    try:
        await _await_task_bounded(build, _BUILDER_TIMEOUT_SECONDS, "online index builder")
    except BaseException as error:
        cleanup_errors = await _cancel_and_settle_builder(build)
        _raise_after_cleanup(error, cleanup_errors)
    return insert_latencies


async def _cancel_and_settle_builder(build: asyncio.Task) -> list[Exception]:
    if not build.done():
        build.cancel()
    try:
        await _await_task_bounded(
            build,
            _BUILDER_CLEANUP_TIMEOUT_SECONDS,
            "cancelled online index builder settlement",
            cancelled_is_success=True,
        )
    except BaseException as error:
        return [_contextual_cleanup_error("online index builder cleanup", error)]
    return []


async def _await_task_bounded(
    task: asyncio.Task,
    timeout: float,
    operation: str,
    *,
    cancelled_is_success: bool = False,
) -> None:
    done, _ = await asyncio.wait({task}, timeout=timeout)
    if not done:
        raise TimeoutError(f"{operation} timed out after {timeout} seconds")
    if task.cancelled() and cancelled_is_success:
        return
    task.result()


async def _run_bounded(awaitable, timeout: float, operation: str) -> None:
    task = asyncio.create_task(awaitable)
    try:
        await _await_task_bounded(task, timeout, operation)
    except BaseException:
        if not task.done():
            task.cancel()
            task.add_done_callback(_consume_task_result)
        raise


def _consume_task_result(task: asyncio.Task) -> None:
    with suppress(BaseException):
        task.result()


async def _collect_cleanup_errors(*operations) -> list[Exception]:
    async def capture(operation: str, awaitable, timeout: float) -> Exception | None:
        try:
            await _run_bounded(awaitable, timeout, operation)
        except BaseException as error:
            return _contextual_cleanup_error(operation, error)
        return None

    results = await asyncio.gather(*(capture(*operation) for operation in operations))
    return [error for error in results if error is not None]


def _contextual_cleanup_error(operation: str, error: BaseException) -> Exception:
    return RuntimeError(f"{operation} failed: {type(error).__name__}: {error}")


def _raise_after_cleanup(
    primary_error: BaseException | None, cleanup_errors: list[Exception]
) -> None:
    if primary_error is not None:
        for cleanup_error in cleanup_errors:
            primary_error.add_note(f"Cleanup failure: {cleanup_error}")
        raise primary_error.with_traceback(primary_error.__traceback__)
    if cleanup_errors:
        raise ExceptionGroup("qualification cleanup failed", cleanup_errors)


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


def test_qualification_database_name_fits_postgres_identifier_limit() -> None:
    database_name = f"{_DATABASE_PREFIX}_{'0' * 32}"

    assert len(database_name.encode("utf-8")) <= 63


def test_polling_failure_cancels_builder_and_preserves_primary_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Blocker:
        async def execute(self, statement: str) -> None:
            if statement == "ROLLBACK":
                await asyncio.Event().wait()

        async def fetchval(self, statement: str) -> int:
            return 20_000

    class Builder:
        task: asyncio.Task | None = None
        settled = False

        async def execute(self, statement: str) -> None:
            self.task = asyncio.current_task()
            try:
                await asyncio.Event().wait()
            finally:
                self.settled = True

        def get_server_pid(self) -> int:
            return 42

    async def fail_polling(observer, builder_pid: int, index_name: str) -> None:
        raise AssertionError("verifier failed")

    async def exercise() -> tuple[BaseException, float]:
        builder = Builder()
        started = perf_counter()
        try:
            await _build_one_index_with_writes(
                Blocker(), builder, object(), object(), "CREATE INDEX", "index_name", 0
            )
        except BaseException as error:
            assert builder.task is not None
            assert builder.task.done()
            assert builder.task.cancelled()
            assert builder.settled
            return error, perf_counter() - started
        raise AssertionError("qualification unexpectedly succeeded")

    monkeypatch.setattr(
        "test_document_listing_online_indexes_postgres18._wait_for_old_snapshot",
        fail_polling,
    )
    monkeypatch.setattr(
        "test_document_listing_online_indexes_postgres18._ROLLBACK_TIMEOUT_SECONDS", 0.01
    )
    monkeypatch.setattr(
        "test_document_listing_online_indexes_postgres18._BUILDER_CLEANUP_TIMEOUT_SECONDS",
        0.05,
    )

    error, elapsed = asyncio.run(exercise())

    assert isinstance(error, AssertionError)
    assert str(error) == "verifier failed"
    assert any(
        "old-snapshot blocker rollback failed: TimeoutError" in note
        for note in getattr(error, "__notes__", [])
    )
    assert elapsed < 0.5


def test_standalone_cleanup_failure_is_bounded_and_fails() -> None:
    async def never_finishes() -> None:
        await asyncio.Event().wait()

    async def exercise() -> tuple[BaseException, float]:
        started = perf_counter()
        errors = await _collect_cleanup_errors(
            ("qualification database drop", never_finishes(), 0.01)
        )
        try:
            _raise_after_cleanup(None, errors)
        except BaseException as error:
            return error, perf_counter() - started
        raise AssertionError("cleanup unexpectedly succeeded")

    error, elapsed = asyncio.run(exercise())

    assert isinstance(error, ExceptionGroup)
    assert "qualification cleanup failed" in str(error)
    assert len(error.exceptions) == 1
    assert "qualification database drop failed: TimeoutError" in str(error.exceptions[0])
    assert elapsed < 0.5
