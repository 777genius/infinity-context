"""Fresh supported-PostgreSQL gate for provider-free context registration."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.managed_cleanup_v4_context_registration import (
    AsyncPostgresCleanupV4ContextAuthorityRegistry,
)
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    register_context_authority_and_readback,
)
from managed_cleanup_v3_full_postgres_support import build_strict_v4_material
from postgres_test_database import PostgresTestDatabase

WHEN = datetime(2026, 8, 9, tzinfo=UTC)
AUTHENTICATOR = ProjectionReceiptAuthenticator(b"v" * 32)


def test_context_registration_on_fresh_supported_postgres() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_scenario(database_url))


async def _scenario(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="v4_context_reg",
        asyncpg=asyncpg,
    )
    context, authority, _pages, _operations = build_strict_v4_material()
    registrar_role = ""
    try:
        await database.recreate()
        engine = build_async_engine(database.app_url)
        try:
            await upgrade_schema(engine)
        finally:
            await engine.dispose()
        registrar_role = await database.create_runtime_role(
            capability_role="infinity_context_strict_v4_registrar",
            suffix="registrar",
        )
        connection = await database.connect()
        try:
            version = int(await connection.fetchval("SHOW server_version_num"))
            assert 160000 <= version < 190000
            await connection.execute(
                """
                INSERT INTO memory_spaces(id,slug,name,status,created_at,updated_at)
                VALUES($1,$2,'strict-v4','active',$3,$3)
                """,
                context.space_id,
                context.space_slug,
                WHEN,
            )
            await connection.execute(
                """
                INSERT INTO memory_comparison_benchmark_runs(
                  run_id_sha256,binding_commitment_sha256,
                  infinity_target_identity_sha256,space_id,space_slug,
                  idempotency_key_sha256,registration_fingerprint_sha256,state,
                  cleanup_plan_json,cleanup_plan_sha256,cleanup_plan_state,
                  projection_manifest_json,projection_manifest_sha256,
                  projection_cleanup_state,cleanup_fingerprint_sha256,
                  cleanup_receipt_json,finalization_fingerprint_sha256,
                  completion_receipt_json,completed_at,created_at,updated_at
                ) VALUES($1,$2,$3,$4,$5,$6,$7,'active',NULL,NULL,'recovery_blocked',
                         NULL,NULL,'unsealed',NULL,NULL,NULL,NULL,NULL,$8,$8)
                """,
                context.run_id_sha256,
                context.binding_commitment_sha256,
                context.infinity_target_identity_sha256,
                context.space_id,
                context.space_slug,
                "9" * 64,
                "8" * 64,
                WHEN,
            )
        finally:
            await connection.close()

        async def connect():
            return await database.connect_as_runtime_role(registrar_role)

        registry = AsyncPostgresCleanupV4ContextAuthorityRegistry(
            connect=connect,
            authenticator=AUTHENTICATOR,
        )
        created = await register_context_authority_and_readback(
            registry,
            context=context,
            authority=authority,
            authenticator=AUTHENTICATOR,
            registered_at=WHEN,
        )
        replayed = await register_context_authority_and_readback(
            registry,
            context=context,
            authority=authority,
            authenticator=AUTHENTICATOR,
            registered_at=WHEN,
        )
        assert created.created is True
        assert replayed.created is False

        connection = await database.connect()
        try:
            with pytest.raises(asyncpg.CheckViolationError) as immutable:
                await connection.execute(
                    """UPDATE memory_cleanup_v3_context_authorities
                       SET registration_mac_sha256=$2 WHERE context_sha256=$1""",
                    context.context_sha256,
                    "0" * 64,
                )
            assert immutable.value.constraint_name == (
                "ck_memory_cleanup_v3_context_authority_immutable"
            )
        finally:
            await connection.close()
        authenticated_replay = await register_context_authority_and_readback(
            registry,
            context=context,
            authority=authority,
            authenticator=AUTHENTICATOR,
            registered_at=WHEN,
        )
        assert authenticated_replay.created is False
    finally:
        await database.drop()
        if registrar_role:
            await database.drop_runtime_roles(registrar_role)
