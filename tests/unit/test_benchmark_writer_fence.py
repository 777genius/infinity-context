import asyncio
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_adapters.noop import SystemClock
from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_WRITER_FENCE_CONSTRAINT,
    BENCHMARK_WRITER_FENCE_FUNCTION,
    BENCHMARK_WRITER_FENCE_SQLSTATE,
    BENCHMARK_WRITER_FENCE_STATEMENTS,
    BENCHMARK_WRITER_FENCE_TABLES,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWork,
    _ensure_managed_benchmark_writer_fence,
    _ensure_runtime_schema,
    _is_benchmark_writer_fence_error,
    create_schema,
)
from infinity_context_core.domain.errors import MemoryConflictError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

MIGRATIONS = (
    Path(__file__).parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
)
INITIAL_MIGRATION = MIGRATIONS / "0017_managed_benchmark_writer_fence.sql"
PROJECTION_MANIFEST_MIGRATION = MIGRATIONS / "0018_benchmark_projection_manifest.sql"
SEALED_FENCE_MIGRATION = MIGRATIONS / "0019_managed_benchmark_sealed_fence.sql"
CLEANUP_COMPLETION_MIGRATION = MIGRATIONS / "0020_benchmark_cleanup_completion.sql"
CLEANUP_PLAN_MIGRATION = MIGRATIONS / "0033_benchmark_cleanup_plan.sql"
FENCE_SQLSTATE = BENCHMARK_WRITER_FENCE_SQLSTATE
FENCE_CONSTRAINT = BENCHMARK_WRITER_FENCE_CONSTRAINT
FENCED_TABLES = tuple(table for table, _update_columns in BENCHMARK_WRITER_FENCE_TABLES)
INITIAL_FENCED_TABLES = FENCED_TABLES[:7]


def test_migration_installs_active_writer_fence_on_all_canonical_tables() -> None:
    sql = INITIAL_MIGRATION.read_text(encoding="utf-8")

    assert "FOR SHARE NOWAIT;" in sql
    assert "WHEN lock_not_available THEN" in sql
    assert "IF registry_state = 'cleanup_pending' THEN" in sql
    assert "old_space_id IS DISTINCT FROM new_space_id" in sql
    assert "benchmark_run.space_id IN (old_space_id, new_space_id)" in sql
    assert "old_space_id := OLD.id" in sql
    assert "old_space_id := OLD.space_id" in sql
    assert f"ERRCODE = '{FENCE_SQLSTATE}'" in sql
    assert f"CONSTRAINT = '{FENCE_CONSTRAINT}'" in sql
    assert sql.count("RAISE EXCEPTION") == 3
    for table in INITIAL_FENCED_TABLES:
        assert f"DROP TRIGGER IF EXISTS trg_{table}_benchmark_writer_fence ON {table};" in sql
        assert f"CREATE TRIGGER trg_{table}_benchmark_writer_fence" in sql
    assert "BEFORE INSERT OR UPDATE OF id, status ON memory_spaces" in sql
    assert sql.count("BEFORE INSERT OR UPDATE OF space_id, status") == 6


def test_latest_migration_fails_closed_after_projection_manifest_seal() -> None:
    sql = SEALED_FENCE_MIGRATION.read_text(encoding="utf-8")

    assert sql.startswith(
        "CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_writer_fence()"
    )
    assert "IF TG_OP <> 'DELETE' THEN" in sql
    assert "IF TG_OP <> 'INSERT' THEN" in sql
    assert "target_space_id := COALESCE(new_space_id, old_space_id)" in sql
    assert "SELECT benchmark_run.state, benchmark_run.projection_cleanup_state" in sql
    assert "registry_state = 'active'" in sql
    assert "registry_projection_cleanup_state = 'unsealed'" in sql
    assert "registry_projection_cleanup_state IN ('pending', 'blocked')" in sql
    assert "OLD.status = 'active'" in sql
    assert "NEW.status = 'deleted'" in sql
    assert "to_jsonb(OLD) - 'status' - 'updated_at'" in sql
    assert "to_jsonb(NEW) - 'status' - 'updated_at'" in sql
    assert sql.count("BEFORE INSERT OR UPDATE OR DELETE") == len(INITIAL_FENCED_TABLES)
    for table in INITIAL_FENCED_TABLES:
        assert f"DROP TRIGGER IF EXISTS trg_{table}_benchmark_writer_fence ON {table};" in sql
        assert f"CREATE TRIGGER trg_{table}_benchmark_writer_fence" in sql
    assert f"ERRCODE = '{FENCE_SQLSTATE}'" in sql
    assert f"CONSTRAINT = '{FENCE_CONSTRAINT}'" in sql


