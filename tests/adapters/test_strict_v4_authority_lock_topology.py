from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from infinity_context_adapters.postgres.strict_v4_authority_lock_topology import (
    _REGISTRATION_BODY,
    _REGISTRATION_FUNCTION,
    _SEAL_BODY,
    _SEAL_FUNCTION,
    assert_strict_v4_authority_lock_topology,
)
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_REGISTRAR_ROLE,
    STRICT_V4_SEALER_ROLE,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptError

_MIGRATION = (
    Path(__file__).parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
    / "0036_memory_comparison_strict_v4_preparations.sql"
)
_FIELDS = (
    "has_exact_name",
    "is_security_definer",
    "is_function",
    "is_volatile",
    "is_plpgsql",
    "returns_void",
    "has_exact_arguments",
    "has_safe_search_path",
    "has_exact_body",
    "has_safe_owner",
    "has_exact_acl",
)


class _Connection:
    def __init__(self, *, changed: str | None = None, missing: bool = False) -> None:
        self.changed = changed
        self.missing = missing
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if self.missing:
            return None
        return {field: field != self.changed for field in _FIELDS}


@pytest.mark.parametrize(
    ("capability", "function_name", "body"),
    (
        (STRICT_V4_REGISTRAR_ROLE, _REGISTRATION_FUNCTION, _REGISTRATION_BODY),
        (STRICT_V4_SEALER_ROLE, _SEAL_FUNCTION, _SEAL_BODY),
    ),
)
def test_exact_callable_authority_lock_is_accepted(
    capability: str,
    function_name: str,
    body: str,
) -> None:
    connection = _Connection()

    asyncio.run(
        assert_strict_v4_authority_lock_topology(
            connection,
            capability_role=capability,
        )
    )

    sql, args = connection.calls[0]
    assert args[0] == f"public.{function_name}(pg_catalog.bpchar,pg_catalog.bpchar)"
    assert args[3] == body
    assert args[5] == capability
    assert "procedure.proargtypes[0]" in sql
    assert "pg_catalog.acldefault" in sql


@pytest.mark.parametrize("field", _FIELDS)
def test_callable_authority_lock_catalog_drift_is_rejected(field: str) -> None:
    with pytest.raises(ProjectionReceiptError, match="authority_lock_invalid"):
        asyncio.run(
            assert_strict_v4_authority_lock_topology(
                _Connection(changed=field),
                capability_role=STRICT_V4_REGISTRAR_ROLE,
            )
        )


def test_missing_or_unknown_authority_lock_is_rejected() -> None:
    for connection, role in (
        (_Connection(missing=True), STRICT_V4_SEALER_ROLE),
        (_Connection(), "unknown"),
    ):
        with pytest.raises(ProjectionReceiptError, match="authority_lock_invalid"):
            asyncio.run(
                assert_strict_v4_authority_lock_topology(
                    connection,
                    capability_role=role,
                )
            )


def test_attested_authority_lock_bodies_match_migration_0036() -> None:
    sql = _MIGRATION.read_text(encoding="utf-8")
    for function_name, expected_body in (
        (_REGISTRATION_FUNCTION, _REGISTRATION_BODY),
        (_SEAL_FUNCTION, _SEAL_BODY),
    ):
        tail = sql.split(f"CREATE OR REPLACE FUNCTION public.{function_name}", 1)[1]
        installed_body = tail.split("AS $$", 1)[1].split("$$;", 1)[0]
        assert installed_body == expected_body
