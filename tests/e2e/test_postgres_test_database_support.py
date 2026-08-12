"""Test-only PostgreSQL authority needed by published strict-v4 migrations."""

from __future__ import annotations

import asyncio

from postgres_test_database import PostgresTestDatabase


class _RecordingAdmin:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: str) -> None:
        self.statements.append(statement)


def test_test_database_restores_safe_published_writer_migration_roles() -> None:
    admin = _RecordingAdmin()
    database = PostgresTestDatabase(
        asyncpg=None,
        admin_dsn="postgresql://unused",
        app_url="postgresql+asyncpg://unused",
        raw_dsn="postgresql://unused",
        database_name="unused",
    )

    asyncio.run(database._provision_strict_v4_capability_roles(admin))

    assert len(admin.statements) == 2
    production_provisioning, compatibility = admin.statements
    assert "strict_v4_fact_writer" not in production_provisioning
    assert "strict_v4_document_writer" not in production_provisioning
    for role in (
        "infinity_context_strict_v4_fact_writer",
        "infinity_context_strict_v4_document_writer",
    ):
        assert role in compatibility
    assert "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE" in compatibility
    assert "NOREPLICATION NOBYPASSRLS" in compatibility
    assert "FROM pg_catalog.pg_auth_members" in compatibility
    assert "REVOKE ALL PRIVILEGES ON SCHEMA public" in compatibility
    assert "GRANT USAGE ON SCHEMA public" in compatibility
