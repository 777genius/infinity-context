"""Real operator-path proof for profile cleanup across Postgres and Qdrant."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_server.admin import retrieval_profile_lifecycle_command
from postgres_test_database import PostgresTestDatabase


def test_profile_delete_operator_when_disposable_services_are_configured(
    monkeypatch,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    qdrant_url = os.getenv("INFINITY_SANDBOX_QDRANT_URL")
    if not database_url or not qdrant_url:
        pytest.skip("disposable PostgreSQL and Qdrant are not configured")
    asyncio.run(_assert_operator_delete(database_url, qdrant_url, monkeypatch))


async def _assert_operator_delete(database_url, qdrant_url, monkeypatch) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    qdrant = pytest.importorskip("qdrant_client")
    database = PostgresTestDatabase.from_url(database_url, prefix="profile_admin", asyncpg=asyncpg)
    collection = f"profile_admin_{uuid4().hex}"
    now = datetime(2026, 8, 23, tzinfo=UTC)
    client = qdrant.AsyncQdrantClient(url=qdrant_url, timeout=10, trust_env=False)
    try:
        await database.recreate()
        engine = build_async_engine(database.app_url)
        try:
            await upgrade_schema(engine)
        finally:
            await engine.dispose()
        connection = await database.connect()
        try:
            await connection.execute(
                """
                INSERT INTO memory_locator_profiles (
                    profile_id, generation, profile_digest, collection_name, state,
                    backfill_complete, canonical_watermark, projected_watermark,
                    expected_count, projected_count, expected_digest, projected_digest,
                    created_at, retired_at
                ) VALUES (
                    'profile-admin', 'generation-admin', repeat('a', 64), $1, 'retired',
                    true, 0, 0, 0, 0, repeat('e', 64), repeat('e', 64), $2, $2
                )
                """,
                collection,
                now,
            )
        finally:
            await connection.close()
        await client.create_collection(
            collection,
            vectors_config=qdrant.models.VectorParams(
                size=2, distance=qdrant.models.Distance.COSINE
            ),
        )
        monkeypatch.setenv("MEMORY_DATABASE_URL", database.app_url)
        monkeypatch.setenv("MEMORY_QDRANT_URL", qdrant_url)
        monkeypatch.setenv("MEMORY_EMBEDDINGS_DIMENSIONS", "2")

        result = await retrieval_profile_lifecycle_command(
            operation="delete",
            target="profile-admin",
            limit=4,
            deadline_seconds=20,
        )

        assert result["status"] == "ok", result
        assert result["phase"] == "complete"
        assert await client.collection_exists(collection) is False
        connection = await database.connect()
        try:
            assert (
                await connection.fetchval(
                    "SELECT phase FROM memory_locator_profile_cleanups "
                    "WHERE profile_id = 'profile-admin'"
                )
                == "complete"
            )
        finally:
            await connection.close()
    finally:
        if await client.collection_exists(collection):
            await client.delete_collection(collection)
        await client.close()
        await database.drop()
