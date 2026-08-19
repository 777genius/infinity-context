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
    / "0033_document_scope_listing_indexes.sql"
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


def test_document_listing_migration_is_explicit_nontransactional_and_split() -> None:
    migration = next(
        item
        for item in migration_runner._load_migrations()
        if item.migration_id == "0033_document_scope_listing_indexes"
    )

    assert migration.transactional is False
    assert len(migration.statements()) == 3
    assert all("CREATE INDEX CONCURRENTLY IF NOT EXISTS" in item for item in migration.statements())
    assert migration.recoverable_indexes() == (
        "ix_memory_documents_scope_status_page",
        "ix_memory_documents_scope_thread_status_page",
        "ix_memory_documents_scope_thread_source_page",
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


def test_online_runner_uses_session_lock_autocommit_and_invalid_index_recovery() -> None:
    upgrade_source = inspect.getsource(migration_runner.upgrade_schema)
    release_source = inspect.getsource(migration_runner._release_advisory_lock)
    online_source = inspect.getsource(migration_runner._execute_nontransactional)

    assert "_acquire_advisory_lock" in upgrade_source
    assert upgrade_source.index("try:") < upgrade_source.index("await _acquire_advisory_lock")
    assert 'isolation_level="AUTOCOMMIT"' in upgrade_source
    assert "pg_advisory_xact_lock" not in upgrade_source
    assert "_release_advisory_lock" in upgrade_source
    assert "pg_advisory_unlock" in release_source
    assert "pg_try_advisory_lock" in inspect.getsource(migration_runner._acquire_advisory_lock)
    assert 'isolation_level="AUTOCOMMIT"' in online_source
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in online_source
    assert "_invalid_or_missing_indexes" in online_source
    assert "Online PostgreSQL migration left an invalid or missing index" in online_source


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
