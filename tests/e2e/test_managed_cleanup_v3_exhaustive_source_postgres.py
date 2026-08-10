"""Fresh-Postgres proof that supported but unauthenticated jobs cannot hide."""

from __future__ import annotations

import asyncio
import json
import os

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.managed_cleanup_v3_canonical_inventory_source import (
    AsyncPostgresManagedCleanupV3CanonicalInventorySource,
)
from postgres_test_database import PostgresTestDatabase
from test_managed_cleanup_v3_canonical_inventory_source_postgres import _context


def test_supported_outbox_without_receipt_surfaces_as_unsupported_on_fresh_postgres():
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_supported_orphan_is_visible(database_url))


async def _assert_supported_orphan_is_visible(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="cleanup_v3_exhaustive", asyncpg=asyncpg
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
    finally:
        await engine.dispose()
    connection = await database.connect()
    try:
        context = _context()
        outbox_id = await connection.fetchval(
            """
            INSERT INTO memory_outbox (
              event_type, aggregate_type, aggregate_id, aggregate_version,
              payload_json, status, attempt_count, next_attempt_at,
              last_safe_error, created_at, updated_at, message_key
            ) VALUES (
              'vector.delete_chunks','benchmark_run',$1,NULL,$2::jsonb,'done',0,
              transaction_timestamp(),NULL,transaction_timestamp(),
              transaction_timestamp(),'orphan-supported-delete'
            ) RETURNING id
            """,
            context.run_id_sha256,
            json.dumps(
                {
                    "chunk_ids": ["unproven-chunk"],
                    "space_id": context.space_id,
                    "cleanup_run_id_sha256": context.run_id_sha256,
                }
            ),
        )
        for statement in (
            """INSERT INTO memory_spaces (id,slug,name,status,created_at,updated_at)
               VALUES ($1,$1,'Managed','deleted',now(),now())""",
            """INSERT INTO memory_scopes (
                 id,space_id,external_ref,name,status,created_at,updated_at
               ) VALUES ('scope-extra',$1,'scope-ref','Scope','deleted',now(),now())""",
            """INSERT INTO memory_threads (
                 id,space_id,memory_scope_id,external_ref,status,created_at,updated_at
               ) VALUES (
                 'thread-extra',$1,'scope-extra','thread-ref','deleted',now(),now()
               )""",
            """INSERT INTO memory_facts (
                 id,space_id,memory_scope_id,thread_id,kind,text,status,confidence,
                 trust_level,classification,version,created_at,updated_at
               ) VALUES (
                 'fact-extra',$1,'scope-extra','thread-extra','note','text','deleted',
                 'medium','medium','internal',1,now(),now()
               )""",
            """INSERT INTO memory_fact_versions (
                 fact_id,version,text,status,source_refs_json,snapshot_json,created_at
               ) VALUES ('fact-extra',1,'text','deleted','[]','{}',now())""",
            """INSERT INTO memory_source_refs (
                 fact_id,fact_version,source_type,source_id
               ) VALUES
                 ('fact-extra',1,'message','source-extra'),
                 ('fact-extra',1,'message','source-extra')""",
        ):
            if "$1" in statement:
                await connection.execute(statement, context.space_id)
            else:
                await connection.execute(statement)
        page = await AsyncPostgresManagedCleanupV3CanonicalInventorySource().read_page(
            connection,
            context=context,
            kind="unsupported_rows",
            after=None,
            limit=10,
        )
        assert page.exhausted
        locators = [dict(row.locator_json) for row in page.rows]
        assert {item["source_table"] for item in locators} == {
            "memory_facts",
            "memory_outbox",
            "memory_source_refs",
        }
        assert {
            item["source_pk"] for item in locators if item["source_table"] == "memory_outbox"
        } == {str(outbox_id)}
        assert sum(item["source_table"] == "memory_source_refs" for item in locators) == 2
    finally:
        await connection.close()
        await database.drop()


__all__ = ()
