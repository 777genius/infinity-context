"""Forward, failed-transaction rollback and populated upgrade proof for 0048."""

from __future__ import annotations

import asyncio
import os

import pytest
from infinity_context_adapters.postgres import build_async_engine
from infinity_context_adapters.postgres.migration_runner import _load_migrations
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
    migrations = _load_migrations()
    release = migrations[-1]
    assert release.migration_id == "0048_locator_lifecycle_release_identity"
    try:
        for migration in migrations[:-1]:
            async with engine.begin() as connection:
                await _execute_script(connection, migration.sql)
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
