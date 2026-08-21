"""Real PostgreSQL proof for the focused cleanup-plan 0033 upgrade."""

import asyncio
import os
from hashlib import sha256

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from test_postgres_schema_upgrade_e2e import (
    _MIGRATIONS,
    _install_versioned_schema_through,
)


def test_cleanup_plan_upgrade_couples_legacy_and_v2_rows_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_cleanup_plan_upgrade(database_url))


async def _assert_cleanup_plan_upgrade(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    try:
        database = PostgresTestDatabase.from_url(
            database_url,
            prefix="cleanup_plan_upgrade",
            asyncpg=asyncpg,
        )
    except ValueError:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")
    try:
        await database.recreate()
        await _install_versioned_schema_through(database, "0032_")
        await _seed_legacy_benchmark_run(database)
        engine = build_async_engine(database.app_url)
        try:
            upgrade = await upgrade_schema(engine)
            assert upgrade.applied == (
                "0033_benchmark_cleanup_plan",
                "0034_benchmark_generated_tombstone_fence",
                "0035_projection_result_receipts",
                "0036_memory_comparison_strict_v4_preparations",
                "0037_strict_v4_fact_writer",
                "0038_strict_v4_document_writer",
            )
            await _assert_cleanup_plan_schema(engine)
            await _assert_projection_receipt_schema(engine)
            await _assert_cleanup_plan_coupling(engine)
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _seed_legacy_benchmark_run(database: PostgresTestDatabase) -> None:
    raw = await database.connect()
    try:
        await raw.execute(
            """
            INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at)
            VALUES ('benchmark-space-legacy', 'benchmark-legacy', 'Legacy', 'active',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        await raw.execute(
            """
            INSERT INTO memory_comparison_benchmark_runs (
                run_id_sha256, binding_commitment_sha256,
                infinity_target_identity_sha256, space_id, space_slug,
                idempotency_key_sha256, registration_fingerprint_sha256,
                state, created_at, updated_at
            ) VALUES ($1, $2, $3, 'benchmark-space-legacy', 'benchmark-legacy',
                      $4, $5, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "d" * 64,
            "e" * 64,
        )
    finally:
        await raw.close()


async def _assert_cleanup_plan_schema(engine) -> None:
    async with engine.connect() as connection:
        migration_history = (
            await connection.execute(
                text(
                    "SELECT migration_id, checksum "
                    "FROM infinity_context_schema_migrations ORDER BY migration_id"
                )
            )
        ).all()
        assert migration_history == [
            (path.stem, sha256(path.read_bytes()).hexdigest())
            for path in sorted(_MIGRATIONS.glob("*.sql"))
        ]
        columns = set(
            (
                await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() "
                        "AND table_name = 'memory_comparison_benchmark_runs'"
                    )
                )
            ).scalars()
        )
        assert {"cleanup_plan_json", "cleanup_plan_sha256", "cleanup_plan_state"} <= columns
        data_type = await connection.scalar(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'memory_comparison_benchmark_runs' "
                "AND column_name = 'cleanup_plan_json'"
            )
        )
        assert data_type == "jsonb"


