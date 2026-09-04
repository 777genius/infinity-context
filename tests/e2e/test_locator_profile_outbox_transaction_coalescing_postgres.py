"""Real-PostgreSQL proof for transaction-coalesced outbox invalidation."""

from __future__ import annotations

import asyncio
import os

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from postgres_test_database import PostgresTestDatabase
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through


def test_0049_upgrade_and_transaction_coalescing_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_upgrade_and_coalescing(database_url))


async def _assert_upgrade_and_coalescing(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="locator_outbox_xact_coalescing",
        asyncpg=asyncpg,
    )
    await database.recreate()
    try:
        await _install_versioned_schema_through(database, "0049_")
        engine = build_async_engine(database.app_url)
        try:
            upgrade = await upgrade_schema(engine)
            assert upgrade.applied == (
                "0050_locator_profile_outbox_transaction_coalescing",
                "0051_locator_profile_acl_search_path_hardening",
                "0052_document_scope_listing_indexes",
                "0052_reconciliation_outbox_binding_index",
                "0053_retrieval_default_lifecycle",
                "0054_locator_profile_exact_delete_generation",
                "0055_generic_vector_rebuild_operations",
                "0056_fact_outbox_receipt_trigger_scope",
                "0057_unmanaged_document_trigger_scope",
                "0058_suggestion_server_thread_scope",
                "0059_locator_parent_lifecycle",
            )
            assert (await upgrade_schema(engine)).applied == ()
        finally:
            await engine.dispose()

        connection = await database.connect()
        try:
            baseline = await _evidence_version(connection)
            await _assert_once_across_multiple_rows_and_statements(connection, baseline)
            await _assert_exact_transition_and_row_semantics(connection, baseline + 1)
        finally:
            await connection.close()

        await _assert_concurrent_transactions_each_invalidate(database)
    finally:
        await database.drop()


async def _evidence_version(connection: object) -> int:
    return await connection.fetchval(
        "SELECT aggregate_version "
        "FROM memory_locator_profile_evidence_versions WHERE singleton=TRUE"
    )


async def _insert_outbox(connection: object, key: str, event_type: str) -> str | None:
    return await connection.fetchval(
        """
        INSERT INTO memory_outbox
          (message_key,event_type,aggregate_type,aggregate_id,aggregate_version,
           workload_class,fairness_key,payload_json,status,attempt_count,
           next_attempt_at,created_at,updated_at)
        VALUES ($1,$2,'probe',$3,1,'projection','probe:'||$4,'{}'::jsonb,
                'pending',0,clock_timestamp(),clock_timestamp(),clock_timestamp())
        RETURNING message_key
        """,
        key,
        event_type,
        key,
        key,
    )


async def _assert_once_across_multiple_rows_and_statements(
    connection: object, baseline: int
) -> None:
    async with connection.transaction():
        assert (
            await _insert_outbox(connection, "coalesced-upsert", "vector.upsert_locator_profile")
            == "coalesced-upsert"
        )
        assert (
            await _insert_outbox(connection, "coalesced-delete", "vector.delete_locator_profile")
            == "coalesced-delete"
        )
        assert (
            await _insert_outbox(connection, "coalesced-irrelevant", "probe.irrelevant")
            == "coalesced-irrelevant"
        )
        await connection.execute(
            "UPDATE memory_outbox SET attempt_count=attempt_count+1 "
            "WHERE message_key LIKE 'coalesced-%'"
        )
        await connection.execute("DELETE FROM memory_outbox WHERE message_key='coalesced-delete'")
        assert await _evidence_version(connection) == baseline + 1
    assert await _evidence_version(connection) == baseline + 1


async def _assert_exact_transition_and_row_semantics(connection: object, baseline: int) -> None:
    async with connection.transaction():
        assert (
            await _insert_outbox(connection, "transition-row", "probe.irrelevant")
            == "transition-row"
        )
        await connection.execute(
            "UPDATE memory_outbox SET attempt_count=attempt_count+1 "
            "WHERE message_key='transition-row'"
        )
    assert await _evidence_version(connection) == baseline

    row = await connection.fetchrow(
        "UPDATE memory_outbox SET event_type='vector.upsert_locator_profile' "
        "WHERE message_key='transition-row' RETURNING message_key,event_type"
    )
    assert tuple(row) == ("transition-row", "vector.upsert_locator_profile")
    assert await _evidence_version(connection) == baseline + 1

    row = await connection.fetchrow(
        "UPDATE memory_outbox SET attempt_count=attempt_count+1 "
        "WHERE message_key='transition-row' RETURNING message_key,event_type"
    )
    assert tuple(row) == ("transition-row", "vector.upsert_locator_profile")
    assert await _evidence_version(connection) == baseline + 2

    row = await connection.fetchrow(
        "UPDATE memory_outbox SET event_type='probe.irrelevant' "
        "WHERE message_key='transition-row' RETURNING message_key,event_type"
    )
    assert tuple(row) == ("transition-row", "probe.irrelevant")
    assert await _evidence_version(connection) == baseline + 3

    await connection.execute(
        "UPDATE memory_outbox SET attempt_count=attempt_count+1 WHERE message_key='transition-row'"
    )
    assert await _evidence_version(connection) == baseline + 3

    assert (
        await _insert_outbox(connection, "delete-row", "vector.delete_locator_profile")
        == "delete-row"
    )
    assert await _evidence_version(connection) == baseline + 4
    deleted = await connection.fetchrow(
        "DELETE FROM memory_outbox WHERE message_key='delete-row' RETURNING message_key,event_type"
    )
    assert tuple(deleted) == ("delete-row", "vector.delete_locator_profile")
    assert await _evidence_version(connection) == baseline + 5

    deleted = await connection.fetchrow(
        "DELETE FROM memory_outbox WHERE message_key='transition-row' "
        "RETURNING message_key,event_type"
    )
    assert tuple(deleted) == ("transition-row", "probe.irrelevant")
    assert await _evidence_version(connection) == baseline + 5


async def _assert_concurrent_transactions_each_invalidate(
    database: PostgresTestDatabase,
) -> None:
    first = await database.connect()
    second = await database.connect()
    baseline = await _evidence_version(first)
    first_transaction = first.transaction()
    await first_transaction.start()
    try:
        await _insert_outbox(first, "concurrent-first-a", "vector.upsert_locator_profile")

        second_started = asyncio.Event()

        async def write_second_transaction() -> None:
            async with second.transaction():
                second_started.set()
                await _insert_outbox(second, "concurrent-second-a", "vector.upsert_locator_profile")
                await _insert_outbox(second, "concurrent-second-b", "vector.delete_locator_profile")

        second_task = asyncio.create_task(write_second_transaction())
        await second_started.wait()
        await asyncio.sleep(0.05)
        assert not second_task.done()

        await _insert_outbox(first, "concurrent-first-b", "vector.delete_locator_profile")
        await first_transaction.commit()
        await second_task
    except BaseException:
        if first.is_in_transaction():
            await first_transaction.rollback()
        raise
    finally:
        await first.close()
        await second.close()

    verifier = await database.connect()
    try:
        assert await _evidence_version(verifier) == baseline + 2
    finally:
        await verifier.close()
