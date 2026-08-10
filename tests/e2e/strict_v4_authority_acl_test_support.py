"""Adversarial PostgreSQL ACL-upgrade proof for strict-v4 authority tables."""

from __future__ import annotations

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_CANONICAL_WRITER_ROLE,
    STRICT_V4_REGISTRAR_ROLE,
    STRICT_V4_SEALER_ROLE,
)
from postgres_test_database import PostgresTestDatabase
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through

STRICT_V4_0035_AUTHORITY_TABLES = (
    "memory_projection_receipt_claims",
    "memory_projection_target_identities",
    "memory_projection_receipt_identity_links",
    "memory_cleanup_inventory_materializations",
    "memory_cleanup_inventory_keys",
)
_ROLES = (
    STRICT_V4_CANONICAL_WRITER_ROLE,
    STRICT_V4_REGISTRAR_ROLE,
    STRICT_V4_SEALER_ROLE,
)
_TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)


async def assert_upgrade_normalizes_all_authority_acls(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="strict_v4_all_authority_acls",
        asyncpg=asyncpg,
    )
    await database.recreate()
    try:
        await _install_versioned_schema_through(database, "0035_")
        existing_tables = (
            "memory_comparison_benchmark_runs",
            "memory_cleanup_v3_context_authorities",
            *STRICT_V4_0035_AUTHORITY_TABLES,
        )
        connection = await database.connect()
        try:
            for table in existing_tables:
                await connection.execute(f"GRANT ALL ON public.{table} TO PUBLIC")
                for role in _ROLES:
                    await connection.execute(f'GRANT ALL ON public.{table} TO "{role}"')
            await database._provision_strict_v4_capability_roles(connection)
        finally:
            await connection.close()

        engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(engine)
            assert result.applied == (
                "0036_memory_comparison_strict_v4_preparations",
                "0038_strict_v4_document_writer",
            )
        finally:
            await engine.dispose()

        connection = await database.connect()
        try:
            expected = {
                "memory_comparison_benchmark_runs": {role: {"SELECT"} for role in _ROLES},
                "memory_cleanup_v3_context_authorities": {
                    STRICT_V4_CANONICAL_WRITER_ROLE: {"SELECT"},
                    STRICT_V4_REGISTRAR_ROLE: {"SELECT", "INSERT"},
                    STRICT_V4_SEALER_ROLE: {"SELECT"},
                },
                "memory_comparison_strict_v4_preparations": {
                    STRICT_V4_CANONICAL_WRITER_ROLE: {"SELECT"},
                    STRICT_V4_REGISTRAR_ROLE: set(),
                    STRICT_V4_SEALER_ROLE: {"SELECT", "INSERT"},
                },
            }
            tables = (*existing_tables, "memory_comparison_strict_v4_preparations")
            for table in tables:
                assert await _table_privileges(connection, table, "PUBLIC") == set()
                for role in _ROLES:
                    assert await _table_privileges(connection, table, role) == (
                        expected.get(table, {}).get(role, set())
                    )
        finally:
            await connection.close()
    finally:
        await database.drop()


async def _table_privileges(connection, table: str, grantee: str) -> set[str]:
    if grantee == "PUBLIC":
        rows = await connection.fetch(
            """
            SELECT privilege_type
            FROM information_schema.table_privileges
            WHERE table_schema='public'
              AND table_name=$1
              AND grantee='PUBLIC'
            """,
            table,
        )
        return {row["privilege_type"] for row in rows}
    return {
        privilege
        for privilege in _TABLE_PRIVILEGES
        if await connection.fetchval(
            "SELECT pg_catalog.has_table_privilege($1, $2, $3)",
            grantee,
            f"public.{table}",
            privilege,
        )
    }
