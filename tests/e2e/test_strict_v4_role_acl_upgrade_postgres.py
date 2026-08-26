"""Fresh PostgreSQL proof that strict-v4 normalizes hostile ACLs."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.migration_runner import _load_migrations
from postgres_test_database import PostgresTestDatabase
from sqlalchemy.engine import make_url
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through

ROLES = (
    "infinity_context_canonical_writer",
    "infinity_context_strict_v4_registrar",
    "infinity_context_strict_v4_sealer",
)
RETIRED_ROLES = (
    "infinity_context_strict_v4_fact_writer",
    "infinity_context_strict_v4_document_writer",
)
CANONICAL_WRITER = ROLES[0]
ALL_TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)

_S = frozenset({"SELECT"})
_SI = frozenset({"SELECT", "INSERT"})
_SID = frozenset({"SELECT", "INSERT", "DELETE"})
_NONE = frozenset()

EXPECTED_TABLE_ACL = {
    "memory_comparison_benchmark_runs": (_S, _S, _S),
    "memory_cleanup_v3_context_authorities": (_S, _SI, _S),
    "memory_comparison_strict_v4_preparations": (_S, _NONE, _SI),
    "memory_spaces": (_S, _NONE, _NONE),
    "memory_scopes": (_SI, _S, _S),
    "memory_threads": (_SI, _S, _S),
    "memory_facts": (_SI, _S, _S),
    "memory_episodes": (_NONE, _NONE, _NONE),
    "memory_documents": (_SI, _S, _S),
    "memory_chunks": (_SI, _S, _S),
    "memory_fact_operation_receipts": (_SI, _S, _S),
    "memory_idempotency_records": (_SI, _S, _S),
    "memory_anchors": (_NONE, _NONE, _NONE),
    "memory_assets": (_NONE, _NONE, _NONE),
    "memory_asset_extraction_jobs": (_NONE, _NONE, _NONE),
    "memory_fact_relations": (_NONE, _NONE, _NONE),
    "memory_fact_temporal_decisions": (_NONE, _NONE, _NONE),
    "memory_suggestions": (_NONE, _NONE, _NONE),
    "memory_captures": (_NONE, _NONE, _NONE),
    "memory_context_links": (_NONE, _NONE, _NONE),
    "memory_context_link_suggestions": (_NONE, _NONE, _NONE),
    "memory_projection_result_receipts": (_NONE, _S, _S),
    "memory_projection_receipt_claims": (_NONE, _NONE, _NONE),
    "memory_projection_target_identities": (_NONE, _NONE, _NONE),
    "memory_projection_receipt_identity_links": (_NONE, _NONE, _NONE),
    "memory_cleanup_inventory_materializations": (_NONE, _NONE, _NONE),
    "memory_cleanup_inventory_keys": (_NONE, _NONE, _NONE),
    "memory_source_refs": (_SID, _NONE, _NONE),
    "memory_fact_versions": (_SI, _NONE, _NONE),
    "memory_outbox": (_SI, _NONE, _NONE),
}

SEQUENCES = (
    "memory_source_refs_id_seq",
    "memory_fact_versions_id_seq",
    "memory_outbox_id_seq",
    "memory_idempotency_records_id_seq",
    "memory_locator_commit_watermark_seq",
)


def test_strict_v4_upgrade_normalizes_hostile_acls_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_scenario(database_url))


def test_strict_v4_upgrade_does_not_require_public_schema_owner_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_non_schema_owner_scenario(database_url))


async def _scenario(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="strict_v4_acl",
        asyncpg=asyncpg,
    )
    await database.recreate()
    try:
        await _install_versioned_schema_through(database, "0035_")
        connection = await database.connect()
        try:
            await _assert_retired_roles_absent(connection)
            await connection.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
            for role in ROLES:
                await connection.execute(f"GRANT CREATE ON SCHEMA public TO {role}")
            for table in EXPECTED_TABLE_ACL:
                if not await connection.fetchval(
                    "SELECT pg_catalog.to_regclass($1) IS NOT NULL",
                    f"public.{table}",
                ):
                    continue
                await connection.execute(f"GRANT ALL ON public.{table} TO PUBLIC")
                for role in ROLES:
                    await connection.execute(f"GRANT ALL ON public.{table} TO {role}")
            for sequence in SEQUENCES:
                if not await connection.fetchval(
                    "SELECT pg_catalog.to_regclass($1) IS NOT NULL",
                    f"public.{sequence}",
                ):
                    continue
                await connection.execute(f"GRANT ALL ON SEQUENCE public.{sequence} TO PUBLIC")
                for role in ROLES:
                    await connection.execute(f"GRANT ALL ON SEQUENCE public.{sequence} TO {role}")
        finally:
            await connection.close()

        # The administrator provisioning step is deliberately target-DB local:
        # it removes legacy CREATE before the ordinary table-owner migration.
        connection = await database.connect()
        try:
            await database._provision_strict_v4_capability_roles(connection)
        finally:
            await connection.close()

        engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(engine)
            assert result.applied == (
                "0036_memory_comparison_strict_v4_preparations",
                "0037_strict_v4_fact_writer",
                "0038_strict_v4_document_writer",
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
            )
        finally:
            await engine.dispose()

        connection = await database.connect()
        try:
            await _assert_retired_roles_absent(connection)
            for role in ROLES:
                assert await connection.fetchval(
                    "SELECT pg_catalog.has_schema_privilege($1, 'public', 'USAGE')",
                    role,
                )
                assert not await connection.fetchval(
                    "SELECT pg_catalog.has_schema_privilege($1, 'public', 'CREATE')",
                    role,
                )
            assert not await connection.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_namespace AS namespace
                    CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl
                    WHERE namespace.nspname='public'
                      AND acl.grantee=0
                      AND acl.privilege_type='CREATE'
                )
                """
            )
            for table, expected_by_role in EXPECTED_TABLE_ACL.items():
                await _assert_exact(
                    connection,
                    grantee="PUBLIC",
                    table=table,
                    expected=_NONE,
                )
                for role, expected in zip(ROLES, expected_by_role, strict=True):
                    await _assert_exact(
                        connection,
                        grantee=role,
                        table=table,
                        expected=expected,
                    )

            for sequence in SEQUENCES:
                await _assert_sequence_exact(
                    connection,
                    grantee="PUBLIC",
                    sequence=sequence,
                    expected=_NONE,
                )
                for role in ROLES:
                    await _assert_sequence_exact(
                        connection,
                        grantee=role,
                        sequence=sequence,
                        expected=frozenset({"USAGE"}) if role == CANONICAL_WRITER else _NONE,
                    )
            await _assert_canonical_sequence_inventory(connection)
        finally:
            await connection.close()
    finally:
        await database.drop()


