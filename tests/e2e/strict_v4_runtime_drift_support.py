"""Isolated live drift probes for one strict-v4 runtime credential."""

from __future__ import annotations

import pytest
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    assert_strict_v4_runtime_capability,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptError
from strict_v4_0036_security_support import quote_identifier


async def assert_runtime_login_drift_rejected(
    *,
    admin,
    connection,
    login: str,
    capability: str,
    migrator: str,
    error_code: str,
) -> None:
    """Prove each dangerous attribute, direct ACL, and ownership class alone."""

    async def accepted() -> None:
        await assert_strict_v4_runtime_capability(
            connection,
            capability_role=capability,
            error_code=error_code,
        )

    async def rejected() -> None:
        with pytest.raises(ProjectionReceiptError, match=error_code):
            await accepted()

    login_name = quote_identifier(login)
    for enabled, disabled in (
        ("SUPERUSER", "NOSUPERUSER"),
        ("BYPASSRLS", "NOBYPASSRLS"),
        ("CREATEDB", "NOCREATEDB"),
        ("CREATEROLE", "NOCREATEROLE"),
        ("REPLICATION", "NOREPLICATION"),
    ):
        await admin.execute(f"ALTER ROLE {login_name} {enabled}")
        try:
            await rejected()
        finally:
            await admin.execute(f"ALTER ROLE {login_name} {disabled}")
        await accepted()

    acl_cases = (
        (
            f"GRANT CREATE ON SCHEMA public TO {login_name}",
            f"REVOKE CREATE ON SCHEMA public FROM {login_name}",
        ),
        (
            f"GRANT UPDATE ON TABLE public.memory_spaces TO {login_name}",
            f"REVOKE UPDATE ON TABLE public.memory_spaces FROM {login_name}",
        ),
        (
            f"GRANT UPDATE (key) ON TABLE public.memory_idempotency_records TO {login_name}",
            f"REVOKE UPDATE (key) ON TABLE public.memory_idempotency_records FROM {login_name}",
        ),
        (
            f"GRANT UPDATE ON SEQUENCE public.memory_idempotency_records_id_seq TO {login_name}",
            f"REVOKE UPDATE ON SEQUENCE public.memory_idempotency_records_id_seq FROM {login_name}",
        ),
        (
            "GRANT EXECUTE ON FUNCTION "
            "public.memory_comparison_enforce_benchmark_writer_fence() "
            f"TO {login_name}",
            "REVOKE EXECUTE ON FUNCTION "
            "public.memory_comparison_enforce_benchmark_writer_fence() "
            f"FROM {login_name}",
        ),
    )
    for grant, revoke in acl_cases:
        await admin.execute(grant)
        try:
            await rejected()
        finally:
            await admin.execute(revoke)
        await accepted()

    migrator_name = quote_identifier(migrator)
    schema_owner = await admin.fetchval(
        """
        SELECT owner.rolname
        FROM pg_catalog.pg_namespace AS namespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid=namespace.nspowner
        WHERE namespace.nspname='public'
        """
    )
    ownership_cases = (
        (
            f"ALTER TABLE public.memory_spaces OWNER TO {login_name}",
            f"ALTER TABLE public.memory_spaces OWNER TO {migrator_name}",
        ),
        (
            f"ALTER SCHEMA public OWNER TO {login_name}",
            f"ALTER SCHEMA public OWNER TO {quote_identifier(str(schema_owner))}",
        ),
        (
            "ALTER FUNCTION public.memory_comparison_enforce_benchmark_writer_fence() "
            f"OWNER TO {login_name}",
            "ALTER FUNCTION public.memory_comparison_enforce_benchmark_writer_fence() "
            f"OWNER TO {migrator_name}",
        ),
    )
    for acquire, restore in ownership_cases:
        await admin.execute(acquire)
        try:
            await rejected()
        finally:
            await admin.execute(restore)
        await accepted()


__all__ = ("assert_runtime_login_drift_rejected",)
