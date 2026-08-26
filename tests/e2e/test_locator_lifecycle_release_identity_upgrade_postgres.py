"""Forward, failed-transaction rollback and populated upgrade proof for 0048."""

from __future__ import annotations

import asyncio
import os

import pytest
from infinity_context_adapters.postgres import build_async_engine, migration_runner
from infinity_context_adapters.postgres.staged_locator_migrations import (
    STAGED_MIGRATION_IDS,
    apply_staged_locator_migration,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text


def test_release_identity_migration_rolls_back_failed_transaction_when_postgres_configured(
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("disposable PostgreSQL is not configured")
    asyncio.run(_assert_transactional_rollback(database_url))


async def _assert_transactional_rollback(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="locator_release_rollback", asyncpg=asyncpg
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    migrations = migration_runner._load_migrations()
    release_index = next(
        index
        for index, migration in enumerate(migrations)
        if migration.migration_id == "0048_locator_lifecycle_release_identity"
    )
    release = migrations[release_index]
    assert release.migration_id == "0048_locator_lifecycle_release_identity"
    try:
        for migration in migrations[:release_index]:
            await _apply_setup_migration(engine, migration)
        raw = await database.connect()
        transaction = raw.transaction()
        await transaction.start()
        try:
            await raw.execute(release.sql)
            raise RuntimeError("force migration transaction rollback")
        except RuntimeError as exc:
            assert str(exc) == "force migration transaction rollback"
            await transaction.rollback()
        finally:
            await raw.close()
        async with engine.connect() as connection:
            rolled_back = await connection.scalar(
                text(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema='public' "
                    "AND table_name='memory_locator_runtime_incarnations' "
                    "AND column_name='release_identity_sha256'"
                )
            )
        assert int(rolled_back or 0) == 0
        async with engine.begin() as connection:
            await _execute_script(connection, release.sql)
        async with engine.connect() as connection:
            applied = await connection.scalar(
                text(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema='public' "
                    "AND table_name='memory_locator_runtime_incarnations' "
                    "AND column_name='release_identity_sha256'"
                )
            )
        assert int(applied or 0) == 1
    finally:
        await engine.dispose()
        await database.drop()


async def _execute_script(connection, sql: str) -> None:
    raw = await connection.get_raw_connection()
    await raw.driver_connection.execute(sql)


async def _apply_setup_migration(engine, migration) -> None:
    if not migration.transactional:
        await migration_runner._execute_nontransactional(engine, migration)
        return
    if migration.migration_id in STAGED_MIGRATION_IDS:
        async with engine.connect() as connection:
            await apply_staged_locator_migration(
                connection,
                migration_id=migration.migration_id,
            )
            async with connection.begin():
                await migration_runner._execute_transactional(connection, migration)
        return
    async with engine.begin() as connection:
        await migration_runner._execute_transactional(connection, migration)