async def _non_schema_owner_scenario(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="strict_v4_non_schema_owner",
        asyncpg=asyncpg,
    )
    migrator = f"ic_v4_migrator_{database.database_name[-32:]}"
    password = "strict-v4-non-schema-owner-test-only"
    await database.recreate()
    try:
        admin = await database.connect()
        try:
            await admin.execute(f"CREATE ROLE \"{migrator}\" LOGIN PASSWORD '{password}'")
            await admin.execute(f'GRANT CREATE ON SCHEMA public TO "{migrator}"')
            await admin.execute(
                f'GRANT CREATE ON DATABASE "{database.database_name}" TO "{migrator}"'
            )
            await admin.execute(f'CREATE SCHEMA hostile AUTHORIZATION "{migrator}"')
            await admin.execute("CREATE TABLE hostile.memory_spaces(shadow_marker text NOT NULL)")
            await admin.execute(f'ALTER ROLE "{migrator}" SET search_path=hostile,public')
            schema_owner = await admin.fetchval(
                """
                SELECT owner.rolname
                FROM pg_catalog.pg_namespace AS namespace
                JOIN pg_catalog.pg_roles AS owner ON owner.oid=namespace.nspowner
                WHERE namespace.nspname='public'
                """
            )
            assert schema_owner != migrator
        finally:
            await admin.close()

        app_url = make_url(database.app_url).set(
            username=migrator,
            password=password,
        )
        raw_url = make_url(database.raw_dsn).set(
            username=migrator,
            password=password,
        )
        migrator_database = replace(
            database,
            app_url=app_url.render_as_string(hide_password=False),
            raw_dsn=raw_url.render_as_string(hide_password=False),
        )
        engine = build_async_engine(migrator_database.app_url)
        try:
            result = await upgrade_schema(engine)
            assert result.current == "0054_locator_profile_exact_delete_generation"
            assert result.applied[0] == "0001_core_facts"
            assert result.applied[-1] == "0054_locator_profile_exact_delete_generation"
        finally:
            await engine.dispose()

        admin = await database.connect()
        try:
            assert (
                await admin.fetchval(
                    """
                    SELECT tableowner FROM pg_catalog.pg_tables
                    WHERE schemaname='public'
                      AND tablename='memory_comparison_strict_v4_preparations'
                    """
                )
                == migrator
            )
            assert await admin.fetchval("SELECT to_regclass('public.memory_spaces') IS NOT NULL")
            assert await admin.fetchval(
                """
                    SELECT array_agg(column_name ORDER BY ordinal_position)
                    FROM information_schema.columns
                    WHERE table_schema='hostile' AND table_name='memory_spaces'
                    """
            ) == ["shadow_marker"]
            canonical_migration_ids = tuple(
                migration.migration_id for migration in _load_migrations()
            )
            applied_migration_ids = tuple(
                await admin.fetch(
                    """
                    SELECT migration_id
                    FROM public.infinity_context_schema_migrations
                    ORDER BY migration_id
                    """
                )
            )
            assert tuple(row["migration_id"] for row in applied_migration_ids) == (
                canonical_migration_ids
            )
        finally:
            await admin.close()
    finally:
        await database.drop()
        admin = await database.asyncpg.connect(database.admin_dsn)
        try:
            await admin.execute(f'DROP ROLE IF EXISTS "{migrator}"')
        finally:
            await admin.close()


