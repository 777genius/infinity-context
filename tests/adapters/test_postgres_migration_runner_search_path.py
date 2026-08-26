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
    def __init__(
        self,
        events: list[str] | None = None,
        *,
        lock_attempts: tuple[bool, ...] = (True,),
        unlock_result: bool | BaseException = True,
    ) -> None:
        self.statements: list[str] = []
        self.events = events if events is not None else []
        self.invalidated = False
        self.closed = False
        self.driver = _RecordingDriver(
            self.events,
            lock_attempts=lock_attempts,
            unlock_result=unlock_result,
        )

    async def execute(self, statement, *_args, **_kwargs) -> _EmptyResult:
        normalized = _sql(statement)
        self.statements.append(normalized)
        self.events.append(f"sqlalchemy:{normalized}")
        return _EmptyResult()

    async def scalar(self, statement, *_args, **_kwargs) -> bool:
        self.statements.append(_sql(statement))
        return False

    def begin(self) -> _Begin:
        return _Begin(self, self.events)

    async def get_raw_connection(self):
        return SimpleNamespace(driver_connection=self.driver)

    async def invalidate(self) -> None:
        self.invalidated = True
        self.events.append("sqlalchemy:invalidate")

    async def close(self) -> None:
        self.closed = True
        self.events.append("sqlalchemy:close")


class _RecordingDriver:
    def __init__(
        self,
        events: list[str],
        *,
        lock_attempts: tuple[bool, ...],
        unlock_result: bool | BaseException,
    ) -> None:
        self.statements: list[str] = []
        self._events = events
        self._lock_attempts = iter(lock_attempts)
        self._unlock_result = unlock_result

    async def execute(self, statement: str) -> str:
        normalized = _sql(statement)
        self.statements.append(normalized)
        self._events.append(f"raw:{normalized}")
        return "OK"

    async def fetchval(self, statement: str) -> bool:
        normalized = _sql(statement)
        self.statements.append(normalized)
        if "pg_advisory_unlock" in normalized:
            if isinstance(self._unlock_result, BaseException):
                self._events.append(f"raw-error:{normalized}")
                raise self._unlock_result
            result = self._unlock_result
        else:
            result = next(self._lock_attempts)
        self._events.append(f"raw-complete:{normalized}:{result}")
        return result


class _Begin:
    def __init__(self, connection: _RecordingConnection, events: list[str]) -> None:
        self._connection = connection
        self._events = events

    async def __aenter__(self) -> _RecordingConnection:
        self._events.append("sqlalchemy:begin")
        return self._connection

    async def __aexit__(self, *_args) -> None:
        self._events.append("sqlalchemy:end")
        return None


