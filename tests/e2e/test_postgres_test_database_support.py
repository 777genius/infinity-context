"""Test-only PostgreSQL authority needed by published strict-v4 migrations."""

from __future__ import annotations

import asyncio

from postgres_test_database import PostgresTestDatabase


class _RecordingAdmin:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: str) -> None:
        self.statements.append(statement)


def test_test_database_uses_only_packaged_production_role_provisioning() -> None:
    admin = _RecordingAdmin()
    database = PostgresTestDatabase(
        asyncpg=None,
        admin_dsn="postgresql://unused",
        app_url="postgresql+asyncpg://unused",
        raw_dsn="postgresql://unused",
        database_name="unused",
    )

    asyncio.run(database._provision_strict_v4_capability_roles(admin))

    assert len(admin.statements) == 1
    (production_provisioning,) = admin.statements
    for role in (
        "infinity_context_canonical_writer",
        "infinity_context_strict_v4_fact_writer",
        "infinity_context_strict_v4_document_writer",
        "infinity_context_strict_v4_registrar",
        "infinity_context_strict_v4_sealer",
    ):
        assert role in production_provisioning
    assert "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE" in production_provisioning
    assert "NOREPLICATION NOBYPASSRLS" in production_provisioning
    assert "pg_catalog.pg_has_role(" in production_provisioning
    assert "strict-v4 capability roles must not inherit other roles" in production_provisioning
    assert "REVOKE ALL PRIVILEGES ON SCHEMA public" in production_provisioning
    assert "GRANT USAGE ON SCHEMA public" in production_provisioning
