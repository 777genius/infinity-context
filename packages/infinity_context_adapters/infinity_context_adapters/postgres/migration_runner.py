"""Ordered PostgreSQL forward migrations with explicit online-DDL support."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from infinity_context_adapters.postgres.legacy_schema_manifest import (
    LEGACY_SCHEMA_MANIFESTS,
    LegacySchemaManifest,
)

_MIGRATIONS_DIRECTORY = Path(__file__).with_name("migrations")
_LEGACY_BASELINE_PREFIX = "0022_"
_ADVISORY_LOCK_ID = 4_916_625_310_112_023_308
_NON_TRANSACTIONAL_HEADER = "-- infinity-context: no-transaction"
_STATEMENT_BREAK = "-- infinity-context: statement-break"
_RECOVER_INDEX_PREFIX = "-- infinity-context: recover-index "
_PUBLISHED_CHECKSUM_ALIASES: dict[str, frozenset[str]] = {
    "0030_suggestion_receipt_tenant_integrity": frozenset(
        {"4d936c3d49f76028eec009a1b1e8ee2bcf214b2b4a03e7ac120bad5321aa3064"}
    ),
}


@dataclass(frozen=True, slots=True)
class SchemaUpgradeResult:
    applied: tuple[str, ...]
    legacy_baseline: bool
    current: str


@dataclass(frozen=True, slots=True)
class _Migration:
    migration_id: str
    checksum: str
    sql: str
    transactional: bool = True

    def statements(self) -> tuple[str, ...]:
        if self.transactional:
            return (self.sql,)
        body = self.sql.removeprefix(_NON_TRANSACTIONAL_HEADER).strip()
        statements = tuple(
            statement.strip() for statement in body.split(_STATEMENT_BREAK) if statement.strip()
        )
        if not statements:
            raise RuntimeError(
                f"Nontransactional PostgreSQL migration is empty: {self.migration_id}"
            )
        return statements

    def recoverable_indexes(self) -> tuple[str, ...]:
        names = tuple(
            line.removeprefix(_RECOVER_INDEX_PREFIX).strip()
            for line in self.sql.splitlines()
            if line.startswith(_RECOVER_INDEX_PREFIX)
        )
        if len(set(names)) != len(names):
            raise RuntimeError(f"Duplicate recoverable index in migration: {self.migration_id}")
        if any(re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name) is None for name in names):
            raise RuntimeError(f"Invalid recoverable index in migration: {self.migration_id}")
        return names


async def upgrade_schema(engine: AsyncEngine) -> SchemaUpgradeResult:
    """Apply packaged migrations once, including online DDL, under one writer lock."""

    if engine.dialect.name != "postgresql":
        raise RuntimeError("Versioned schema upgrade requires PostgreSQL")
    migrations = _load_migrations()
    applied: list[str] = []
    legacy_baseline = False

    async with engine.connect() as lock_connection:
        await lock_connection.execute(text(f"SELECT pg_advisory_lock({_ADVISORY_LOCK_ID})"))
        await lock_connection.commit()
        try:
            async with lock_connection.begin():
                await _ensure_history_table(lock_connection)
                applied_history = await _load_history(lock_connection)
                _validate_history(migrations, applied_history)
                legacy_baseline = not applied_history and await _has_unversioned_schema(
                    lock_connection
                )
                if legacy_baseline:
                    await _validate_legacy_baseline(lock_connection)
                    await _record_legacy_baseline(lock_connection, migrations)
                    applied_history = await _load_history(lock_connection)

                first_online = _first_pending_nontransactional(
                    migrations,
                    applied_history,
                )
                prefix = migrations if first_online is None else migrations[:first_online]
                applied.extend(
                    await _apply_transactional_pending(
                        lock_connection,
                        prefix,
                        applied_history,
                    )
                )

            start = len(migrations) if first_online is None else first_online
            for migration in migrations[start:]:
                if migration.migration_id in applied_history:
                    continue
                if migration.transactional:
                    async with lock_connection.begin():
                        await _execute_transactional(lock_connection, migration)
                        await _record_migration(
                            lock_connection,
                            migration,
                            execution_kind="applied",
                        )
                else:
                    await _execute_nontransactional(engine, migration)
                    async with lock_connection.begin():
                        await _record_migration(
                            lock_connection,
                            migration,
                            execution_kind="applied",
                        )
                applied.append(migration.migration_id)
        finally:
            if lock_connection.in_transaction():
                await lock_connection.rollback()
            await lock_connection.execute(text(f"SELECT pg_advisory_unlock({_ADVISORY_LOCK_ID})"))
            await lock_connection.commit()

    return SchemaUpgradeResult(
        applied=tuple(applied),
        legacy_baseline=legacy_baseline,
        current=migrations[-1].migration_id,
    )


def _load_migrations() -> tuple[_Migration, ...]:
    paths = sorted(_MIGRATIONS_DIRECTORY.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    if not paths:
        raise RuntimeError("No packaged PostgreSQL migrations were found")
    migrations = tuple(
        _Migration(
            migration_id=path.stem,
            checksum=sha256(path.read_bytes()).hexdigest(),
            sql=path.read_text(encoding="utf-8"),
            transactional=not path.read_text(encoding="utf-8").startswith(
                _NON_TRANSACTIONAL_HEADER
            ),
        )
        for path in paths
    )
    if len({migration.migration_id for migration in migrations}) != len(migrations):
        raise RuntimeError("Duplicate PostgreSQL migration identifiers")
    return migrations


async def _ensure_history_table(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS infinity_context_schema_migrations (
                migration_id VARCHAR(160) PRIMARY KEY,
                checksum VARCHAR(64) NOT NULL,
                execution_kind VARCHAR(32) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT ck_infinity_context_schema_migration_kind
                    CHECK (execution_kind IN ('applied', 'legacy_baseline'))
            )
            """
        )
    )


