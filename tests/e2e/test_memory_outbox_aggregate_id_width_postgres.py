from __future__ import annotations

import asyncio
import os

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from postgres_test_database import PostgresTestDatabase
from postgres_versioned_schema_fixtures import install_versioned_schema_through
from sqlalchemy import text


def test_memory_outbox_width_upgrade_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_width_upgrade(database_url))


async def _assert_width_upgrade(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="outbox_width_0060", asyncpg=asyncpg
    )
    await database.recreate()
    try:
        await install_versioned_schema_through(database, "0059_")
        existing_id = "e" * 80
        raw = await database.connect()
        try:
            await raw.execute(
                "INSERT INTO memory_outbox "
                "(event_type,aggregate_type,aggregate_id,payload_json,status,"
                "attempt_count,next_attempt_at,created_at,updated_at) "
                "VALUES ('probe.existing','locator_profile',$1,'{}','pending',0,"
                "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                existing_id,
            )
        finally:
            await raw.close()

        engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(engine)
            assert result.applied == ("0060_memory_outbox_aggregate_id_width",)
            aggregate_id = "p" * 120
            async with engine.begin() as connection:
                assert await connection.scalar(
                    text(
                        "SELECT character_maximum_length FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name='memory_outbox' "
                        "AND column_name='aggregate_id'"
                    )
                ) == 120
                assert await connection.scalar(
                    text("SELECT aggregate_id FROM memory_outbox WHERE aggregate_id=:id"),
                    {"id": existing_id},
                ) == existing_id
                await connection.execute(
                    text(
                        "INSERT INTO memory_outbox "
                        "(event_type,aggregate_type,aggregate_id,payload_json,status,"
                        "attempt_count,next_attempt_at,created_at,updated_at) "
                        "VALUES ('vector.upsert_locator_profile','locator_profile',:id,"
                        "'{}','pending',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,"
                        "CURRENT_TIMESTAMP)"
                    ),
                    {"id": aggregate_id},
                )
        finally:
            await engine.dispose()
    finally:
        await database.drop()
