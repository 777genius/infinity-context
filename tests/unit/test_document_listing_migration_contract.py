"""Fail-closed contracts for online document listing index migration."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import migration_runner

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _ROOT
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
    / "0033_document_scope_listing_indexes.sql"
)
_RUNBOOK = _ROOT / "docs/document-listing-index-rollout.md"


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
    online_source = inspect.getsource(migration_runner._execute_nontransactional)

    assert "_acquire_advisory_lock" in upgrade_source
    assert "pg_advisory_xact_lock" not in upgrade_source
    assert "pg_advisory_unlock" in upgrade_source
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
        async def scalar(self, statement: object, parameters: object) -> bool:
            return False

    ticks = iter((10.0, 70.0))
    monkeypatch.setattr(migration_runner, "monotonic", lambda: next(ticks))

    with pytest.raises(TimeoutError, match="schema migration advisory lock"):
        asyncio.run(
            migration_runner._acquire_advisory_lock(Connection())  # type: ignore[arg-type]
        )


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
