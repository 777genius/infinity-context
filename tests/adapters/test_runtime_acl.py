from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres.runtime_acl import (
    RUNTIME_ROLE,
    load_runtime_acl_sql,
    reconcile_runtime_acl,
)


class _Driver:
    def __init__(self) -> None:
        self.sql: list[str] = []

    async def execute(self, sql: str) -> None:
        self.sql.append(sql)


class _Connection:
    def __init__(self, driver: _Driver) -> None:
        self._driver = driver

    async def get_raw_connection(self) -> SimpleNamespace:
        return SimpleNamespace(driver_connection=self._driver)


class _Transaction:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _Connection:
        return self._connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Engine:
    def __init__(self, dialect: str) -> None:
        self.dialect = SimpleNamespace(name=dialect)
        self.driver = _Driver()

    def begin(self) -> _Transaction:
        return _Transaction(_Connection(self.driver))


def test_runtime_acl_is_exact_and_excludes_strict_writes() -> None:
    sql = load_runtime_acl_sql()

    assert RUNTIME_ROLE == "infinity_context_runtime"
    assert "GRANT ALL" not in sql.upper()
    assert "ALTER DEFAULT PRIVILEGES" not in sql.upper()
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" in sql
    assert "GRANT SELECT ON TABLE" in sql
    assert "memory_comparison_strict_v4_preparations" in sql
    assert "memory_cleanup_v3_context_authorities" in sql
    assert "memory_locator_profile_cleanups" in sql
    assert "memory_locator_profile_projection_receipts" in sql
    assert "memory_locator_profile_evidence_versions" in sql
    assert "memory_locator_profile_queries" in sql
    assert "memory_locator_profile_maintenance_fence" in sql
    assert "memory_locator_profile_recovery_receipts" in sql
    assert "memory_locator_profile_tombstone_replays" in sql
    assert "memory_vector_rebuild_operations" in sql
    assert "memory_comparison_is_strict_v4_canonical_writer" in sql
    assert "REVOKE ALL PRIVILEGES ON FUNCTION" in sql
    assert "rolcanlogin" in sql
    assert "NOT role.rolinherit" in sql
    assert "membership.member = runtime_oid" in sql
    assert "relation.relowner = runtime_oid" in sql


def test_runtime_acl_executes_the_packaged_program_once() -> None:
    engine = _Engine("postgresql")

    asyncio.run(reconcile_runtime_acl(engine))  # type: ignore[arg-type]

    assert engine.driver.sql == [load_runtime_acl_sql()]


def test_runtime_acl_rejects_non_postgres_engines() -> None:
    engine = _Engine("sqlite")

    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        asyncio.run(reconcile_runtime_acl(engine))  # type: ignore[arg-type]
    assert engine.driver.sql == []
