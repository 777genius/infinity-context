"""Real PostgreSQL proof for Retrieval maximum-safe version transit."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_session_factory,
    upgrade_schema,
)
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryLocatorProfileRow,
    MemoryLocatorProfileTombstoneRow,
    MemoryScopeRow,
    MemorySpaceRow,
)
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow
from infinity_context_adapters.postgres.repositories import PostgresChunkRepository
from infinity_context_core.domain.entities import MemoryChunkKind
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import select, text

MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991
WHEN = datetime(2026, 1, 1, tzinfo=UTC)
EMPTY_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_maximum_safe_version_round_trips_through_real_postgres_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_scenario(database_url))


async def _scenario(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="retrieval_transit", asyncpg=asyncpg
    )
    await database.recreate()
    try:
        engine = build_async_engine(database.app_url)
        try:
            upgraded = await upgrade_schema(engine)
            assert upgraded.applied[-16:] == (
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
            )
            await _assert_transit_column_types(engine)

            sessions = build_session_factory(engine)
            async with sessions() as session, session.begin():
                await _seed_authority(session)
                await session.execute(
                    text(
                        "ALTER TABLE memory_chunks DISABLE TRIGGER "
                        "trg_memory_chunk_retrieval_fence_v2"
                    )
                )
                session.add(_maximum_deleted_chunk())
                await session.flush()
                await session.execute(
                    text(
                        "ALTER TABLE memory_chunks ENABLE TRIGGER "
                        "trg_memory_chunk_retrieval_fence_v2"
                    )
                )
                await session.execute(
                    text(
                        "UPDATE memory_chunks SET classification = 'restricted' "
                        "WHERE id = 'chunk-max'"
                    )
                )

            async with sessions() as session:
                chunk = await PostgresChunkRepository(session).get_by_id("chunk-max")
                assert chunk is not None
                assert (
                    chunk.metadata["_canonical_retrieval_projection"]["canonical_version"]
                    == MAX_SAFE_JSON_INTEGER
                )
                tombstone = await session.get(
                    MemoryLocatorProfileTombstoneRow, ("profile-max", "chunk-max")
                )
                outbox = (
                    await session.execute(
                        select(MemoryOutboxRow).where(
                            MemoryOutboxRow.event_type == "vector.delete_locator_profile",
                            MemoryOutboxRow.aggregate_id == "chunk-max",
                        )
                    )
                ).scalar_one()
                assert tombstone is not None
                assert tombstone.canonical_version == MAX_SAFE_JSON_INTEGER
                assert outbox.aggregate_version == MAX_SAFE_JSON_INTEGER
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _assert_transit_column_types(engine) -> None:
    expected = {
        ("memory_chunks", "retrieval_version"),
        ("memory_locator_profile_tombstones", "canonical_version"),
        ("memory_outbox", "aggregate_version"),
        ("memory_projection_result_receipts", "aggregate_version"),
    }
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT table_name, column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND (table_name, column_name) IN (
                        ('memory_chunks', 'retrieval_version'),
                        ('memory_locator_profile_tombstones', 'canonical_version'),
                        ('memory_outbox', 'aggregate_version'),
                        ('memory_projection_result_receipts', 'aggregate_version')
                      )
                    """
                )
            )
        ).all()
    assert {(row.table_name, row.column_name) for row in rows} == expected
    assert {row.data_type for row in rows} == {"bigint"}


async def _seed_authority(session) -> None:
    session.add(
        MemorySpaceRow(
            id="space-max",
            slug="space-max",
            name="Maximum Version Space",
            status="active",
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    await session.flush()
    session.add(
        MemoryScopeRow(
            id="scope-max",
            space_id="space-max",
            external_ref="scope-max",
            name="Maximum Version Scope",
            status="active",
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    await session.flush()
    session.add_all(
        (
            MemoryDocumentRow(
                id="document-max",
                space_id="space-max",
                memory_scope_id="scope-max",
                thread_id=None,
                title="Maximum Version Document",
                source_type="file",
                source_external_id="maximum-version.txt",
                content_hash="a" * 64,
                classification="internal",
                status="active",
                retrieval_projected=True,
                created_at=WHEN,
                updated_at=WHEN,
            ),
            MemoryLocatorProfileRow(
                profile_id="profile-max",
                generation="generation-max",
                profile_digest="3" * 64,
                collection_name="retrieval_max",
                state="building",
                backfill_cursor=None,
                backfill_complete=False,
                canonical_watermark=0,
                projected_watermark=0,
                expected_count=0,
                projected_count=0,
                expected_digest=EMPTY_DIGEST,
                projected_digest=EMPTY_DIGEST,
                created_at=WHEN,
            ),
        )
    )
    await session.flush()


def _maximum_deleted_chunk() -> MemoryChunkRow:
    return MemoryChunkRow(
        id="chunk-max",
        space_id="space-max",
        memory_scope_id="scope-max",
        thread_id=None,
        document_id="document-max",
        episode_id=None,
        source_type="document",
        source_external_id="maximum-version.txt",
        source_hash="b" * 64,
        kind=MemoryChunkKind.DOCUMENT_SECTION.value,
        text="Maximum safe version transit proof.",
        normalized_text="maximum safe version transit proof.",
        status="active",
        sequence=0,
        char_start=0,
        char_end=35,
        token_estimate=6,
        classification="internal",
        created_at=WHEN,
        updated_at=WHEN,
        metadata_json={},
        retrieval_locator="retrieval-max",
        retrieval_source_key="source-max",
        retrieval_projection_generation="generation-max",
        retrieval_sequence_ordinal=0,
        retrieval_kind="record",
        retrieval_version=MAX_SAFE_JSON_INTEGER - 1,
        retrieval_actor_keys_json=[],
        retrieval_start_at=None,
        retrieval_end_at=None,
        retrieval_relative_start_ms=None,
        retrieval_relative_end_ms=None,
        retrieval_category="decision",
        retrieval_tags_json=[],
    )