def test_runtime_installer_statements_do_not_drift_from_latest_migration() -> None:
    migration_sql = _normalize_sql(CLEANUP_PLAN_MIGRATION.read_text(encoding="utf-8"))

    assert len(BENCHMARK_WRITER_FENCE_STATEMENTS) == 37
    assert BENCHMARK_WRITER_FENCE_FUNCTION in migration_sql
    assert _normalize_sql(BENCHMARK_WRITER_FENCE_STATEMENTS[0]) in migration_sql
    assert "registry_cleanup_plan_state" in migration_sql
    assert "cleanup_plan_state = 'sealed'" in migration_sql
    assert "AND TG_OP = 'INSERT'" in migration_sql
    assert "memory_fact_operation_receipts" in migration_sql
    assert "memory_anchors" in migration_sql
    assert "memory_fact_relations" in migration_sql
    assert "memory_context_links" in migration_sql


@pytest.mark.parametrize(
    ("dialect_name", "expected_statement_count"),
    [("postgresql", 37), ("sqlite", 0)],
)
def test_create_schema_writer_fence_helper_is_postgres_only(
    dialect_name: str,
    expected_statement_count: int,
) -> None:
    connection = _StatementRecordingConnection(dialect_name)

    _ensure_managed_benchmark_writer_fence(connection)

    assert len(connection.statements) == expected_statement_count
    if dialect_name == "postgresql":
        assert tuple(connection.statements) == BENCHMARK_WRITER_FENCE_STATEMENTS


def test_create_schema_registers_writer_fence_installer() -> None:
    asyncio.run(_assert_create_schema_registers_writer_fence())


def test_writer_fence_match_requires_exact_sqlstate_and_constraint() -> None:
    assert _is_benchmark_writer_fence_error(_integrity_error()) is True
    assert (
        _is_benchmark_writer_fence_error(
            _integrity_error(sqlstate="23505", constraint=FENCE_CONSTRAINT)
        )
        is False
    )
    assert (
        _is_benchmark_writer_fence_error(
            _integrity_error(sqlstate=FENCE_SQLSTATE, constraint="some_other_check")
        )
        is False
    )


def test_uow_exit_replaces_exact_fence_error_after_rollback_and_close() -> None:
    asyncio.run(_assert_uow_exit_mapping())


def test_uow_exit_translates_unrelated_integrity_error_after_rollback() -> None:
    asyncio.run(_assert_uow_exit_translates_unrelated_error())


@pytest.mark.parametrize(
    ("sqlstate", "constraint", "message"),
    [
        (FENCE_SQLSTATE, FENCE_CONSTRAINT, "cleanup in progress"),
        (
            "23505",
            "uq_existing_caller",
            "Canonical write conflicted with existing data",
        ),
    ],
)
def test_uow_commit_preserves_generic_conflicts_with_specific_fence_message(
    sqlstate: str,
    constraint: str,
    message: str,
) -> None:
    asyncio.run(
        _assert_commit_mapping(
            _integrity_error(sqlstate=sqlstate, constraint=constraint),
            message,
        )
    )


def test_real_postgres_writer_share_lock_serializes_cleanup_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_real_postgres_fence(database_url))


class _PgViolation(Exception):
    def __init__(self, *, sqlstate: str, constraint: str) -> None:
        super().__init__("synthetic postgres violation")
        self.sqlstate = sqlstate
        self.constraint_name = constraint


class _StatementRecordingConnection:
    def __init__(self, dialect_name: str) -> None:
        self.dialect = type("Dialect", (), {"name": dialect_name})()
        self.statements: list[str] = []

    def execute(self, statement) -> None:
        self.statements.append(str(statement))


class _RunSyncRecordingConnection:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    async def run_sync(self, callback) -> None:
        self.callbacks.append(callback)


