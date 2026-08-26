"""Ordered, transactional PostgreSQL forward-migration runner."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from hashlib import sha256
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from infinity_context_adapters.postgres.legacy_schema_manifest import (
    LEGACY_SCHEMA_MANIFESTS,
    LegacySchemaManifest,
)
from infinity_context_adapters.postgres.migration_metadata import (
    is_compatible_migration_checksum,
)
from infinity_context_adapters.postgres.staged_locator_migrations import (
    STAGED_MIGRATION_IDS,
    apply_staged_locator_migration,
)

_MIGRATIONS_DIRECTORY = Path(__file__).with_name("migrations")
_LEGACY_BASELINE_PREFIX = "0022_"
_ADVISORY_LOCK_ID = 4_916_625_310_112_023_308
_ADVISORY_LOCK_RETRY_SECONDS = 0.05


class _AdvisoryLockState(Enum):
    NOT_ACQUIRED = auto()
    ACQUISITION_UNCERTAIN = auto()
    ACQUIRED = auto()


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


async def upgrade_schema(engine: AsyncEngine) -> SchemaUpgradeResult:
    """Apply packaged migrations once, failing closed on drift or history gaps."""

    if engine.dialect.name != "postgresql":
        raise RuntimeError("Versioned schema upgrade requires PostgreSQL")
    migrations = _load_migrations()
    async with engine.connect() as connection:
        # A session lock remains held across the committed backfill batches.
        # Acquire it through asyncpg before SQLAlchemy autobegin can leave a waiter
        # holding an open transaction that conflicts with the winner's DDL.
        raw_connection = await connection.get_raw_connection()
        driver_connection = raw_connection.driver_connection
        await driver_connection.execute("SET search_path = public, pg_catalog, pg_temp")
        lock_state = _AdvisoryLockState.NOT_ACQUIRED
        application_error: BaseException | None = None
        try:
            while lock_state is not _AdvisoryLockState.ACQUIRED:
                lock_state = _AdvisoryLockState.ACQUISITION_UNCERTAIN
                lock_acquired = bool(
                    await driver_connection.fetchval(
                        f"SELECT pg_catalog.pg_try_advisory_lock({_ADVISORY_LOCK_ID})"
                    )
                )
                lock_state = (
                    _AdvisoryLockState.ACQUIRED
                    if lock_acquired
                    else _AdvisoryLockState.NOT_ACQUIRED
                )
                if not lock_acquired:
                    await asyncio.sleep(_ADVISORY_LOCK_RETRY_SECONDS)
            async with connection.begin():
                await _ensure_history_table(connection)
                applied_history = await _load_history(connection)
                _validate_history(migrations, applied_history)
                legacy_baseline = not applied_history and await _has_unversioned_schema(connection)
                if legacy_baseline:
                    await _validate_legacy_baseline(connection)
                    await _record_legacy_baseline(connection, migrations)
                    applied_history = await _load_history(connection)
            applied = await _apply_pending(connection, migrations, applied_history)
        except BaseException as error:
            application_error = error
            raise
        finally:
            if lock_state is _AdvisoryLockState.ACQUIRED:
                await _release_advisory_lock(
                    connection,
                    driver_connection,
                    application_error=application_error,
                )
            elif lock_state is _AdvisoryLockState.ACQUISITION_UNCERTAIN:
                await _discard_connection(connection)
    return SchemaUpgradeResult(
        applied=applied,
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
            CREATE TABLE IF NOT EXISTS public.infinity_context_schema_migrations (
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
                FROM public.infinity_context_schema_migrations
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
        if not is_compatible_migration_checksum(
            migration_id, checksum, known[migration_id].checksum
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
                    WHERE schemaname = 'public'
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
                WHERE table_schema = 'public'
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
                WHERE constraint_schema = 'public'
            """,
        ),
        "indexes": await _load_catalog_names(
            connection,
            query="SELECT indexname FROM pg_catalog.pg_indexes WHERE schemaname = 'public'",
        ),
        "triggers": await _load_catalog_names(
            connection,
            query="""
                SELECT DISTINCT trigger_name
                FROM information_schema.triggers
                WHERE trigger_schema = 'public'
            """,
        ),
        "functions": await _load_catalog_names(
            connection,
            query="""
                SELECT routine_name
                FROM information_schema.routines
                WHERE routine_schema = 'public'
            """,
        ),
        "extensions": await _load_catalog_names(
            connection,
            query="SELECT extname FROM pg_catalog.pg_extension",
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


async def _apply_pending(
    connection: AsyncConnection,
    migrations: tuple[_Migration, ...],
    history: dict[str, str],
) -> tuple[str, ...]:
    applied: list[str] = []
    for migration in migrations:
        if migration.migration_id in history:
            continue
        if migration.migration_id in STAGED_MIGRATION_IDS:
            await apply_staged_locator_migration(
                connection, migration_id=migration.migration_id
            )
        async with connection.begin():
            raw_connection = await connection.get_raw_connection()
            # AsyncConnection.begin() is lazy. Force SQLAlchemy/asyncpg to start the
            # physical transaction before bypassing SQLAlchemy for a multi-statement
            # script, so the script and history insert share one commit boundary.
            await connection.execute(text("SELECT 1"))
            await raw_connection.driver_connection.execute(migration.sql)
            await _record_migration(connection, migration, execution_kind="applied")
        applied.append(migration.migration_id)
    return tuple(applied)


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
            INSERT INTO public.infinity_context_schema_migrations (
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


async def _release_advisory_lock(
    connection: AsyncConnection,
    driver_connection: object,
    *,
    application_error: BaseException | None,
) -> None:
    cleanup_error: BaseException | None = None
    try:
        unlocked = await driver_connection.fetchval(  # type: ignore[attr-defined]
            f"SELECT pg_catalog.pg_advisory_unlock({_ADVISORY_LOCK_ID})"
        )
        if unlocked is not True:
            cleanup_error = RuntimeError("PostgreSQL migration advisory lock was not released")
    except BaseException as error:
        cleanup_error = error

    if cleanup_error is None:
        return
    await _discard_connection(connection)
    if application_error is None:
        raise cleanup_error


async def _discard_connection(connection: AsyncConnection) -> None:
    """Never return a session with uncertain advisory-lock state to the pool."""

    with suppress(BaseException):
        await connection.invalidate()
    with suppress(BaseException):
        await connection.close()


__all__ = ("SchemaUpgradeResult", "upgrade_schema")
