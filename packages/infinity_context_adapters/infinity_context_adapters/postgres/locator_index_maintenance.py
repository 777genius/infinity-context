"""Explicit, non-transactional concurrent-index phase for Retrieval."""

from __future__ import annotations

from contextlib import suppress
from enum import Enum, auto
from hashlib import sha256
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from infinity_context_adapters.postgres.locator_catalog_attestation import (
    LOCATOR_CATALOG_MAINTENANCE_LOCK_ID,
    attest_locator_retrieval_catalog,
)
from infinity_context_adapters.postgres.migration_metadata import (
    is_compatible_migration_checksum,
)

_MIGRATION_ID = "0039_locator_retrieval_attributes"
_MIGRATION = Path(__file__).with_name("migrations") / f"{_MIGRATION_ID}.sql"
_SQL = Path(__file__).with_name("maintenance") / "locator_retrieval_v2_concurrent_indexes.sql"
_EXPECTED_INDEXES = (
    "uq_memory_chunks_retrieval_locator_owner",
    "uq_memory_chunks_retrieval_active_ordinal_owner",
    "ix_memory_chunks_locator_retrieval",
    "ix_locator_projection_tombstones_pending",
)


class _AdvisoryLockState(Enum):
    NOT_ACQUIRED = auto()
    ACQUISITION_UNCERTAIN = auto()
    ACQUIRED = auto()


async def build_locator_retrieval_indexes(
    engine: AsyncEngine,
    *,
    lock_timeout_ms: int = 1_000,
    statement_timeout_ms: int = 0,
) -> tuple[str, ...]:
    """Build resumable indexes concurrently under a dedicated session lock."""

    if engine.dialect.name != "postgresql":
        raise RuntimeError("Locator index maintenance requires PostgreSQL")
    if lock_timeout_ms < 1 or statement_timeout_ms < 0:
        raise ValueError("invalid locator index maintenance timeout")
    statements = _maintenance_statements(_SQL.read_text(encoding="utf-8"))
    connection = await engine.connect()
    connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
    lock_state = _AdvisoryLockState.NOT_ACQUIRED
    application_error: BaseException | None = None
    try:
        await _require_expand_migration(connection)
        lock_state = _AdvisoryLockState.ACQUISITION_UNCERTAIN
        acquired = await connection.scalar(
            text(f"SELECT pg_try_advisory_lock({LOCATOR_CATALOG_MAINTENANCE_LOCK_ID})")
        )
        lock_state = (
            _AdvisoryLockState.ACQUIRED
            if acquired
            else _AdvisoryLockState.NOT_ACQUIRED
        )
        if not acquired:
            raise RuntimeError("Locator index maintenance is already running")
        await connection.execute(text(f"SET lock_timeout = '{lock_timeout_ms}ms'"))
        await connection.execute(
            text(
                "SET statement_timeout = "
                + ("0" if statement_timeout_ms == 0 else f"'{statement_timeout_ms}ms'")
            )
        )
        attestation = await attest_locator_retrieval_catalog(connection)
        non_index_mismatch = next(
            (mismatch for mismatch in attestation.mismatches if mismatch.object_kind != "index"),
            None,
        )
        if non_index_mismatch is not None:
            raise RuntimeError(
                "Unsafe Retrieval catalog mismatch cannot be repaired by index "
                f"maintenance: {non_index_mismatch.object_kind} "
                f"{non_index_mismatch.object_name}"
            )
        await _drop_mismatched_indexes(
            connection,
            {
                mismatch.object_name
                for mismatch in attestation.mismatches
                if mismatch.object_kind == "index" and mismatch.property_name != "presence"
            },
        )
        for statement in statements:
            await connection.execute(text(statement))
        (await attest_locator_retrieval_catalog(connection)).require_qualified()
        return _EXPECTED_INDEXES
    except BaseException as error:
        application_error = error
        raise
    finally:
        if lock_state is _AdvisoryLockState.ACQUIRED:
            await _release_advisory_lock(
                connection,
                application_error=application_error,
            )
        elif lock_state is _AdvisoryLockState.ACQUISITION_UNCERTAIN:
            await _discard_connection(connection)
        else:
            await connection.close()


async def _release_advisory_lock(
    connection: AsyncConnection,
    *,
    application_error: BaseException | None,
) -> None:
    cleanup_error: BaseException | None = None
    try:
        unlocked = await connection.scalar(
            text(f"SELECT pg_advisory_unlock({LOCATOR_CATALOG_MAINTENANCE_LOCK_ID})")
        )
        if unlocked is not True:
            cleanup_error = RuntimeError(
                "Locator index maintenance advisory lock was not released"
            )
    except BaseException as error:
        cleanup_error = error

    if cleanup_error is None:
        await connection.close()
        return
    await _discard_connection(connection)
    if application_error is None:
        raise cleanup_error


async def _discard_connection(connection: AsyncConnection) -> None:
    """Never pool a session whose advisory-lock state may still be acquired."""

    with suppress(BaseException):
        await connection.invalidate()
    with suppress(BaseException):
        await connection.close()


async def _require_expand_migration(connection) -> None:
    observed = await connection.scalar(
        text(
            "SELECT checksum FROM infinity_context_schema_migrations "
            "WHERE migration_id = :migration_id"
        ),
        {"migration_id": _MIGRATION_ID},
    )
    expected = sha256(_MIGRATION.read_bytes()).hexdigest()
    if not is_compatible_migration_checksum(_MIGRATION_ID, observed, expected):
        raise RuntimeError("Retrieval expand migration is absent or has checksum drift")


async def _drop_mismatched_indexes(connection, names: set[str]) -> None:
    if not names:
        return
    rows = tuple(
        (
            await connection.execute(
                text(
                    """SELECT c.relname, c.relkind,
                    EXISTS (SELECT 1 FROM pg_catalog.pg_constraint con
                            WHERE con.conindid = c.oid) AS constraint_owned
                    FROM pg_catalog.pg_class c
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relname = ANY(:names)
                    ORDER BY c.relname"""
                ),
                {"names": sorted(names)},
            )
        ).mappings()
    )
    for row in rows:
        index_name = row["relname"]
        relation_kind = row["relkind"]
        if isinstance(relation_kind, bytes):
            relation_kind = relation_kind.decode("ascii")
        if index_name not in _EXPECTED_INDEXES or relation_kind != "i" or row["constraint_owned"]:
            raise RuntimeError(f"Unsafe same-named relation cannot be rebuilt: {index_name}")
    for row in rows:
        index_name = row["relname"]
        await connection.execute(text(f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"'))


def _maintenance_statements(sql: str) -> tuple[str, ...]:
    without_comments = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    return tuple(
        statement.strip() for statement in without_comments.split(";") if statement.strip()
    )


__all__ = ("build_locator_retrieval_indexes",)