async def _load_history(connection: AsyncConnection) -> dict[str, str]:
    rows = (
        await connection.execute(
            text(
                """
                SELECT migration_id, checksum
                FROM infinity_context_schema_migrations
                ORDER BY migration_id
                """
            )
        )
    ).all()
    return {str(migration_id): str(checksum) for migration_id, checksum in rows}


def _validate_history(
    migrations: tuple[_Migration, ...],
    history: dict[str, str],
) -> None:
    known = {migration.migration_id: migration for migration in migrations}
    unknown = sorted(set(history) - set(known))
    if unknown:
        raise RuntimeError(f"Unknown applied PostgreSQL migration: {unknown[0]}")
    for migration_id, checksum in history.items():
        if known[
            migration_id
        ].checksum != checksum and checksum not in _PUBLISHED_CHECKSUM_ALIASES.get(
            migration_id, frozenset()
        ):
            raise RuntimeError(f"PostgreSQL migration checksum drift: {migration_id}")
    applied_ids = tuple(history)
    expected_prefix = tuple(migration.migration_id for migration in migrations[: len(history)])
    if applied_ids != expected_prefix:
        raise RuntimeError("PostgreSQL migration history contains a gap or is out of order")


async def _has_unversioned_schema(connection: AsyncConnection) -> bool:
    return bool(
        await connection.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = current_schema()
                      AND tablename <> 'infinity_context_schema_migrations'
                )
                """
            )
        )
    )


async def _validate_legacy_baseline(connection: AsyncConnection) -> None:
    """Recognize the documented pre-runner schema without mutating it."""

    rows = (
        await connection.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                """
            )
        )
    ).all()
    observed: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        observed.setdefault(str(table_name), set()).add(str(column_name))
    catalogs = {
        "constraints": await _load_catalog_names(
            connection,
            query="""
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE constraint_schema = current_schema()
            """,
        ),
        "indexes": await _load_catalog_names(
            connection,
            query="SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()",
        ),
        "triggers": await _load_catalog_names(
            connection,
            query="""
                SELECT DISTINCT trigger_name
                FROM information_schema.triggers
                WHERE trigger_schema = current_schema()
            """,
        ),
        "functions": await _load_catalog_names(
            connection,
            query="""
                SELECT routine_name
                FROM information_schema.routines
                WHERE routine_schema = current_schema()
            """,
        ),
        "extensions": await _load_catalog_names(
            connection,
            query="SELECT extname FROM pg_extension",
        ),
    }
    failures = [
        _manifest_mismatches(manifest, observed_columns=observed, catalogs=catalogs)
        for manifest in LEGACY_SCHEMA_MANIFESTS
    ]
    if any(not failure for failure in failures):
        return
    details = "; ".join(
        f"{manifest.name}: {', '.join(failure)}"
        for manifest, failure in zip(LEGACY_SCHEMA_MANIFESTS, failures, strict=True)
    )
    raise RuntimeError(f"Unrecognized legacy PostgreSQL migration baseline: {details}")


async def _load_catalog_names(connection: AsyncConnection, *, query: str) -> set[str]:
    return {str(value) for value in (await connection.execute(text(query))).scalars()}


def _manifest_mismatches(
    manifest: LegacySchemaManifest,
    *,
    observed_columns: dict[str, set[str]],
    catalogs: dict[str, set[str]],
) -> tuple[str, ...]:
    failures: list[str] = []
    missing_columns = {
        table_name: sorted(columns - observed_columns.get(table_name, set()))
        for table_name, columns in manifest.columns.items()
        if not columns <= observed_columns.get(table_name, set())
    }
    if missing_columns:
        failures.append(
            "columns "
            + " ".join(
                f"{table_name}({','.join(columns)})"
                for table_name, columns in sorted(missing_columns.items())
            )
        )
    required_catalogs = {
        "constraints": manifest.constraints,
        "indexes": manifest.indexes,
        "triggers": manifest.triggers,
        "functions": manifest.functions,
        "extensions": manifest.extensions,
    }
    for label, required in required_catalogs.items():
        missing = sorted(required - catalogs[label])
        if missing:
            failures.append(f"{label}({','.join(missing)})")
    return tuple(failures)


