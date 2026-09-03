"""Fail-closed contracts for online document listing index migration."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres import migration_runner

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _ROOT
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
    / "0052_document_scope_listing_indexes.sql"
)
_RUNBOOK = _ROOT / "docs/document-listing-index-rollout.md"


class _LockEngine:
    def __init__(self, connection: object) -> None:
        self.dialect = SimpleNamespace(name="postgresql")
        self.connection = connection

    def connect(self) -> object:
        return self.connection


class _LockConnection:
    def __init__(self) -> None:
        self.invalidated = False
        self.closed = False
        self.returned_alive = False
        self.isolation_level: str | None = None

    async def __aenter__(self) -> _LockConnection:
        return self

    async def __aexit__(self, *args: object) -> None:
        self.returned_alive = not self.invalidated

    async def execution_options(self, *, isolation_level: str) -> _LockConnection:
        self.isolation_level = isolation_level
        return self

    async def invalidate(self) -> None:
        self.invalidated = True

    async def close(self) -> None:
        self.closed = True


class _Result:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self._rows = rows

    def all(self) -> tuple[tuple[object, ...], ...]:
        return self._rows


class _OnlineConnection:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self.rows = rows
        self.statements: list[str] = []

    async def __aenter__(self) -> _OnlineConnection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execution_options(self, *, isolation_level: str) -> _OnlineConnection:
        assert isolation_level == "AUTOCOMMIT"
        return self

    async def exec_driver_sql(self, statement: str) -> _Result:
        self.statements.append(" ".join(statement.split()))
        if "FROM pg_catalog.pg_index" in statement:
            return _Result(self.rows)
        return _Result(())


class _OnlineEngine:
    def __init__(self, connection: _OnlineConnection) -> None:
        self.connection = connection

    def connect(self) -> _OnlineConnection:
        return self.connection


def test_document_listing_migration_is_explicit_nontransactional_and_split() -> None:
    migration = next(
        item
        for item in migration_runner._load_migrations()
        if item.migration_id == "0052_document_scope_listing_indexes"
    )

    assert migration.transactional is False
    assert len(migration.statements()) == 3
    assert all("CREATE INDEX CONCURRENTLY IF NOT EXISTS" in item for item in migration.statements())
    assert migration.recoverable_indexes() == (
        "ix_memory_documents_scope_status_page",
        "ix_memory_documents_scope_thread_status_page",
        "ix_memory_documents_scope_thread_source_page",
    )


def test_pr57_history_through_0051_has_exact_appended_0052_sequence_pending() -> None:
    migrations = migration_runner._load_migrations()
    migration_ids = tuple(migration.migration_id for migration in migrations)
    pr57_migrations = migrations[:-8]
    history = {migration.migration_id: migration.checksum for migration in pr57_migrations}
    document_index_migrations = tuple(
        migration.migration_id
        for migration in migrations
        if migration.migration_id.endswith("_document_scope_listing_indexes")
    )

    assert migration_ids[-9:] == (
        "0051_locator_profile_acl_search_path_hardening",
        "0052_document_scope_listing_indexes",
        "0052_reconciliation_outbox_binding_index",
        "0053_retrieval_default_lifecycle",
        "0054_locator_profile_exact_delete_generation",
        "0055_generic_vector_rebuild_operations",
        "0056_fact_outbox_receipt_trigger_scope",
        "0057_unmanaged_document_trigger_scope",
        "0058_suggestion_server_thread_scope",
    )
    assert migrations[-1].migration_id == "0058_suggestion_server_thread_scope"
    assert document_index_migrations == ("0052_document_scope_listing_indexes",)
    migration_runner._validate_history(migrations, history)
    assert migration_runner._first_pending_out_of_transaction(migrations, history) == len(
        pr57_migrations
    )


@pytest.mark.parametrize(
    "sql",
    [
        "-- infinity-context: no-transaction",
        "-- infinity-context: no-transaction\n-- infinity-context: statement-break",
    ],
)
def test_empty_nontransactional_migration_fails_closed(sql: str) -> None:
    migration = migration_runner._Migration(
        migration_id="9999_empty",
        checksum="0" * 64,
        sql=sql,
        transactional=False,
    )

    with pytest.raises(RuntimeError, match="is empty"):
        migration.statements()


@pytest.mark.parametrize(
    ("directives", "message"),
    [
        (
            "-- infinity-context: recover-index duplicated\n"
            "-- infinity-context: recover-index duplicated",
            "Duplicate recoverable index",
        ),
        (
            "-- infinity-context: recover-index invalid-name",
            "Invalid recoverable index",
        ),
    ],
)
def test_recoverable_index_directives_fail_closed(
    directives: str,
    message: str,
) -> None:
    migration = migration_runner._Migration(
        migration_id="9999_invalid",
        checksum="0" * 64,
        sql=directives,
        transactional=False,
    )

    with pytest.raises(RuntimeError, match=message):
        migration.recoverable_indexes()


@pytest.mark.parametrize(
    (
        "table_schema",
        "table_name",
        "access_method",
        "unique",
        "predicate",
        "key_expressions",
        "include_expressions",
    ),
    [
        (
            "public",
            "attacker_documents",
            "btree",
            False,
            None,
            ("space_id", "memory_scope_id", "status", "updated_at DESC", "id DESC"),
            (),
        ),
        (
            "public",
            "memory_documents",
            "btree",
            False,
            None,
            ("space_id", "memory_scope_id", "status", "id DESC", "updated_at DESC"),
            (),
        ),
        (
            "public",
            "memory_documents",
            "btree",
            False,
            None,
            ("tenant_id", "memory_scope_id", "status", "updated_at DESC", "id DESC"),
            (),
        ),
        (
            "public",
            "memory_documents",
            "btree",
            False,
            None,
            ("space_id", "memory_scope_id", "lower(status)", "updated_at DESC", "id DESC"),
            (),
        ),
        (
            "public",
            "memory_documents",
            "btree",
            False,
            None,
            ("space_id", "memory_scope_id", "status", "updated_at", "id DESC"),
            (),
        ),
        (
            "public",
            "memory_documents",
            "hash",
            False,
            None,
            ("space_id", "memory_scope_id", "status", "updated_at DESC", "id DESC"),
            (),
        ),
        (
            "public",
            "memory_documents",
            "btree",
            True,
            None,
            ("space_id", "memory_scope_id", "status", "updated_at DESC", "id DESC"),
            (),
        ),
        (
            "public",
            "memory_documents",
            "btree",
            False,
            "(status IS NOT NULL)",
            ("space_id", "memory_scope_id", "status", "updated_at DESC", "id DESC"),
            (),
        ),
        (
            "public",
            "memory_documents",
            "btree",
            False,
            None,
            ("space_id", "memory_scope_id", "status", "updated_at DESC", "id DESC"),
            ("source_external_id",),
        ),
    ],
)
def test_valid_wrong_recoverable_index_definition_fails_without_drop(
    table_schema: str,
    table_name: str,
    access_method: str,
    unique: bool,
    predicate: str | None,
    key_expressions: tuple[str, ...],
    include_expressions: tuple[str, ...],
) -> None:
    migration = next(
        item
        for item in migration_runner._load_migrations()
        if item.migration_id == "0052_document_scope_listing_indexes"
    )
    rows = (
        (
            "ix_memory_documents_scope_status_page",
            True,
            table_schema,
            table_name,
            access_method,
            unique,
            predicate,
            key_expressions,
            tuple(3 if expression.endswith(" DESC") else 0 for expression in key_expressions),
            include_expressions,
        ),
    )
    connection = _OnlineConnection(rows)

    with pytest.raises(RuntimeError, match="valid index with an unexpected definition"):
        asyncio.run(
            migration_runner._execute_nontransactional(
                _OnlineEngine(connection),  # type: ignore[arg-type]
                migration,
            )
        )

    assert not any("DROP INDEX" in statement for statement in connection.statements)
    assert not any("CREATE INDEX" in statement for statement in connection.statements)


def test_existing_valid_document_listing_indexes_pass_preflight() -> None:
    migration = next(
        item
        for item in migration_runner._load_migrations()
        if item.migration_id == "0052_document_scope_listing_indexes"
    )
    specs = migration_runner._RECOVERABLE_INDEX_SPECS[migration.migration_id]
    rows = tuple(
        (
            spec.name,
            True,
            "public",
            spec.table_name,
            spec.access_method,
            spec.unique,
            spec.predicate,
            tuple(expression.removesuffix(" DESC") for expression in spec.key_expressions),
            tuple(3 if expression.endswith(" DESC") else 0 for expression in spec.key_expressions),
            spec.include_expressions,
        )
        for spec in specs
    )
    connection = _OnlineConnection(rows)

    asyncio.run(
        migration_runner._execute_nontransactional(
            _OnlineEngine(connection),  # type: ignore[arg-type]
            migration,
        )
    )

    assert not any("DROP INDEX" in statement for statement in connection.statements)
    assert sum("CREATE INDEX" in statement for statement in connection.statements) == 3


@pytest.mark.parametrize(
    ("key_expressions", "key_options", "expected"),
    [
        (("space_id", "updated_at"), (0, 3), ("space_id", "updated_at DESC")),
        (("space_id",), (2,), ("space_id NULLS FIRST",)),
        (("updated_at",), (1,), ("updated_at DESC NULLS LAST",)),
    ],
)
def test_index_states_preserve_key_direction_and_null_ordering(
    key_expressions: tuple[str, ...],
    key_options: tuple[int, ...],
    expected: tuple[str, ...],
) -> None:
    rows = (
        (
            "ix_memory_documents_scope_status_page",
            True,
            "public",
            "memory_documents",
            "btree",
            False,
            None,
            key_expressions,
            key_options,
            (),
        ),
    )
    connection = _OnlineConnection(rows)
    specs = (migration_runner._RECOVERABLE_INDEX_SPECS["0052_document_scope_listing_indexes"][0],)

    states = asyncio.run(
        migration_runner._index_states(connection, specs)  # type: ignore[arg-type]
    )

    assert states["ix_memory_documents_scope_status_page"].key_expressions == expected


@pytest.mark.parametrize(
    ("key_expressions", "key_options", "message"),
    [
        (("space_id",), (), "expressions and options are misaligned"),
        (("space_id",), (4,), "unknown ordering options"),
    ],
)
def test_index_states_fail_closed_for_unrepresentable_key_options(
    key_expressions: tuple[str, ...],
    key_options: tuple[int, ...],
    message: str,
) -> None:
    rows = (
        (
            "ix_memory_documents_scope_status_page",
            True,
            "public",
            "memory_documents",
            "btree",
            False,
            None,
            key_expressions,
            key_options,
            (),
        ),
    )
    connection = _OnlineConnection(rows)
    specs = (migration_runner._RECOVERABLE_INDEX_SPECS["0052_document_scope_listing_indexes"][0],)

    with pytest.raises(RuntimeError, match=message):
        asyncio.run(
            migration_runner._index_states(connection, specs)  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("invalidation_fails", [False, True])
def test_main_upgrade_preserves_application_error_when_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    invalidation_fails: bool,
) -> None:
    migration = migration_runner._Migration("0001_test", "a" * 64, "SELECT 1")

    class Connection(_LockConnection):
        def __init__(self) -> None:
            super().__init__()
            self.scalar_calls = 0

        async def scalar(self, statement: object, parameters: object) -> bool:
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return True
            raise OSError("unlock connection loss")

        async def invalidate(self) -> None:
            self.invalidated = True
            if invalidation_fails:
                raise OSError("invalidation connection loss")

        async def close(self) -> None:
            self.closed = True
            raise OSError("close connection loss")

    class Engine(_LockEngine):
        def begin(self) -> Connection:
            return self.connection  # type: ignore[return-value]

    async def no_op(*_args: object, **_kwargs: object) -> None:
        return None

    async def empty_history(_connection: object) -> dict[str, str]:
        return {}

    async def no_legacy(_connection: object) -> bool:
        return False

    async def fail_migration(*_args: object, **_kwargs: object) -> tuple[str, ...]:
        raise LookupError("original migration failure")

    monkeypatch.setattr(migration_runner, "_load_migrations", lambda: (migration,))
    monkeypatch.setattr(migration_runner, "_ensure_history_table", no_op)
    monkeypatch.setattr(migration_runner, "_load_history", empty_history)
    monkeypatch.setattr(migration_runner, "_has_unversioned_schema", no_legacy)
    monkeypatch.setattr(migration_runner, "_apply_transactional_pending", fail_migration)
    connection = Connection()

    with pytest.raises(LookupError, match="original migration failure"):
        asyncio.run(
            migration_runner.upgrade_schema(Engine(connection))  # type: ignore[arg-type]
        )

    assert connection.invalidated is True
    assert connection.closed is True


def test_online_runner_uses_session_lock_autocommit_and_invalid_index_recovery() -> None:
    upgrade_source = inspect.getsource(migration_runner.upgrade_schema)
    release_source = inspect.getsource(migration_runner._release_advisory_lock)
    online_source = inspect.getsource(migration_runner._execute_nontransactional)
    catalog_source = inspect.getsource(migration_runner._index_states)

    assert "_acquire_advisory_lock" in upgrade_source
    assert upgrade_source.index("try:") < upgrade_source.index("await _acquire_advisory_lock")
    assert 'isolation_level="AUTOCOMMIT"' in upgrade_source
    assert "pg_advisory_xact_lock" not in upgrade_source
    assert "_release_advisory_lock" in upgrade_source
    assert "pg_advisory_unlock" in release_source
    assert "pg_try_advisory_lock" in inspect.getsource(migration_runner._acquire_advisory_lock)
    assert 'isolation_level="AUTOCOMMIT"' in online_source
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in online_source
    assert online_source.count("_index_states") == 2
    assert online_source.count("_validate_valid_index_definitions") == 2
    assert "Online PostgreSQL migration left an invalid or missing index" in online_source
    assert "pg_catalog.pg_am" in catalog_source
    assert "indisunique" in catalog_source
    assert "indoption::int2[]" in catalog_source
    assert "WITH ORDINALITY" in catalog_source
    assert "pg_catalog.pg_get_expr" in catalog_source
    assert "indnkeyatts + 1" in catalog_source


def test_advisory_lock_wait_polls_without_one_long_running_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        def __init__(self) -> None:
            self.results = iter((False, False, True))
            self.calls: list[tuple[object, object]] = []

        async def scalar(self, statement: object, parameters: object) -> bool:
            self.calls.append((statement, parameters))
            return next(self.results)

    connection = Connection()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(migration_runner.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(migration_runner, "monotonic", lambda: 1.0)

    asyncio.run(migration_runner._acquire_advisory_lock(connection))  # type: ignore[arg-type]

    assert len(connection.calls) == 3
    assert all("pg_try_advisory_lock" in str(call[0]) for call in connection.calls)
    assert sleeps == [0.1, 0.1]


def test_advisory_lock_wait_has_a_hard_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        def __init__(self) -> None:
            self.calls = 0

        async def scalar(self, statement: object, parameters: object) -> bool:
            self.calls += 1
            return False

    connection = Connection()
    ticks = iter((10.0, 70.0))
    monkeypatch.setattr(migration_runner, "monotonic", lambda: next(ticks))

    with pytest.raises(TimeoutError, match="schema migration advisory lock"):
        asyncio.run(
            migration_runner._acquire_advisory_lock(connection)  # type: ignore[arg-type]
        )
    assert connection.calls == 0


def test_expired_deadline_after_failed_attempt_makes_no_extra_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        def __init__(self) -> None:
            self.calls = 0

        async def scalar(self, statement: object, parameters: object) -> bool:
            self.calls += 1
            return False

    connection = Connection()
    ticks = iter((0.0, 0.0, 61.0))
    monkeypatch.setattr(migration_runner, "monotonic", lambda: next(ticks))

    with pytest.raises(TimeoutError, match="schema migration advisory lock"):
        asyncio.run(
            migration_runner._acquire_advisory_lock(connection)  # type: ignore[arg-type]
        )

    assert connection.calls == 1


def test_slow_scalar_is_cancelled_by_the_whole_acquisition_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        def __init__(self) -> None:
            self.cancelled = False
            self.calls = 0

        async def scalar(self, statement: object, parameters: object) -> bool:
            self.calls += 1
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return True

    connection = Connection()
    monkeypatch.setattr(migration_runner, "_ADVISORY_LOCK_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(TimeoutError, match="schema migration advisory lock"):
        asyncio.run(
            migration_runner._acquire_advisory_lock(connection)  # type: ignore[arg-type]
        )

    assert connection.calls == 1
    assert connection.cancelled is True


def test_external_cancel_during_ambiguous_acquisition_discards_physical_connection() -> None:
    class Connection(_LockConnection):
        def __init__(self) -> None:
            super().__init__()
            self.query_started = asyncio.Event()
            self.postgres_may_hold_lock = False

        async def scalar(self, statement: object, parameters: object) -> bool:
            self.postgres_may_hold_lock = True
            self.query_started.set()
            await asyncio.Event().wait()
            return True

    async def scenario() -> Connection:
        connection = Connection()
        task = asyncio.create_task(
            migration_runner.upgrade_schema(_LockEngine(connection))  # type: ignore[arg-type]
        )
        await connection.query_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return connection

    connection = asyncio.run(scenario())

    assert connection.postgres_may_hold_lock is True
    assert connection.isolation_level == "AUTOCOMMIT"
    assert connection.invalidated is True
    assert connection.returned_alive is False


def test_ambiguous_scalar_driver_error_discards_physical_connection() -> None:
    class Connection(_LockConnection):
        async def scalar(self, statement: object, parameters: object) -> bool:
            raise RuntimeError("driver lost the scalar result")

    connection = Connection()

    with pytest.raises(RuntimeError, match="driver lost"):
        asyncio.run(
            migration_runner.upgrade_schema(_LockEngine(connection))  # type: ignore[arg-type]
        )

    assert connection.invalidated is True
    assert connection.returned_alive is False


def test_slow_scalar_timeout_discards_physical_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection(_LockConnection):
        async def scalar(self, statement: object, parameters: object) -> bool:
            await asyncio.Event().wait()
            return True

    connection = Connection()
    monkeypatch.setattr(migration_runner, "_ADVISORY_LOCK_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(TimeoutError, match="schema migration advisory lock"):
        asyncio.run(
            migration_runner.upgrade_schema(_LockEngine(connection))  # type: ignore[arg-type]
        )

    assert connection.invalidated is True
    assert connection.returned_alive is False


def test_unlock_success_reuses_connection_and_ambiguous_failure_invalidates_it() -> None:
    class Connection(_LockConnection):
        def __init__(self, result: bool) -> None:
            super().__init__()
            self.result = result
            self.queries: list[str] = []

        async def scalar(self, statement: object, parameters: object) -> bool:
            self.queries.append(str(statement))
            return self.result

    released = Connection(True)
    asyncio.run(migration_runner._release_advisory_lock(released))  # type: ignore[arg-type]
    assert released.invalidated is False
    assert released.queries == ["SELECT pg_advisory_unlock(:lock_id)"]

    ambiguous = Connection(False)
    with pytest.raises(RuntimeError, match="was not held"):
        asyncio.run(
            migration_runner._release_advisory_lock(ambiguous)  # type: ignore[arg-type]
        )
    assert ambiguous.invalidated is True
    assert ambiguous.closed is True


def test_unlock_error_survives_best_effort_discard_failures() -> None:
    class Connection(_LockConnection):
        async def scalar(self, statement: object, parameters: object) -> bool:
            raise OSError("unlock connection loss")

        async def invalidate(self) -> None:
            self.invalidated = True
            raise OSError("invalidation connection loss")

        async def close(self) -> None:
            self.closed = True
            raise OSError("close connection loss")

    connection = Connection()

    with pytest.raises(OSError, match="unlock connection loss"):
        asyncio.run(
            migration_runner._release_advisory_lock(connection)  # type: ignore[arg-type]
        )

    assert connection.invalidated is True
    assert connection.closed is True


def test_cancelled_unlock_finishes_invalidation_before_propagating_cancel() -> None:
    class Connection(_LockConnection):
        def __init__(self) -> None:
            super().__init__()
            self.query_started = asyncio.Event()
            self.invalidation_finished = asyncio.Event()

        async def scalar(self, statement: object, parameters: object) -> bool:
            self.query_started.set()
            await asyncio.Event().wait()
            return True

        async def invalidate(self) -> None:
            await asyncio.sleep(0)
            self.invalidated = True
            self.invalidation_finished.set()

    async def scenario() -> Connection:
        connection = Connection()
        task = asyncio.create_task(
            migration_runner._release_advisory_lock(connection)  # type: ignore[arg-type]
        )
        await connection.query_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert connection.invalidation_finished.is_set()
        return connection

    assert asyncio.run(scenario()).invalidated is True


def test_document_listing_index_sql_and_runbook_preserve_online_recovery_contract() -> None:
    sql = _MIGRATION.read_text(encoding="utf-8")
    runbook = _RUNBOOK.read_text(encoding="utf-8").lower()

    assert sql.startswith("-- infinity-context: no-transaction")
    assert sql.count("-- infinity-context: statement-break") == 2
    assert sql.count("-- infinity-context: recover-index ") == 3
    assert sql.count("CREATE INDEX CONCURRENTLY IF NOT EXISTS") == 3
    assert "indisvalid" in runbook
    assert "invalid" in runbook
    assert "retry" in runbook
    assert "lock" in runbook
    assert "60 seconds total" in runbook
    assert "no lock query after that deadline" in runbook
    assert "discards its physical connection" in runbook
