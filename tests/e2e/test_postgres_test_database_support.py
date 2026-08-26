"""Test-only PostgreSQL authority needed by published strict-v4 migrations."""

from __future__ import annotations

import asyncio
from importlib.resources import files

from postgres_test_database import STRICT_V4_CAPABILITY_ROLES, PostgresTestDatabase


class _RecordingAdmin:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: str) -> None:
        self.statements.append(statement)


def test_test_database_executes_exact_production_role_provisioning_once() -> None:
    admin = _RecordingAdmin()
    database = PostgresTestDatabase(
        asyncpg=None,
        admin_dsn="postgresql://unused",
        app_url="postgresql+asyncpg://unused",
        raw_dsn="postgresql://unused",
        database_name="unused",
    )

    asyncio.run(database._provision_strict_v4_capability_roles(admin))

    expected = (
        files("infinity_context_adapters.postgres")
        .joinpath("provisioning", "strict_v4_roles.sql")
        .read_text(encoding="utf-8")
    )
    assert admin.statements == [expected]

    for role in (
        "infinity_context_canonical_writer",
        "infinity_context_strict_v4_registrar",
        "infinity_context_strict_v4_sealer",
    ):
        assert role in expected
    for role in (
        "infinity_context_strict_v4_fact_writer",
        "infinity_context_strict_v4_document_writer",
    ):
        assert role not in expected


def test_runtime_capabilities_are_exactly_the_three_production_roles() -> None:
    assert STRICT_V4_CAPABILITY_ROLES == (
        "infinity_context_canonical_writer",
        "infinity_context_strict_v4_registrar",
        "infinity_context_strict_v4_sealer",
    )