class _ConnectionContext:
    def __init__(self, connection: _RecordingConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _RecordingConnection:
        return self._connection

    async def __aexit__(self, *_args) -> None:
        return None


class _Engine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(
        self,
        events: list[str] | None = None,
        *,
        lock_attempts: tuple[bool, ...] = (True,),
        unlock_result: bool | BaseException = True,
    ) -> None:
        self.connection = _RecordingConnection(
            events,
            lock_attempts=lock_attempts,
            unlock_result=unlock_result,
        )

    def connect(self) -> _ConnectionContext:
        return _ConnectionContext(self.connection)


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

    async def record_backoff(delay: float) -> None:
        assert delay == migration_runner._ADVISORY_LOCK_RETRY_SECONDS
        events.append("backoff")

    monkeypatch.setattr(migration_runner, "_load_migrations", lambda: (migration,))
    monkeypatch.setattr(migration_runner, "_ensure_history_table", ensure_history)
    monkeypatch.setattr(migration_runner, "_load_history", load_history)
    monkeypatch.setattr(migration_runner, "_has_unversioned_schema", has_unversioned_schema)
    monkeypatch.setattr(migration_runner, "_apply_pending", apply_pending)
    monkeypatch.setattr(migration_runner.asyncio, "sleep", record_backoff)

    engine = _Engine(events, lock_attempts=(False, True))
    result = asyncio.run(migration_runner.upgrade_schema(engine))

    assert engine.connection.statements == []
    assert engine.connection.driver.statements == [
        "SET search_path = public, pg_catalog, pg_temp",
        f"SELECT pg_catalog.pg_try_advisory_lock({migration_runner._ADVISORY_LOCK_ID})",
        f"SELECT pg_catalog.pg_try_advisory_lock({migration_runner._ADVISORY_LOCK_ID})",
        f"SELECT pg_catalog.pg_advisory_unlock({migration_runner._ADVISORY_LOCK_ID})",
    ]
    assert events == [
        "raw:SET search_path = public, pg_catalog, pg_temp",
        "raw-complete:SELECT pg_catalog.pg_try_advisory_lock"
        f"({migration_runner._ADVISORY_LOCK_ID}):False",
        "backoff",
        "raw-complete:SELECT pg_catalog.pg_try_advisory_lock"
        f"({migration_runner._ADVISORY_LOCK_ID}):True",
        "sqlalchemy:begin",
        "ensure-history",
        "load-history",
        "detect-legacy",
        "sqlalchemy:end",
        "apply-pending",
        "raw-complete:SELECT pg_catalog.pg_advisory_unlock"
        f"({migration_runner._ADVISORY_LOCK_ID}):True",
    ]
    assert result.applied == (migration.migration_id,)


def test_upgrade_cancelled_while_waiting_does_not_unlock(monkeypatch) -> None:
    migration = migration_runner._Migration("0001_test", "a" * 64, "SELECT 1")

    async def cancel_backoff(_delay: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(migration_runner, "_load_migrations", lambda: (migration,))
    monkeypatch.setattr(migration_runner.asyncio, "sleep", cancel_backoff)

    engine = _Engine(lock_attempts=(False,))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(migration_runner.upgrade_schema(engine))

    assert engine.connection.driver.statements == [
        "SET search_path = public, pg_catalog, pg_temp",
        f"SELECT pg_catalog.pg_try_advisory_lock({migration_runner._ADVISORY_LOCK_ID})",
    ]


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_upgrade_releases_acquired_lock_after_application_failure(
    monkeypatch,
    error_type: type[BaseException],
) -> None:
    migration = migration_runner._Migration("0001_test", "a" * 64, "SELECT 1")

    async def fail_application(_connection, _migrations, _history) -> tuple[str, ...]:
        raise error_type("application stopped")

    monkeypatch.setattr(migration_runner, "_load_migrations", lambda: (migration,))
    monkeypatch.setattr(migration_runner, "_apply_pending", fail_application)

    engine = _Engine()
    with pytest.raises(error_type, match="application stopped"):
        asyncio.run(migration_runner.upgrade_schema(engine))

    assert engine.connection.driver.statements == [
        "SET search_path = public, pg_catalog, pg_temp",
        f"SELECT pg_catalog.pg_try_advisory_lock({migration_runner._ADVISORY_LOCK_ID})",
        f"SELECT pg_catalog.pg_advisory_unlock({migration_runner._ADVISORY_LOCK_ID})",
    ]


@pytest.mark.parametrize(
    ("unlock_result", "error_type"),
    [
        (False, RuntimeError),
        (OSError("connection lost"), OSError),
        (asyncio.CancelledError("unlock cancelled"), asyncio.CancelledError),
    ],
)
def test_uncertain_unlock_discards_connection(
    monkeypatch,
    unlock_result: bool | BaseException,
    error_type: type[BaseException],
) -> None:
    migration = migration_runner._Migration("0001_test", "a" * 64, "SELECT 1")

    async def apply_pending(_connection, _migrations, _history) -> tuple[str, ...]:
        return (migration.migration_id,)

    monkeypatch.setattr(migration_runner, "_load_migrations", lambda: (migration,))
    monkeypatch.setattr(migration_runner, "_apply_pending", apply_pending)
    engine = _Engine(unlock_result=unlock_result)

    with pytest.raises(error_type):
        asyncio.run(migration_runner.upgrade_schema(engine))

    assert engine.connection.invalidated
    assert engine.connection.closed


@pytest.mark.parametrize(
    "unlock_result",
    [False, OSError("connection lost"), asyncio.CancelledError("unlock cancelled")],
)
@pytest.mark.parametrize(
    "application_error",
    [
        LookupError("original application failure"),
        asyncio.CancelledError("original application cancellation"),
    ],
)
def test_uncertain_unlock_preserves_original_application_error(
    monkeypatch,
    unlock_result: bool | BaseException,
    application_error: BaseException,
) -> None:
    migration = migration_runner._Migration("0001_test", "a" * 64, "SELECT 1")

    async def fail_application(_connection, _migrations, _history) -> tuple[str, ...]:
        raise application_error

    monkeypatch.setattr(migration_runner, "_load_migrations", lambda: (migration,))
    monkeypatch.setattr(migration_runner, "_apply_pending", fail_application)
    engine = _Engine(unlock_result=unlock_result)

    with pytest.raises(type(application_error), match=str(application_error)):
        asyncio.run(migration_runner.upgrade_schema(engine))

    assert engine.connection.invalidated
    assert engine.connection.closed


def test_pending_script_starts_physical_transaction_before_raw_ddl(monkeypatch) -> None:
    events: list[str] = []
    connection = _RecordingConnection(events)
    migration = migration_runner._Migration(
        "0001_atomic", "a" * 64, "CREATE TABLE atomic_proof (id integer)"
    )

    async def fail_history(*_args, **_kwargs) -> None:
        events.append("history:failed")
        raise RuntimeError("history persistence failed")

    monkeypatch.setattr(migration_runner, "_record_migration", fail_history)
    with pytest.raises(RuntimeError, match="history persistence failed"):
        asyncio.run(migration_runner._apply_pending(connection, (migration,), {}))

    assert events.index("sqlalchemy:SELECT 1") < events.index(
        "raw:CREATE TABLE atomic_proof (id integer)"
    )
    assert events.index("raw:CREATE TABLE atomic_proof (id integer)") < events.index(
        "history:failed"
    )


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