class _RecordingBegin:
    def __init__(self, connection: _RunSyncRecordingConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _RunSyncRecordingConnection:
        return self.connection

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _RecordingEngine:
    def __init__(self) -> None:
        self.dialect = SimpleNamespace(name="sqlite")
        self.connection = _RunSyncRecordingConnection()

    def begin(self) -> _RecordingBegin:
        return _RecordingBegin(self.connection)


class _FakeSession:
    def __init__(self, *, commit_error: IntegrityError | None = None) -> None:
        self.commit_error = commit_error
        self.rollback_count = 0
        self.close_count = 0

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def close(self) -> None:
        self.close_count += 1


def _integrity_error(
    *,
    sqlstate: str = FENCE_SQLSTATE,
    constraint: str = FENCE_CONSTRAINT,
) -> IntegrityError:
    return IntegrityError(
        "synthetic statement",
        {},
        _PgViolation(sqlstate=sqlstate, constraint=constraint),
    )


def _normalize_sql(value: str) -> str:
    return " ".join(value.replace(";", "").split())


async def _assert_create_schema_registers_writer_fence() -> None:
    engine = _RecordingEngine()

    await create_schema(engine)

    assert engine.connection.callbacks[-1] is _ensure_runtime_schema


async def _assert_uow_exit_mapping() -> None:
    session = _FakeSession()
    uow = PostgresUnitOfWork(session_factory=lambda: session, clock=SystemClock())
    await uow.__aenter__()
    error = _integrity_error()

    with pytest.raises(MemoryConflictError, match="cleanup in progress") as raised:
        await uow.__aexit__(IntegrityError, error, None)

    assert raised.value.__cause__ is error
    assert session.rollback_count == 1
    assert session.close_count == 1


async def _assert_uow_exit_translates_unrelated_error() -> None:
    session = _FakeSession()
    uow = PostgresUnitOfWork(session_factory=lambda: session, clock=SystemClock())
    error = _integrity_error(sqlstate="23505", constraint="uq_existing_caller")

    with pytest.raises(MemoryConflictError, match="Canonical write conflicted") as raised:
        async with uow:
            raise error

    assert raised.value.__cause__ is error
    assert session.rollback_count == 1
    assert session.close_count == 1


async def _assert_commit_mapping(error: IntegrityError, message: str) -> None:
    session = _FakeSession(commit_error=error)
    uow = PostgresUnitOfWork(session_factory=lambda: session, clock=SystemClock())

    with pytest.raises(MemoryConflictError, match=message) as raised:
        async with uow:
            await uow.commit()

    assert raised.value.__cause__ is error
    assert session.rollback_count == 2
    assert session.close_count == 1


async def _assert_real_postgres_fence(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    parsed_url = make_url(database_url)
    if not parsed_url.drivername.startswith("postgresql"):
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")
    dsn = parsed_url.set(drivername="postgresql").render_as_string(hide_password=False)
    schema = f"writer_fence_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(dsn)
    writer = None
    cleanup = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(f'SET search_path TO "{schema}"')
        await admin.execute(_minimal_postgres_schema())
        await admin.execute(INITIAL_MIGRATION.read_text(encoding="utf-8"))
        await admin.execute(PROJECTION_MANIFEST_MIGRATION.read_text(encoding="utf-8"))
        await admin.execute(SEALED_FENCE_MIGRATION.read_text(encoding="utf-8"))
        writer = await asyncpg.connect(dsn)
        cleanup = await asyncpg.connect(dsn)
        await writer.execute(f'SET search_path TO "{schema}"')
        await cleanup.execute(f'SET search_path TO "{schema}"')

        await admin.execute("INSERT INTO memory_spaces (id, status) VALUES ('space-1', 'active')")
        await admin.execute(
            """
            INSERT INTO memory_comparison_benchmark_runs (space_id, state)
            VALUES ('space-1', 'active')
            """
        )

        writer_tx = writer.transaction()
        await writer_tx.start()
        await writer.execute(
            """
            INSERT INTO memory_facts (id, space_id, status)
            VALUES ('fact-before-cleanup', 'space-1', 'active')
            """
        )
        cleanup_task = asyncio.create_task(_mark_cleanup_pending(cleanup))
        await _wait_until_lock_blocked(
            admin,
            cleanup_pid=cleanup.get_server_pid(),
            writer_pid=writer.get_server_pid(),
        )
        await writer_tx.commit()
        visible_active_facts = await asyncio.wait_for(cleanup_task, timeout=5)
        assert visible_active_facts == 1

        with pytest.raises(asyncpg.CheckViolationError) as active_write:
            async with writer.transaction():
                await writer.execute(
                    """
                    INSERT INTO memory_facts (id, space_id, status)
                    VALUES ('fact-after-cleanup', 'space-1', 'active')
                    """
                )
        assert active_write.value.sqlstate == FENCE_SQLSTATE
        assert active_write.value.constraint_name == FENCE_CONSTRAINT

        await admin.execute("UPDATE memory_spaces SET status = 'deleted' WHERE id = 'space-1'")
        with pytest.raises(asyncpg.CheckViolationError):
            await admin.execute("UPDATE memory_spaces SET status = 'active' WHERE id = 'space-1'")

        await admin.execute(
            """
            UPDATE memory_comparison_benchmark_runs
            SET state = 'active', projection_cleanup_state = 'unsealed'
            WHERE space_id = 'space-1'
            """
        )
        cleanup_tx = cleanup.transaction()
        await cleanup_tx.start()
        await cleanup.execute(
            """
            UPDATE memory_comparison_benchmark_runs
            SET state = 'cleanup_pending', projection_cleanup_state = 'blocked'
            WHERE space_id = 'space-1'
            """
        )
        try:
            with pytest.raises(asyncpg.CheckViolationError) as cleanup_first_write:
                await asyncio.wait_for(
                    writer.execute(
                        """
                        INSERT INTO memory_facts (id, space_id, status)
                        VALUES ('fact-during-cleanup-lock', 'space-1', 'active')
                        """
                    ),
                    timeout=1,
                )
            assert cleanup_first_write.value.sqlstate == FENCE_SQLSTATE
            assert cleanup_first_write.value.constraint_name == FENCE_CONSTRAINT
        finally:
            await cleanup_tx.rollback()

        await admin.execute(
            """
            INSERT INTO memory_spaces (id, status)
            VALUES ('ordinary-a', 'active'), ('ordinary-b', 'active')
            """
        )
        await admin.execute(
            """
            INSERT INTO memory_facts (id, space_id, status)
            VALUES ('ordinary-move', 'ordinary-a', 'active')
            """
        )
        await admin.execute(
            """
            UPDATE memory_facts
            SET space_id = 'ordinary-b'
            WHERE id = 'ordinary-move'
            """
        )
        assert (
            await admin.fetchval("SELECT space_id FROM memory_facts WHERE id = 'ordinary-move'")
            == "ordinary-b"
        )

        await admin.execute(
            """
            INSERT INTO memory_facts (id, space_id, status)
            VALUES ('move-into-managed', 'ordinary-a', 'active')
            """
        )
        with pytest.raises(asyncpg.CheckViolationError) as move_into_managed:
            await admin.execute(
                """
                UPDATE memory_facts
                SET space_id = 'space-1'
                WHERE id = 'move-into-managed'
                """
            )
        assert move_into_managed.value.sqlstate == FENCE_SQLSTATE
        assert move_into_managed.value.constraint_name == FENCE_CONSTRAINT

        await admin.execute(
            """
            INSERT INTO memory_facts (id, space_id, status)
            VALUES ('move-out-of-managed', 'space-1', 'active')
            """
        )
        with pytest.raises(asyncpg.CheckViolationError) as move_out_of_managed:
            await admin.execute(
                """
                UPDATE memory_facts
                SET space_id = 'ordinary-a'
                WHERE id = 'move-out-of-managed'
                """
            )
        assert move_out_of_managed.value.sqlstate == FENCE_SQLSTATE
        assert move_out_of_managed.value.constraint_name == FENCE_CONSTRAINT

        await admin.execute(
            """
            UPDATE memory_comparison_benchmark_runs
            SET projection_manifest_json = '{}'::json,
                projection_manifest_sha256 = repeat('a', 64),
                projection_cleanup_state = 'sealed'
            WHERE space_id = 'space-1'
            """
        )
        with pytest.raises(asyncpg.CheckViolationError) as sealed_write:
            await writer.execute(
                """
                INSERT INTO memory_facts (id, space_id, status)
                VALUES ('fact-after-manifest-seal', 'space-1', 'active')
                """
            )
        assert sealed_write.value.sqlstate == FENCE_SQLSTATE
        assert sealed_write.value.constraint_name == FENCE_CONSTRAINT

        with pytest.raises(asyncpg.CheckViolationError) as sealed_content_update:
            await writer.execute(
                """
                UPDATE memory_facts
                SET payload = 'changed-after-seal'
                WHERE id = 'fact-before-cleanup'
                """
            )
        assert sealed_content_update.value.sqlstate == FENCE_SQLSTATE
        assert sealed_content_update.value.constraint_name == FENCE_CONSTRAINT

        with pytest.raises(asyncpg.CheckViolationError) as sealed_primary_key_update:
            await writer.execute(
                """
                UPDATE memory_facts
                SET id = 'fact-after-primary-key-change'
                WHERE id = 'fact-before-cleanup'
                """
            )
        assert sealed_primary_key_update.value.sqlstate == FENCE_SQLSTATE
        assert sealed_primary_key_update.value.constraint_name == FENCE_CONSTRAINT

        with pytest.raises(asyncpg.CheckViolationError) as sealed_physical_delete:
            await writer.execute("DELETE FROM memory_facts WHERE id = 'fact-before-cleanup'")
        assert sealed_physical_delete.value.sqlstate == FENCE_SQLSTATE
        assert sealed_physical_delete.value.constraint_name == FENCE_CONSTRAINT

        await admin.execute(
            """
            UPDATE memory_comparison_benchmark_runs
            SET state = 'cleanup_pending', projection_cleanup_state = 'pending'
            WHERE space_id = 'space-1'
            """
        )
        await admin.execute(
            """
            UPDATE memory_facts
            SET status = 'deleted', updated_at = now()
            WHERE id = 'fact-before-cleanup'
            """
        )
        assert (
            await admin.fetchval("SELECT status FROM memory_facts WHERE id = 'fact-before-cleanup'")
            == "deleted"
        )
    finally:
        if writer is not None:
            await writer.close()
        if cleanup is not None:
            await cleanup.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


async def _mark_cleanup_pending(connection) -> int:
    async with connection.transaction():
        await connection.execute("SET LOCAL lock_timeout = '5s'")
        await connection.execute(
            """
            UPDATE memory_comparison_benchmark_runs
            SET state = 'cleanup_pending', projection_cleanup_state = 'blocked'
            WHERE space_id = 'space-1'
            """
        )
        active_facts = await connection.fetchval(
            """
            SELECT count(*)
            FROM memory_facts
            WHERE space_id = 'space-1' AND status = 'active'
            """
        )
        return int(active_facts)


async def _wait_until_lock_blocked(
    connection,
    *,
    cleanup_pid: int,
    writer_pid: int,
) -> None:
    for _ in range(100):
        writer_blocks_cleanup = await connection.fetchval(
            "SELECT $1::integer = ANY(pg_blocking_pids($2::integer))",
            writer_pid,
            cleanup_pid,
        )
        if writer_blocks_cleanup is True:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("writer transaction did not block cleanup's registry update")


def _minimal_postgres_schema() -> str:
    child_tables = "\n".join(
        f"""
        CREATE TABLE {table} (
            id VARCHAR(80) PRIMARY KEY,
            space_id VARCHAR(80) NOT NULL,
            status VARCHAR(40) NOT NULL,
            payload VARCHAR(80),
            updated_at TIMESTAMPTZ
        );
        """
        for table in FENCED_TABLES
        if table != "memory_spaces"
    )
    return f"""
    CREATE TABLE memory_spaces (
        id VARCHAR(80) PRIMARY KEY,
        status VARCHAR(40) NOT NULL,
        payload VARCHAR(80),
        updated_at TIMESTAMPTZ
    );
    CREATE TABLE memory_comparison_benchmark_runs (
        space_id VARCHAR(80) PRIMARY KEY,
        state VARCHAR(40) NOT NULL
    );
    {child_tables}
    """
