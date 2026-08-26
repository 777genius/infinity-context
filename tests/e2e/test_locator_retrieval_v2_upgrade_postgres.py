"""Seeded executable proof for the 0038 -> 0039 locator migration."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_locator_retrieval_indexes,
    build_session_factory,
    upgrade_schema,
)
from infinity_context_adapters.postgres.locator_projection_maintenance import (
    PostgresLocatorProjectionMaintenance,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through


def test_seeded_locator_upgrade_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_seeded_upgrade(database_url))


async def _assert_seeded_upgrade(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="locator_v2_upgrade", asyncpg=asyncpg
    )
    try:
        await database.recreate()
        await _install_versioned_schema_through(database, "0038_")
        raw = await database.connect()
        try:
            await raw.execute(
                """
                INSERT INTO memory_spaces
                  (id, slug, name, status, created_at, updated_at)
                VALUES ('space-a', 'space-a', 'Space A', 'active', now(), now());
                INSERT INTO memory_scopes
                  (id, space_id, external_ref, name, status, created_at, updated_at)
                VALUES ('scope-a', 'space-a', 'scope-a', 'Scope A',
                        'active', now(), now());
                INSERT INTO memory_documents
                  (id, space_id, memory_scope_id, thread_id, title, source_type,
                   source_external_id, content_hash, classification, status,
                   created_at, updated_at)
                VALUES ('document-canonical-a', 'space-a', 'scope-a', NULL,
                        'Document', 'file', 'guessable-name.txt', repeat('a', 64),
                        'internal', 'active', now(), now());
                INSERT INTO memory_chunks
                  (id, space_id, memory_scope_id, thread_id, document_id, episode_id,
                   source_type, source_external_id, source_hash, kind, text,
                   normalized_text, status, sequence, char_start, char_end,
                   token_estimate, classification, created_at, updated_at, metadata_json)
                VALUES ('chunk-canonical-a', 'space-a', 'scope-a', NULL,
                        'document-canonical-a', NULL, 'file', 'guessable-name.txt',
                        repeat('b', 64), 'paragraph', 'First text', 'first text',
                        'active', 0, 0, 10, 2, 'internal', now(), now(), '{}'::jsonb)
                """
            )
        finally:
            await raw.close()
        engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(engine)
            assert result.applied == (
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
                )
            assert len(await build_locator_retrieval_indexes(engine)) == 4
            assert len(await build_locator_retrieval_indexes(engine)) == 4
            async with engine.begin() as connection:
                row = (
                    await connection.execute(
                        text(
                            """
                            SELECT retrieval_locator, retrieval_source_key,
                                   retrieval_projection_generation, retrieval_version
                            FROM memory_chunks WHERE id = 'chunk-canonical-a'
                            """
                        )
                    )
                ).one()
                assert tuple(row) == (None, None, None, 1)
                rebuilds = await connection.scalar(
                    text(
                        "SELECT count(*) FROM memory_outbox "
                        "WHERE aggregate_id = 'chunk-canonical-a'"
                    )
                )
                assert rebuilds == 0
                await connection.execute(
                    text(
                        "UPDATE memory_chunks SET retrieval_locator = 'caller-locator', "
                        "retrieval_source_key = 'caller-source', "
                        "retrieval_projection_generation = 'caller-generation', "
                        "retrieval_sequence_ordinal = 7, retrieval_kind = 'record', "
                        "retrieval_category = 'decision' "
                        "WHERE id = 'chunk-canonical-a'"
                    )
                )
                assert (
                    await connection.scalar(
                        text(
                            "SELECT retrieval_version FROM memory_chunks "
                            "WHERE id = 'chunk-canonical-a'"
                        )
                    )
                    == 2
                )
                await connection.execute(
                    text(
                        "UPDATE memory_chunks SET text = 'Second text' "
                        "WHERE id = 'chunk-canonical-a'"
                    )
                )
                await connection.execute(
                    text(
                        "UPDATE memory_chunks SET classification = 'restricted' "
                        "WHERE id = 'chunk-canonical-a'"
                    )
                )
                tombstone = (
                    await connection.execute(
                        text(
                            "SELECT canonical_version, legacy_deleted_at, locator_deleted_at "
                            "FROM memory_locator_projection_tombstones "
                            "WHERE chunk_id = 'chunk-canonical-a'"
                        )
                    )
                ).one()
                assert tuple(tombstone) == (4, None, None)
                await connection.execute(
                    text(
                        "UPDATE memory_locator_projection_tombstones SET "
                        "legacy_deleted_at = CURRENT_TIMESTAMP, "
                        "locator_deleted_at = CURRENT_TIMESTAMP "
                        "WHERE chunk_id = 'chunk-canonical-a'"
                    )
                )
                tombstone_jobs = await connection.scalar(
                    text(
                        "SELECT count(*) FROM memory_outbox WHERE message_key LIKE "
                        "'locator-v2-tombstone:chunk-canonical-a:%'"
                    )
                )
                await connection.execute(
                    text(
                        "UPDATE memory_chunks SET updated_at = CURRENT_TIMESTAMP "
                        "WHERE id = 'chunk-canonical-a'"
                    )
                )
                preserved = (
                    await connection.execute(
                        text(
                            "SELECT canonical_version, legacy_deleted_at IS NOT NULL, "
                            "locator_deleted_at IS NOT NULL "
                            "FROM memory_locator_projection_tombstones "
                            "WHERE chunk_id = 'chunk-canonical-a'"
                        )
                    )
                ).one()
                assert tuple(preserved) == (4, True, True)
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM memory_outbox WHERE message_key LIKE "
                            "'locator-v2-tombstone:chunk-canonical-a:%'"
                        )
                    )
                    == tombstone_jobs
                )
                await connection.execute(
                    text(
                        "UPDATE memory_chunks SET text = 'Later non-visible version' "
                        "WHERE id = 'chunk-canonical-a'"
                    )
                )
                reset = (
                    await connection.execute(
                        text(
                            "SELECT canonical_version, legacy_deleted_at, locator_deleted_at "
                            "FROM memory_locator_projection_tombstones "
                            "WHERE chunk_id = 'chunk-canonical-a'"
                        )
                    )
                ).one()
                assert tuple(reset) == (5, None, None)
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM memory_outbox WHERE message_key = "
                            "'locator-v2-tombstone:chunk-canonical-a:5'"
                        )
                    )
                    == 1
                )
            maintenance = PostgresLocatorProjectionMaintenance(build_session_factory(engine))
            assert await maintenance.current_delete_ids(
                ("chunk-canonical-a",), canonical_version=5
            ) == ("chunk-canonical-a",)
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE memory_chunks SET classification = 'internal' "
                        "WHERE id = 'chunk-canonical-a'"
                    )
                )
            assert (
                await maintenance.current_delete_ids(("chunk-canonical-a",), canonical_version=5)
                == ()
            )
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE memory_chunks SET classification = 'restricted' "
                        "WHERE id = 'chunk-canonical-a'"
                    )
                )
            await maintenance.mark_deleted(
                "locator",
                ("chunk-canonical-a",),
                completed_at=datetime(2026, 1, 1, tzinfo=UTC),
                canonical_version=6,
            )
            async with engine.connect() as connection:
                assert await connection.scalar(
                    text(
                        "SELECT locator_deleted_at IS NULL "
                        "FROM memory_locator_projection_tombstones "
                        "WHERE chunk_id = 'chunk-canonical-a'"
                    )
                )
            assert (await upgrade_schema(engine)).applied == ()
        finally:
            await engine.dispose()
    finally:
        await database.drop()