async def _record_legacy_baseline(
    connection: AsyncConnection,
    migrations: tuple[_Migration, ...],
) -> None:
    baseline = tuple(
        migration
        for migration in migrations
        if migration.migration_id <= _legacy_baseline_id(migrations)
    )
    for migration in baseline:
        await _record_migration(connection, migration, execution_kind="legacy_baseline")


def _legacy_baseline_id(migrations: tuple[_Migration, ...]) -> str:
    matches = tuple(
        migration.migration_id
        for migration in migrations
        if migration.migration_id.startswith(_LEGACY_BASELINE_PREFIX)
    )
    if len(matches) != 1:
        raise RuntimeError("Legacy PostgreSQL migration baseline is missing or ambiguous")
    return matches[0]


def _first_pending_nontransactional(
    migrations: tuple[_Migration, ...],
    history: dict[str, str],
) -> int | None:
    for index, migration in enumerate(migrations):
        if migration.migration_id not in history and not migration.transactional:
            return index
    return None


async def _apply_transactional_pending(
    connection: AsyncConnection,
    migrations: tuple[_Migration, ...],
    history: dict[str, str],
) -> tuple[str, ...]:
    applied: list[str] = []
    for migration in migrations:
        if migration.migration_id in history:
            continue
        if not migration.transactional:
            raise RuntimeError(
                f"Nontransactional migration entered transactional phase: {migration.migration_id}"
            )
        await _execute_transactional(connection, migration)
        await _record_migration(connection, migration, execution_kind="applied")
        applied.append(migration.migration_id)
    return tuple(applied)


async def _execute_transactional(
    connection: AsyncConnection,
    migration: _Migration,
) -> None:
    raw_connection = await connection.get_raw_connection()
    await raw_connection.driver_connection.execute(migration.sql)


async def _execute_nontransactional(
    engine: AsyncEngine,
    migration: _Migration,
) -> None:
    recoverable_indexes = migration.recoverable_indexes()
    async with engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        invalid_indexes = await _invalid_indexes(autocommit, recoverable_indexes)
        for index_name in invalid_indexes:
            await autocommit.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"')
        for statement in migration.statements():
            await autocommit.exec_driver_sql(statement)
        incomplete = await _invalid_or_missing_indexes(
            autocommit,
            recoverable_indexes,
        )
        if incomplete:
            raise RuntimeError(
                f"Online PostgreSQL migration left an invalid or missing index: {incomplete[0]}"
            )


async def _invalid_indexes(
    connection: AsyncConnection,
    index_names: tuple[str, ...],
) -> tuple[str, ...]:
    states = await _index_validity(connection, index_names)
    return tuple(name for name in index_names if states.get(name) is False)


async def _invalid_or_missing_indexes(
    connection: AsyncConnection,
    index_names: tuple[str, ...],
) -> tuple[str, ...]:
    states = await _index_validity(connection, index_names)
    return tuple(name for name in index_names if states.get(name) is not True)


async def _index_validity(
    connection: AsyncConnection,
    index_names: tuple[str, ...],
) -> dict[str, bool]:
    if not index_names:
        return {}
    quoted = ", ".join(f"'{name}'" for name in index_names)
    rows = (
        await connection.exec_driver_sql(
            f"""
            SELECT index_class.relname, index_state.indisvalid
            FROM pg_catalog.pg_index AS index_state
            JOIN pg_catalog.pg_class AS index_class
              ON index_class.oid = index_state.indexrelid
            JOIN pg_catalog.pg_namespace AS index_namespace
              ON index_namespace.oid = index_class.relnamespace
            WHERE index_namespace.nspname = current_schema()
              AND index_class.relname IN ({quoted})
            """
        )
    ).all()
    return {str(name): bool(valid) for name, valid in rows}


async def _record_migration(
    connection: AsyncConnection,
    migration: _Migration,
    *,
    execution_kind: str,
    applied_at: datetime | None = None,
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO infinity_context_schema_migrations (
                migration_id, checksum, execution_kind, applied_at
            ) VALUES (
                :migration_id, :checksum, :execution_kind,
                COALESCE(:applied_at, CURRENT_TIMESTAMP)
            )
            """
        ),
        {
            "migration_id": migration.migration_id,
            "checksum": migration.checksum,
            "execution_kind": execution_kind,
            "applied_at": applied_at,
        },
    )


__all__ = ("SchemaUpgradeResult", "upgrade_schema")
