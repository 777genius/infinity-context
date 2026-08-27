"""Executable upgrade proofs for the Retrieval-default lifecycle cutover."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_locator_retrieval_indexes,
    upgrade_schema,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through


@pytest.mark.parametrize("starting_migration", ["0039_", "0040_"])
def test_retrieval_cutover_upgrade_when_postgres_is_configured(starting_migration: str) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_cutover_upgrade(database_url, starting_migration))


def test_retrieval_cutover_refuses_running_work_and_is_idempotent_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_running_work_refusal_and_idempotence(database_url))


async def _assert_cutover_upgrade(database_url: str, starting_migration: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix=f"retrieval_cutover_{starting_migration[:4]}",
        asyncpg=asyncpg,
    )
    try:
        await database.recreate()
        await _install_versioned_schema_through(database, starting_migration)
        raw = await database.connect()
        try:
            if starting_migration == "0040_":
                await _install_staged_watermark(raw)
                await _seed_profile(raw)
            await _seed_chunk_and_queued_events(raw)
        finally:
            await raw.close()

        engine = build_async_engine(database.app_url)
        try:
            upgraded = await upgrade_schema(engine)
            expected = (
                "0039_locator_retrieval_attributes",
                "0040_locator_profile_lifecycle",
                "0041_locator_profile_attestation_fence",
                "0042_locator_profile_retirement",
                "0043_locator_profile_transition_audit",
                "0044_locator_profile_operator_receipts",
                "0045_locator_profile_incremental_attestation",
                "0046_locator_profile_linearizable_fences",
                "0047_locator_runtime_supervisor_proofs",
                "0048_locator_lifecycle_release_identity",
                "0049_reconciliation_runtime_generation",
                "0050_locator_profile_outbox_transaction_coalescing",
                "0051_locator_profile_acl_search_path_hardening",
                "0052_document_scope_listing_indexes",
                "0052_reconciliation_outbox_binding_index",
                "0053_retrieval_default_lifecycle",
                "0054_locator_profile_exact_delete_generation",
                "0055_generic_vector_rebuild_operations",
                "0056_fact_outbox_receipt_trigger_scope",
                "0057_unmanaged_document_trigger_scope",
            )
            installed_count = 1 if starting_migration == "0039_" else 2
            assert upgraded.applied == expected[installed_count:]
            assert upgraded.current == "0057_unmanaged_document_trigger_scope"
            assert upgraded.applied[-1] == "0057_unmanaged_document_trigger_scope"
            assert len(await build_locator_retrieval_indexes(engine)) == 3
            assert len(await build_locator_retrieval_indexes(engine)) == 3
            async with engine.begin() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT to_regclass('memory_locator_projection_tombstones')")
                    )
                    is None
                )
                assert (
                    await connection.scalar(
                        text(
                            "SELECT to_regprocedure('memory_chunk_locator_projection_events_v2()')"
                        )
                    )
                    is None
                )
                triggers = set(
                    (
                        await connection.execute(
                            text(
                                "SELECT tgname FROM pg_trigger "
                                "WHERE tgrelid = 'memory_chunks'::regclass AND NOT tgisinternal"
                            )
                        )
                    ).scalars()
                )
                assert "trg_memory_chunk_locator_projection_events_v2" not in triggers
                assert "trg_memory_chunk_locator_profile_events_v2" in triggers

                retired = tuple(
                    (
                        await connection.execute(
                            text(
                                "SELECT status, last_safe_diagnostic_code FROM memory_outbox "
                                "WHERE aggregate_type = 'locator_chunk' ORDER BY id"
                            )
                        )
                    ).all()
                )
                assert retired
                assert set(retired) == {("done", "retrieval.legacy_projection_retired")}

                current_before = int(
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM memory_outbox WHERE event_type LIKE "
                            "'vector.%_locator_profile'"
                        )
                    )
                    or 0
                )
                if starting_migration == "0039_":
                    await connection.execute(
                        text(
                            "INSERT INTO memory_locator_profiles ("
                            "profile_id, generation, profile_digest, collection_name, state, "
                            "backfill_complete, canonical_watermark, projected_watermark, "
                            "expected_count, projected_count, expected_digest, projected_digest, "
                            "created_at) VALUES ("
                            "'profile-cutover', 'generation-cutover', :profile_digest, "
                            "'retrieval_cutover', 'building', FALSE, 0, 0, 0, 0, "
                            ":empty_digest, :empty_digest, now())"
                        ),
                        {
                            "profile_digest": "a" * 64,
                            "empty_digest": (
                                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                            ),
                        },
                    )
                await connection.execute(
                    text(
                        "UPDATE memory_chunks SET classification = 'internal' "
                        "WHERE id = 'chunk-cutover'"
                    )
                )
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM memory_outbox WHERE event_type LIKE "
                            "'vector.%_locator_profile'"
                        )
                    )
                    == current_before + 1
                )
                assert await connection.scalar(
                    text(
                        "SELECT count(*) FROM memory_outbox WHERE aggregate_type = 'locator_chunk'"
                    )
                ) == len(retired)
            assert (await upgrade_schema(engine)).applied == ()
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _assert_running_work_refusal_and_idempotence(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="retrieval_cutover_running", asyncpg=asyncpg
    )
    await database.recreate()
    try:
        await _install_versioned_schema_through(database, "0050_")
        connection = await database.connect()
        try:
            await connection.execute(
                """
                INSERT INTO memory_outbox (
                    message_key, event_type, aggregate_type, aggregate_id,
                    aggregate_version, workload_class, fairness_key, payload_json,
                    status, attempt_count, next_attempt_at, created_at, updated_at
                ) VALUES (
                    'late-legacy-running', 'vector.delete_chunks', 'locator_chunk',
                    'chunk-running', 5, 'projection', 'chunk:chunk-running',
                    '{"chunk_ids":["chunk-running"]}'::jsonb,
                    'running', 0, now(), now(), now()
                )
                """
            )
            migration = Path(__file__).resolve().parents[2] / (
                "packages/infinity_context_adapters/infinity_context_adapters/postgres/"
                "migrations/0053_retrieval_default_lifecycle.sql"
            )
            with pytest.raises(Exception, match="running events to drain"):
                async with connection.transaction():
                    await connection.execute(migration.read_text())

            await connection.execute(
                "UPDATE memory_outbox SET status='done' WHERE message_key='late-legacy-running'"
            )
            async with connection.transaction():
                await connection.execute(migration.read_text())
            async with connection.transaction():
                await connection.execute(migration.read_text())
            assert (
                await connection.fetchval(
                    "SELECT to_regclass('memory_locator_projection_tombstones')"
                )
                is None
            )
        finally:
            await connection.close()
    finally:
        await database.drop()


async def _seed_profile(connection) -> None:
    empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    await connection.execute(
        """
        INSERT INTO memory_locator_profiles (
            profile_id, generation, profile_digest, collection_name, state,
            backfill_complete, canonical_watermark, projected_watermark,
            expected_count, projected_count, expected_digest, projected_digest,
            created_at
        ) VALUES (
            'profile-cutover', 'generation-cutover', $1, 'retrieval_cutover', 'building',
            FALSE, 0, 0, 0, 0, $2, $2, now()
        )
        """,
        "a" * 64,
        empty,
    )


async def _install_staged_watermark(connection) -> None:
    await connection.execute(
        """
        CREATE SEQUENCE memory_locator_commit_watermark_seq START 1;
        ALTER TABLE memory_chunks
          ADD COLUMN retrieval_commit_watermark BIGINT NOT NULL
          DEFAULT nextval('memory_locator_commit_watermark_seq');
        """
    )


async def _seed_chunk_and_queued_events(connection) -> None:
    await connection.execute(
        """
        INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at)
        VALUES ('space-cutover', 'space-cutover', 'Cutover', 'active', now(), now());
        INSERT INTO memory_scopes
          (id, space_id, external_ref, name, status, created_at, updated_at)
        VALUES ('scope-cutover', 'space-cutover', 'scope-cutover', 'Cutover',
                'active', now(), now());
        INSERT INTO memory_documents
          (id, space_id, memory_scope_id, thread_id, title, source_type,
           source_external_id, content_hash, classification, status,
           retrieval_projected, created_at, updated_at)
        VALUES ('document-cutover', 'space-cutover', 'scope-cutover', NULL,
                'Document', 'file', 'document.txt', repeat('a', 64), 'internal',
                'active', TRUE, now(), now());
        INSERT INTO memory_chunks
          (id, space_id, memory_scope_id, thread_id, document_id, episode_id,
           source_type, source_external_id, source_hash, kind, text,
           normalized_text, status, sequence, char_start, char_end,
           token_estimate, classification, created_at, updated_at, metadata_json,
           retrieval_locator, retrieval_source_key, retrieval_projection_generation,
           retrieval_sequence_ordinal, retrieval_kind, retrieval_category)
        VALUES ('chunk-cutover', 'space-cutover', 'scope-cutover', NULL,
                'document-cutover', NULL, 'file', 'document.txt', repeat('b', 64),
                'paragraph', 'Version four', 'version four', 'active', 0, 0, 12, 2,
                'internal', now(), now(), '{}'::jsonb, 'cutover/0', 'document.txt',
                'generation-cutover', 0, 'record', 'decision');
        UPDATE memory_chunks SET text = 'Version five' WHERE id = 'chunk-cutover';
        UPDATE memory_chunks SET classification = 'restricted' WHERE id = 'chunk-cutover';
        """
    )


__all__ = ()
