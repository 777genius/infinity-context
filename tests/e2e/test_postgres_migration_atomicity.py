"""Real-PostgreSQL proof that migration DDL and history have one commit boundary."""

from __future__ import annotations

import asyncio
import os

import pytest
from infinity_context_adapters.postgres import build_async_engine, migration_runner
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text


def test_failed_history_persistence_rolls_back_migration_ddl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_failed_history_is_atomic(database_url, monkeypatch))


async def _assert_failed_history_is_atomic(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="migration_atomicity",
        asyncpg=asyncpg,
    )
    try:
        await database.recreate()
        engine = build_async_engine(database.app_url)

        async def fail_history(*_args, **_kwargs) -> None:
            raise RuntimeError("injected history persistence failure")

        monkeypatch.setattr(migration_runner, "_record_migration", fail_history)
        try:
            with pytest.raises(RuntimeError, match="injected history persistence failure"):
                await migration_runner.upgrade_schema(engine)
            async with engine.connect() as connection:
                assert await connection.scalar(text("SELECT to_regclass('memory_spaces')")) is None
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM infinity_context_schema_migrations")
                    )
                    == 0
                )
        finally:
            await engine.dispose()
    finally:
        await database.drop()
