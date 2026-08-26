from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres import migration_runner


def _sql(value: object) -> str:
    return " ".join(str(value).split())


class _EmptyResult:
    def all(self) -> tuple[object, ...]:
        return ()

    def scalars(self) -> tuple[object, ...]:
        return ()


class _RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement, *_args, **_kwargs) -> _EmptyResult:
        self.statements.append(_sql(statement))
        return _EmptyResult()

    async def scalar(self, statement, *_args, **_kwargs) -> bool:
        self.statements.append(_sql(statement))
        return False

    def begin(self) -> _Begin:
        return _Begin(self)

    async def commit(self) -> None:
        return None


class _Begin:
    def __init__(self, connection: _RecordingConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _RecordingConnection:
        return self._connection

    async def __aexit__(self, *_args) -> None:
        return None


class _Engine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self) -> None:
        self.connection = _RecordingConnection()

    def connect(self) -> _Begin:
        return _Begin(self.connection)


def test_upgrade_sets_hostile_safe_search_path_before_catalog_work(monkeypatch) -> None:
    migration = migration_runner._Migration("0001_test", "a" * 64, "SELECT 1")
    events: list[str] = []

    async def ensure_history(_connection) -> None:
        events.append("ensure-history")

    async def load_history(_connection) -> dict[str, str]:
        events.append("load-history")
        return {}

    async def has_unversioned_schema(_connection) -> bool:
        events.append("detect-legacy")
        return False

    async def apply_pending(_connection, _migrations, _history) -> tuple[str, ...]:
        events.append("apply-pending")
        return (migration.migration_id,)

    monkeypatch.setattr(migration_runner, "_load_migrations", lambda: (migration,))
    monkeypatch.setattr(migration_runner, "_ensure_history_table", ensure_history)
    monkeypatch.setattr(migration_runner, "_load_history", load_history)
    monkeypatch.setattr(migration_runner, "_has_unversioned_schema", has_unversioned_schema)
    monkeypatch.setattr(migration_runner, "_apply_pending", apply_pending)

    engine = _Engine()
    result = asyncio.run(migration_runner.upgrade_schema(engine))

    assert engine.connection.statements == [
        "SET search_path = public, pg_catalog, pg_temp",
        f"SELECT pg_catalog.pg_advisory_lock({migration_runner._ADVISORY_LOCK_ID})",
        f"SELECT pg_catalog.pg_advisory_unlock({migration_runner._ADVISORY_LOCK_ID})",
    ]
    assert events == ["ensure-history", "load-history", "detect-legacy", "apply-pending"]
    assert result.applied == (migration.migration_id,)


def test_history_and_legacy_catalog_sql_cannot_resolve_hostile_shadows() -> None:
    async def scenario() -> tuple[str, ...]:
        connection = _RecordingConnection()
        await migration_runner._ensure_history_table(connection)
        assert await migration_runner._load_history(connection) == {}
        assert await migration_runner._has_unversioned_schema(connection) is False
        with pytest.raises(RuntimeError, match="Unrecognized legacy PostgreSQL migration"):
            await migration_runner._validate_legacy_baseline(connection)
        await migration_runner._record_migration(
            connection,
            migration_runner._Migration("0001_test", "b" * 64, "SELECT 1"),
            execution_kind="applied",
        )
        return tuple(connection.statements)

    statements = asyncio.run(scenario())
    combined = "\n".join(statements).lower()

    assert combined.count("public.infinity_context_schema_migrations") == 3
    assert "current_schema" not in combined
    for fragment in (
        "from pg_catalog.pg_tables",
        "from information_schema.columns",
        "from information_schema.table_constraints",
        "from pg_catalog.pg_indexes",
        "from information_schema.triggers",
        "from information_schema.routines",
        "from pg_catalog.pg_extension",
    ):
        assert fragment in combined
    for schema_filter in (
        "schemaname = 'public'",
        "table_schema = 'public'",
        "constraint_schema = 'public'",
        "trigger_schema = 'public'",
        "routine_schema = 'public'",
    ):
        assert schema_filter in combined