async def _assert_exact(connection, *, grantee: str, table: str, expected) -> None:
    if grantee == "PUBLIC":
        observed = set(
            await connection.fetch(
                """
                SELECT privilege_type
                FROM information_schema.table_privileges
                WHERE table_schema='public' AND table_name=$1 AND grantee='PUBLIC'
                """,
                table,
            )
        )
        observed = {row["privilege_type"] for row in observed}
    else:
        observed = {
            privilege
            for privilege in ALL_TABLE_PRIVILEGES
            if await connection.fetchval(
                "SELECT pg_catalog.has_table_privilege($1, $2, $3)",
                grantee,
                f"public.{table}",
                privilege,
            )
        }
    assert observed == expected


async def _assert_retired_roles_absent(connection) -> None:
    assert not await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=ANY($1::text[]))",
        list(RETIRED_ROLES),
    )


async def _assert_sequence_exact(
    connection,
    *,
    grantee: str,
    expected,
    sequence: str = "memory_idempotency_records_id_seq",
) -> None:
    if grantee == "PUBLIC":
        rows = await connection.fetch(
            """
            SELECT privilege_type
            FROM information_schema.usage_privileges
            WHERE object_schema='public'
              AND object_name=$1
              AND grantee='PUBLIC'
            """,
            sequence,
        )
        observed = {row["privilege_type"] for row in rows}
    else:
        observed = {
            privilege
            for privilege in ("USAGE", "SELECT", "UPDATE")
            if await connection.fetchval(
                "SELECT pg_catalog.has_sequence_privilege($1, $2, $3)",
                grantee,
                f"public.{sequence}",
                privilege,
            )
        }
    assert observed == expected


async def _assert_canonical_sequence_inventory(connection) -> None:
    canonical_tables = (
        "memory_spaces",
        "memory_scopes",
        "memory_threads",
        "memory_facts",
        "memory_episodes",
        "memory_documents",
        "memory_chunks",
        "memory_fact_operation_receipts",
        "memory_idempotency_records",
        "memory_anchors",
        "memory_assets",
        "memory_asset_extraction_jobs",
        "memory_fact_relations",
        "memory_fact_temporal_decisions",
        "memory_suggestions",
        "memory_captures",
        "memory_context_links",
        "memory_context_link_suggestions",
    )
    rows = await connection.fetch(
        """
        SELECT table_name, column_name, column_default
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name=ANY($1::text[])
          AND (
              is_identity='YES'
              OR column_default LIKE 'nextval(%'
          )
        ORDER BY table_name, column_name
        """,
        list(canonical_tables),
    )
    assert [(row["table_name"], row["column_name"], row["column_default"]) for row in rows] == [
        (
            "memory_chunks",
            "retrieval_commit_watermark",
            "nextval('memory_locator_commit_watermark_seq'::regclass)",
        ),
        (
            "memory_idempotency_records",
            "id",
            "nextval('memory_idempotency_records_id_seq'::regclass)",
        ),
    ]
