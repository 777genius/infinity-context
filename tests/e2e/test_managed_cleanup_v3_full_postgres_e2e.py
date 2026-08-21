"""Full strict-v4 canonical-source to sealed-inventory PostgreSQL E2E."""

from __future__ import annotations

import asyncio
import os
import time

import asyncpg
import pytest
from infinity_context_core.ports.managed_cleanup_v3_contracts import ManagedCleanupV3Error
from infinity_context_core.ports.managed_cleanup_v3_recovery import INVENTORY_KINDS
from managed_cleanup_v3_full_postgres_support import create_full_postgres_harness


def test_full_strict_v4_source_materializes_and_replays_on_fresh_postgres(tmp_path) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_full_flow(database_url, tmp_path))


async def _assert_full_flow(database_url: str, tmp_path) -> None:
    harness = await create_full_postgres_harness(database_url, tmp_path)
    try:
        started = time.monotonic()
        await harness.materializer.materialize(
            context=harness.context,
            authority_terminal_sha256=harness.authority.terminal_commitment_sha256,
            cleanup_receipt_sha256=harness.cleanup_receipt_sha256,
        )
        assert time.monotonic() - started < 300
        assert harness.source_page_calls == {
            "memory_scopes": 1,
            "memory_threads": 1,
            "facts": 12,
            "fact_source_refs": 12,
            "documents": 1,
            "chunks": 1,
            "qdrant_target_identities": 1,
            "graphiti_target_names": 12,
            "graphiti_target_uuids": 12,
            "qdrant_upsert_jobs": 1,
            "qdrant_delete_jobs": 1,
            "graphiti_upsert_jobs": 12,
            "graphiti_delete_jobs": 12,
            "cleanup_outbox_receipts": 12,
            "unsupported_rows": 1,
        }
        connection = await harness.database.connect()
        try:
            summaries = await connection.fetch(
                """
                SELECT kind, expected_count, complete
                FROM memory_cleanup_inventory_materializations
                WHERE run_id_sha256=$1 AND context_sha256=$2
                  AND cleanup_receipt_sha256=$3
                ORDER BY kind
                """,
                harness.context.run_id_sha256,
                harness.context.context_sha256,
                harness.cleanup_receipt_sha256,
            )
            counts = {str(row["kind"]): int(row["expected_count"]) for row in summaries}
            assert set(counts) == set(INVENTORY_KINDS)
            assert all(row["complete"] is True for row in summaries)
            assert counts["facts"] == 5882
            assert counts["fact_source_refs"] == 5882
            assert counts["graphiti_target_names"] == 5882
            assert counts["graphiti_target_uuids"] == 5882
            assert counts["graphiti_upsert_jobs"] == 5882
            assert counts["graphiti_delete_jobs"] == 5882
            assert counts["cleanup_outbox_receipts"] == 5882
        finally:
            await connection.close()

        # Exact replay authenticates sealed PG rows and never re-consumes source claims.
        await harness.materializer.materialize(
            context=harness.context,
            authority_terminal_sha256=harness.authority.terminal_commitment_sha256,
            cleanup_receipt_sha256=harness.cleanup_receipt_sha256,
        )
        assert sum(harness.source_page_calls.values()) == 92

        connection = await harness.database.connect()
        try:
            receipt = await connection.fetchrow(
                """
                SELECT outbox_id
                FROM memory_projection_result_receipts
                ORDER BY outbox_id LIMIT 1
                """
            )
            assert receipt is not None
            with pytest.raises(asyncpg.UniqueViolationError):
                await connection.execute(
                    """
                    INSERT INTO memory_projection_result_receipts
                    SELECT * FROM memory_projection_result_receipts
                    WHERE outbox_id=$1
                    """,
                    receipt["outbox_id"],
                )
            row = await connection.fetchrow(
                """
                SELECT canonical_key_sha256, row_mac_sha256
                FROM memory_cleanup_inventory_keys
                WHERE run_id_sha256=$1 AND context_sha256=$2
                  AND cleanup_receipt_sha256=$3 AND kind='facts'
                ORDER BY canonical_key_sha256 LIMIT 1
                """,
                harness.context.run_id_sha256,
                harness.context.context_sha256,
                harness.cleanup_receipt_sha256,
            )
            assert row is not None
            await connection.execute(
                "ALTER TABLE memory_cleanup_inventory_keys DISABLE TRIGGER USER"
            )
            try:
                await connection.execute(
                    """
                    UPDATE memory_cleanup_inventory_keys
                    SET row_mac_sha256=$1
                    WHERE run_id_sha256=$2 AND context_sha256=$3
                      AND cleanup_receipt_sha256=$4 AND kind='facts'
                      AND canonical_key_sha256=$5
                    """,
                    "0" * 64,
                    harness.context.run_id_sha256,
                    harness.context.context_sha256,
                    harness.cleanup_receipt_sha256,
                    row["canonical_key_sha256"],
                )
            finally:
                await connection.execute(
                    "ALTER TABLE memory_cleanup_inventory_keys ENABLE TRIGGER USER"
                )
        finally:
            await connection.close()
        with pytest.raises(ManagedCleanupV3Error, match="inventory_page_invalid"):
            await harness.materializer.materialize(
                context=harness.context,
                authority_terminal_sha256=harness.authority.terminal_commitment_sha256,
                cleanup_receipt_sha256=harness.cleanup_receipt_sha256,
            )
        assert sum(harness.source_page_calls.values()) == 92

        connection = await harness.database.connect()
        try:
            await connection.execute(
                "ALTER TABLE memory_cleanup_inventory_keys DISABLE TRIGGER USER"
            )
            try:
                await connection.execute(
                    """
                    UPDATE memory_cleanup_inventory_keys
                    SET row_mac_sha256=$1
                    WHERE run_id_sha256=$2 AND context_sha256=$3
                      AND cleanup_receipt_sha256=$4 AND kind='facts'
                      AND canonical_key_sha256=$5
                    """,
                    row["row_mac_sha256"],
                    harness.context.run_id_sha256,
                    harness.context.context_sha256,
                    harness.cleanup_receipt_sha256,
                    row["canonical_key_sha256"],
                )
                await connection.execute(
                    """
                    DELETE FROM memory_cleanup_inventory_keys
                    WHERE run_id_sha256=$1 AND context_sha256=$2
                      AND cleanup_receipt_sha256=$3 AND kind='facts'
                      AND canonical_key_sha256=$4
                    """,
                    harness.context.run_id_sha256,
                    harness.context.context_sha256,
                    harness.cleanup_receipt_sha256,
                    row["canonical_key_sha256"],
                )
            finally:
                await connection.execute(
                    "ALTER TABLE memory_cleanup_inventory_keys ENABLE TRIGGER USER"
                )
        finally:
            await connection.close()
        with pytest.raises(ManagedCleanupV3Error, match="replay_invalid"):
            await harness.materializer.materialize(
                context=harness.context,
                authority_terminal_sha256=harness.authority.terminal_commitment_sha256,
                cleanup_receipt_sha256=harness.cleanup_receipt_sha256,
            )
    finally:
        await harness.close()
