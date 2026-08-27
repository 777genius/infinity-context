"""Populated 0048 -> 0049 reconciliation provenance upgrade proof."""

from __future__ import annotations

import asyncio
import os

import pytest
from infinity_context_adapters.postgres import (
    build_async_engine,
    preflight_reconciliation_0049,
    upgrade_schema,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through


def test_populated_reconciliation_0049_upgrade_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_populated_upgrade(database_url))


def test_competing_current_generation_0049_upgrade_is_refused() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_competing_upgrade_refused(database_url))


async def _assert_populated_upgrade(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="reconciliation_0049_populated", asyncpg=asyncpg
    )
    await database.recreate()
    try:
        await _install_versioned_schema_through(database, "0048_")
        raw = await database.connect()
        try:
            await raw.execute(
                """
                INSERT INTO memory_locator_profiles
                  (profile_id,generation,profile_digest,collection_name,state,created_at)
                VALUES ('legacy-active','profile-generation',repeat('a',64),
                        'legacy-collection','active',CURRENT_TIMESTAMP);
                INSERT INTO memory_locator_runtime_incarnations
                  (instance_id,generation,registered_at,last_seen_at,
                   acknowledged_generation,supervisor_key_id,supervisor_public_key,
                   trust_root_sha256,trust_registry_generation,launch_token,process_pid,
                   process_birth_identity,executable_identity,executable_sha256,
                   launch_identity_sha256,release_revision,release_source_tree_sha256,
                   release_installed_distribution_sha256,release_runtime_modules_sha256,
                   release_identity_sha256)
                VALUES ('legacy-runtime','runtime-generation',CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP,0,'legacy-unrecoverable',repeat('0',64),
                        repeat('0',64),0,'legacy-launch',1,'legacy-birth','/legacy/runtime',
                        repeat('0',64),repeat('0',64),repeat('0',40),
                        'sha256:'||repeat('0',64),'sha256:'||repeat('0',64),
                        'sha256:'||repeat('0',64),repeat('0',64));
                INSERT INTO memory_locator_profile_reconciliation_operations
                  (profile_id,operation_id,predecessor_generation,predecessor_drifted,
                   created_at)
                VALUES ('legacy-active','legacy-operation','profile-generation',TRUE,
                        CURRENT_TIMESTAMP);
                INSERT INTO memory_locator_profile_transition_audit
                  (profile_id,lease_id,evidence_digest,runtime_instance_id,
                   runtime_generation,lifecycle_identity_sha256,occurred_at)
                VALUES ('legacy-active','legacy-lease',repeat('0',64),'legacy-runtime',
                        'runtime-generation',repeat('0',64),CURRENT_TIMESTAMP)
                """
            )
        finally:
            await raw.close()

        engine = build_async_engine(database.app_url)
        try:
            preflight = await preflight_reconciliation_0049(engine)
            assert preflight.status == "ready"
            assert preflight.upgrade_safe is True
            result = await upgrade_schema(engine)
            assert result.applied == (
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
            async with engine.connect() as connection:
                legacy_operation = (
                    await connection.execute(
                        text(
                            "SELECT runtime_instance_id,runtime_generation,"
                            "lifecycle_identity_sha256 FROM "
                            "memory_locator_profile_reconciliation_operations "
                            "WHERE operation_id='legacy-operation'"
                        )
                    )
                ).one()
                assert tuple(legacy_operation) == (None, None, None)
                audit = (
                    await connection.execute(
                        text(
                            "SELECT operation,lease_issued_at,lease_expires_at,"
                            "requested_expires_at,mutation_epoch,reconciliation_drifted "
                            "FROM memory_locator_profile_transition_audit "
                            "WHERE lease_id='legacy-lease'"
                        )
                    )
                ).one()
                assert tuple(audit) == ("activation", None, None, None, None, None)
            with pytest.raises(Exception, match="uq_locator_runtime_current_instance"):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO memory_locator_runtime_incarnations "
                            "(instance_id,generation,registered_at,last_seen_at,"
                            "acknowledged_generation,supervisor_key_id,supervisor_public_key,"
                            "trust_root_sha256,trust_registry_generation,launch_token,process_pid,"
                            "process_birth_identity,executable_identity,executable_sha256,"
                            "launch_identity_sha256,release_revision,release_source_tree_sha256,"
                            "release_installed_distribution_sha256,"
                            "release_runtime_modules_sha256,release_identity_sha256) SELECT "
                            "instance_id,'competing-generation',registered_at,last_seen_at,"
                            "acknowledged_generation,supervisor_key_id,supervisor_public_key,"
                            "trust_root_sha256,trust_registry_generation,'competing-launch',"
                            "process_pid,process_birth_identity,executable_identity,"
                            "executable_sha256,launch_identity_sha256,release_revision,"
                            "release_source_tree_sha256,release_installed_distribution_sha256,"
                            "release_runtime_modules_sha256,release_identity_sha256 "
                            "FROM memory_locator_runtime_incarnations "
                            "WHERE instance_id='legacy-runtime'"
                        )
                    )
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _assert_competing_upgrade_refused(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="reconciliation_0049_competing", asyncpg=asyncpg
    )
    await database.recreate()
    try:
        await _install_versioned_schema_through(database, "0048_")
        raw = await database.connect()
        try:
            await raw.execute(
                """
                INSERT INTO memory_locator_runtime_incarnations
                  (instance_id,generation,registered_at,last_seen_at,
                   acknowledged_generation,supervisor_key_id,supervisor_public_key,
                   trust_root_sha256,trust_registry_generation,launch_token,process_pid,
                   process_birth_identity,executable_identity,executable_sha256,
                   launch_identity_sha256,release_revision,release_source_tree_sha256,
                   release_installed_distribution_sha256,release_runtime_modules_sha256,
                   release_identity_sha256)
                VALUES
                  ('competing-runtime','generation-a',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,
                   0,'legacy-unrecoverable',repeat('0',64),repeat('0',64),0,'launch-a',1,
                   'legacy-birth','/legacy/runtime',repeat('0',64),repeat('0',64),
                   repeat('0',40),'sha256:'||repeat('0',64),'sha256:'||repeat('0',64),
                   'sha256:'||repeat('0',64),repeat('0',64)),
                  ('competing-runtime','generation-b',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,
                   0,'legacy-unrecoverable',repeat('0',64),repeat('0',64),0,'launch-b',1,
                   'legacy-birth','/legacy/runtime',repeat('0',64),repeat('0',64),
                   repeat('0',40),'sha256:'||repeat('0',64),'sha256:'||repeat('0',64),
                   'sha256:'||repeat('0',64),repeat('0',64))
                """
            )
        finally:
            await raw.close()
        engine = build_async_engine(database.app_url)
        try:
            preflight = await preflight_reconciliation_0049(engine)
            assert preflight.status == "blocked_competing_generations"
            assert preflight.upgrade_safe is False
            assert preflight.competing_instances == (
                ("competing-runtime", ("generation-a", "generation-b")),
            )
            assert preflight.to_dict()["winner_selected"] is False
            with pytest.raises(Exception, match="uq_locator_runtime_current_instance"):
                await upgrade_schema(engine)
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text(
                            "SELECT migration_id FROM infinity_context_schema_migrations "
                            "ORDER BY applied_at DESC,migration_id DESC LIMIT 1"
                        )
                    )
                    == "0048_locator_lifecycle_release_identity"
                )
                assert (
                    int(
                        await connection.scalar(
                            text(
                                "SELECT count(*) FROM information_schema.columns "
                                "WHERE table_name='memory_locator_runtime_incarnations' "
                                "AND column_name='retired_at'"
                            )
                        )
                        or 0
                    )
                    == 0
                )
        finally:
            await engine.dispose()
    finally:
        await database.drop()
