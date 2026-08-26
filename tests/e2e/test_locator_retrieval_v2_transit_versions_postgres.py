"""Real PostgreSQL proof for Retrieval V2 maximum-safe version transit."""

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
from infinity_context_adapters.postgres.benchmark_run_models import (
    MemoryComparisonBenchmarkRunRow,
)
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryLocatorProjectionTombstoneRow,
    MemoryScopeRow,
    MemorySpaceRow,
)
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow
from infinity_context_adapters.postgres.projection_receipt_models import (
    MemoryCleanupV3ContextAuthorityRow,
    MemoryProjectionResultReceiptRow,
)
from infinity_context_adapters.postgres.repositories import PostgresChunkRepository
from infinity_context_core.domain.entities import MemoryChunkKind
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import select, text
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through

MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991
WHEN = datetime(2026, 1, 1, tzinfo=UTC)
RUN_ID = "1" * 64
CONTEXT_ID = "2" * 64


def test_maximum_safe_version_round_trips_through_real_postgres_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_scenario(database_url))


async def _scenario(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="locator_v2_transit",
        asyncpg=asyncpg,
    )
    await database.recreate()
    try:
        await _install_versioned_schema_through(database, "0038_")
        engine = build_async_engine(database.app_url)
        try:
            upgraded = await upgrade_schema(engine)
            assert upgraded.applied == (
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
            )
            await _assert_transit_column_types(engine)

            sessions = build_session_factory(engine)
            async with sessions() as session, session.begin():
                await _seed_receipt_authority(session)

                # Retrieval versions normally start at one. Disabling only the version
                # fence lets this boundary fixture start at the contract maximum while
                # leaving the real projection-event trigger enabled.
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

                outbox = (
                    await session.execute(
                        select(MemoryOutboxRow).where(
                            MemoryOutboxRow.message_key
                            == f"locator-v2-tombstone:chunk-max:{MAX_SAFE_JSON_INTEGER}"
                        )
                    )
                ).scalar_one()
                session.add(_maximum_receipt(outbox.id))

            async with sessions() as session:
                chunk = await PostgresChunkRepository(session).get_by_id("chunk-max")
                assert chunk is not None
                assert (
                    chunk.metadata["_canonical_retrieval_projection"]["canonical_version"]
                    == MAX_SAFE_JSON_INTEGER
                )

                tombstone = await session.get(
                    MemoryLocatorProjectionTombstoneRow,
                    "chunk-max",
                )
                outbox = (
                    await session.execute(
                        select(MemoryOutboxRow).where(MemoryOutboxRow.aggregate_id == "chunk-max")
                    )
                ).scalar_one()
                receipt = await session.get(MemoryProjectionResultReceiptRow, outbox.id)

                assert tombstone is not None
                assert tombstone.canonical_version == MAX_SAFE_JSON_INTEGER
                assert outbox.aggregate_version == MAX_SAFE_JSON_INTEGER
                assert receipt is not None
                assert receipt.aggregate_version == MAX_SAFE_JSON_INTEGER
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _assert_transit_column_types(engine) -> None:
    expected = {
        ("memory_chunks", "retrieval_version"),
        ("memory_locator_projection_tombstones", "canonical_version"),
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
                        ('memory_locator_projection_tombstones', 'canonical_version'),
                        ('memory_outbox', 'aggregate_version'),
                        ('memory_projection_result_receipts', 'aggregate_version')
                      )
                    """
                )
            )
        ).all()
    assert {(row.table_name, row.column_name) for row in rows} == expected
    assert {row.data_type for row in rows} == {"bigint"}


async def _seed_receipt_authority(session) -> None:
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
            MemoryComparisonBenchmarkRunRow(
                run_id_sha256=RUN_ID,
                binding_commitment_sha256="3" * 64,
                infinity_target_identity_sha256="4" * 64,
                space_id="space-max",
                space_slug="space-max",
                idempotency_key_sha256="5" * 64,
                registration_fingerprint_sha256="6" * 64,
                state="active",
                cleanup_plan_json={},
                cleanup_plan_sha256="7" * 64,
                cleanup_plan_state="sealed",
                projection_manifest_json=None,
                projection_manifest_sha256=None,
                projection_cleanup_state="unsealed",
                cleanup_fingerprint_sha256=None,
                cleanup_receipt_json=None,
                finalization_fingerprint_sha256=None,
                completion_receipt_json=None,
                completed_at=None,
                created_at=WHEN,
                updated_at=WHEN,
            ),
        )
    )
    await session.flush()
    session.add(
        MemoryCleanupV3ContextAuthorityRow(
            run_id_sha256=RUN_ID,
            context_sha256=CONTEXT_ID,
            authority_terminal_sha256="8" * 64,
            context_json={},
            authority_json={},
            registration_sha256="9" * 64,
            registration_mac_sha256="a" * 64,
            registered_at=WHEN,
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
        status="deleted",
        sequence=0,
        char_start=0,
        char_end=35,
        token_estimate=6,
        classification="internal",
        created_at=WHEN,
        updated_at=WHEN,
        metadata_json={},
        retrieval_locator="locator-max",
        retrieval_source_key="source-max",
        retrieval_projection_generation="generation-max",
        retrieval_sequence_ordinal=0,
        retrieval_kind="record",
        retrieval_version=MAX_SAFE_JSON_INTEGER,
        retrieval_actor_keys_json=[],
        retrieval_start_at=None,
        retrieval_end_at=None,
        retrieval_relative_start_ms=None,
        retrieval_relative_end_ms=None,
        retrieval_category="decision",
        retrieval_tags_json=[],
    )


def _maximum_receipt(outbox_id: int) -> MemoryProjectionResultReceiptRow:
    return MemoryProjectionResultReceiptRow(
        outbox_id=outbox_id,
        run_id_sha256=RUN_ID,
        context_sha256=CONTEXT_ID,
        lane="qdrant",
        operation="delete",
        result_state="absent",
        space_id="space-max",
        memory_scope_id="scope-max",
        thread_id=None,
        aggregate_type="locator_chunk",
        aggregate_id="chunk-max",
        aggregate_version=MAX_SAFE_JSON_INTEGER,
        target_authority_sha256="b" * 64,
        worker_authority_sha256="c" * 64,
        outbox_event_commitment_sha256="d" * 64,
        identity_count=1,
        ordered_identity_root_sha256="e" * 64,
        lineage_root_sha256="f" * 64,
        provider_completed_at=WHEN,
        persisted_at=WHEN,
        receipt_sha256="0" * 64,
        receipt_mac_sha256="1" * 64,
    )