async def _assert_projection_receipt_schema(engine) -> None:
    expected_columns = {
        "memory_cleanup_v3_context_authorities": {
            "run_id_sha256",
            "context_sha256",
            "authority_terminal_sha256",
            "context_json",
            "authority_json",
            "registration_sha256",
            "registration_mac_sha256",
            "registered_at",
        },
        "memory_projection_receipt_claims": {
            "outbox_id",
            "run_id_sha256",
            "context_sha256",
            "worker_authority_sha256",
            "projection_key_sha256",
            "operation",
            "expected_identities_sha256",
            "claim_token_sha256",
            "generation",
            "state",
            "lease_expires_at",
            "created_at",
            "updated_at",
        },
        "memory_projection_result_receipts": {
            "outbox_id",
            "run_id_sha256",
            "context_sha256",
            "lane",
            "operation",
            "result_state",
            "space_id",
            "memory_scope_id",
            "thread_id",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            "target_authority_sha256",
            "worker_authority_sha256",
            "outbox_event_commitment_sha256",
            "identity_count",
            "ordered_identity_root_sha256",
            "lineage_root_sha256",
            "provider_completed_at",
            "persisted_at",
            "receipt_sha256",
            "receipt_mac_sha256",
        },
        "memory_projection_target_identities": {
            "run_id_sha256",
            "kind",
            "identity_sha256",
            "identity_commitment_sha256",
            "canonical_source_id",
            "physical_identity",
            "lineage_root_sha256",
            "target_authority_sha256",
            "identity_mac_sha256",
            "created_at",
        },
        "memory_projection_receipt_identity_links": {
            "outbox_id",
            "run_id_sha256",
            "kind",
            "identity_sha256",
            "identity_commitment_sha256",
            "ordinal",
        },
    }
    async with engine.connect() as connection:
        for table_name, columns in expected_columns.items():
            observed = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND table_name = :table_name"
                        ),
                        {"table_name": table_name},
                    )
                ).scalars()
            )
            assert observed == columns
        constraints = set(
            (
                await connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE connamespace = current_schema()::regnamespace "
                        "AND conrelid IN ("
                        "'memory_cleanup_v3_context_authorities'::regclass, "
                        "'memory_projection_receipt_claims'::regclass, "
                        "'memory_projection_result_receipts'::regclass, "
                        "'memory_projection_target_identities'::regclass, "
                        "'memory_projection_receipt_identity_links'::regclass)"
                    )
                )
            ).scalars()
        )
    assert {
        "uq_cleanup_v3_context_authority_run_context",
        "ck_projection_context_authority_digests",
        "fk_projection_receipt_claim_context",
        "ck_projection_receipt_claim_digests",
        "ck_projection_receipt_claim_state",
        "fk_projection_receipt_context_authority",
        "ck_projection_receipt_identity_count",
        "ck_projection_receipt_lane",
        "ck_projection_receipt_operation",
        "ck_projection_receipt_result_state",
        "ck_projection_receipt_operation_result",
        "ck_projection_receipt_digests",
        "uq_projection_receipt_outbox_run",
        "uq_projection_receipt_canonical_job",
        "ck_projection_identity_physical_value",
        "ck_projection_identity_digests",
        "ck_projection_identity_kind",
        "uq_projection_identity_authenticated",
        "fk_projection_receipt_link_identity",
        "fk_projection_receipt_link_receipt",
        "ck_projection_receipt_link_ordinal",
        "ck_projection_receipt_link_digests",
        "uq_projection_receipt_link_ordinal",
    } <= constraints


async def _assert_cleanup_plan_coupling(engine) -> None:
    async with engine.begin() as connection:
        legacy = (
            await connection.execute(
                text(
                    "SELECT cleanup_plan_json, cleanup_plan_sha256, cleanup_plan_state "
                    "FROM memory_comparison_benchmark_runs WHERE run_id_sha256 = :run_id"
                ),
                {"run_id": "a" * 64},
            )
        ).one()
        assert legacy == (None, None, "recovery_blocked")
        await connection.execute(
            text(
                """
                INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at)
                VALUES ('benchmark-space-v2', 'benchmark-v2', 'V2', 'active',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO memory_comparison_benchmark_runs (
                    run_id_sha256, binding_commitment_sha256,
                    infinity_target_identity_sha256, space_id, space_slug,
                    idempotency_key_sha256, registration_fingerprint_sha256,
                    state, cleanup_plan_json, cleanup_plan_sha256, cleanup_plan_state,
                    created_at, updated_at
                ) VALUES (:run_id, :binding, :target, 'benchmark-space-v2',
                          'benchmark-v2', :key, :fingerprint, 'active',
                          CAST(:plan AS JSONB), :plan_sha, 'sealed',
                          CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {
                "run_id": "1" * 64,
                "binding": "2" * 64,
                "target": "3" * 64,
                "key": "4" * 64,
                "fingerprint": "5" * 64,
                "plan": "{}",
                "plan_sha": "6" * 64,
            },
        )
        sealed = (
            await connection.execute(
                text(
                    "SELECT cleanup_plan_json IS NOT NULL, cleanup_plan_sha256, "
                    "cleanup_plan_state FROM memory_comparison_benchmark_runs "
                    "WHERE run_id_sha256 = :run_id"
                ),
                {"run_id": "1" * 64},
            )
        ).one()
        assert sealed == (True, "6" * 64, "sealed")
