"""Exact catalog attestation for callable strict-v4 authority locks."""

# ruff: noqa: E501 -- exact PostgreSQL prosrc bodies intentionally preserve SQL bytes.

from __future__ import annotations

from typing import Any

from infinity_context_core.features.projection_receipts import ProjectionReceiptError

from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_CAPABILITY_ROLES,
    STRICT_V4_REGISTRAR_ROLE,
    STRICT_V4_SEALER_ROLE,
)

_SAFE_SEARCH_PATH = "search_path=pg_catalog, public, pg_temp"
_REGISTRATION_FUNCTION = "memory_comparison_lock_strict_v4_registration_targets"
_SEAL_FUNCTION = "memory_comparison_lock_strict_v4_seal_targets"
_REGISTRATION_BODY = """
BEGIN
    IF requested_run_id_sha256 !~ '^[0-9a-f]{64}$'
        OR requested_context_sha256 !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION 'strict-v4 registration lock identity is invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM 1
    FROM public.memory_comparison_benchmark_runs
    WHERE run_id_sha256 = requested_run_id_sha256
    FOR UPDATE;
    PERFORM 1
    FROM public.memory_cleanup_v3_context_authorities
    WHERE run_id_sha256 = requested_run_id_sha256
       OR context_sha256 = requested_context_sha256
    ORDER BY run_id_sha256, context_sha256
    FOR UPDATE;
    IF NOT EXISTS (SELECT 1 FROM public.memory_cleanup_v3_context_authorities
                   WHERE run_id_sha256 = requested_run_id_sha256
                      OR context_sha256 = requested_context_sha256)
       AND EXISTS (
        SELECT 1 FROM public.memory_projection_receipt_claims WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
        UNION ALL SELECT 1 FROM public.memory_projection_target_identities WHERE run_id_sha256 = requested_run_id_sha256
        UNION ALL SELECT 1 FROM public.memory_projection_receipt_identity_links WHERE run_id_sha256 = requested_run_id_sha256
        UNION ALL SELECT 1 FROM public.memory_cleanup_inventory_materializations WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
        UNION ALL SELECT 1 FROM public.memory_cleanup_inventory_keys WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
    ) THEN
        RAISE EXCEPTION 'strict-v4 registration target state is not pristine'
            USING ERRCODE = '23514',
              CONSTRAINT = 'ck_memory_comparison_strict_v4_registration_pristine';
    END IF;
END;
"""
_SEAL_BODY = """
BEGIN
    IF requested_run_id_sha256 !~ '^[0-9a-f]{64}$'
        OR requested_context_sha256 !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION 'strict-v4 seal lock identity is invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM 1
    FROM public.memory_comparison_benchmark_runs
    WHERE run_id_sha256 = requested_run_id_sha256
    FOR UPDATE;
    PERFORM 1
    FROM public.memory_cleanup_v3_context_authorities
    WHERE run_id_sha256 = requested_run_id_sha256
       OR context_sha256 = requested_context_sha256
    ORDER BY run_id_sha256, context_sha256
    FOR UPDATE;
    PERFORM 1
    FROM public.memory_comparison_strict_v4_preparations
    WHERE run_id_sha256 = requested_run_id_sha256
       OR context_sha256 = requested_context_sha256
    ORDER BY run_id_sha256, context_sha256
    FOR UPDATE;
    IF NOT EXISTS (SELECT 1 FROM public.memory_comparison_strict_v4_preparations
                   WHERE run_id_sha256 = requested_run_id_sha256
                      OR context_sha256 = requested_context_sha256)
       AND EXISTS (
        SELECT 1 FROM public.memory_projection_receipt_claims WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
        UNION ALL SELECT 1 FROM public.memory_projection_target_identities WHERE run_id_sha256 = requested_run_id_sha256
        UNION ALL SELECT 1 FROM public.memory_projection_receipt_identity_links WHERE run_id_sha256 = requested_run_id_sha256
        UNION ALL SELECT 1 FROM public.memory_cleanup_inventory_materializations WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
        UNION ALL SELECT 1 FROM public.memory_cleanup_inventory_keys WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
    ) THEN
        RAISE EXCEPTION 'strict-v4 seal target state is not pristine'
            USING ERRCODE = '23514',
              CONSTRAINT = 'ck_memory_comparison_strict_v4_seal_pristine';
    END IF;
END;
"""
_EXPECTED = {
    STRICT_V4_REGISTRAR_ROLE: (_REGISTRATION_FUNCTION, _REGISTRATION_BODY),
    STRICT_V4_SEALER_ROLE: (_SEAL_FUNCTION, _SEAL_BODY),
}

_AUTHORITY_LOCK_SQL = """
SELECT procedure.proname=$2 AS has_exact_name,
       procedure.prosecdef AS is_security_definer,
       procedure.prokind='f' AS is_function,
       procedure.provolatile='v' AS is_volatile,
       language.lanname='plpgsql' AS is_plpgsql,
       procedure.prorettype='pg_catalog.void'::pg_catalog.regtype AS returns_void,
       procedure.pronargs=2
         AND procedure.proargtypes[0]=
             'pg_catalog.bpchar'::pg_catalog.regtype
         AND procedure.proargtypes[1]=
             'pg_catalog.bpchar'::pg_catalog.regtype AS has_exact_arguments,
       procedure.proconfig=ARRAY[$3]::pg_catalog.text[] AS has_safe_search_path,
       procedure.prosrc=$4 AS has_exact_body,
       owner.rolname<>ALL($5::pg_catalog.text[]) AS has_safe_owner,
       NOT EXISTS (
           SELECT 1
           FROM pg_catalog.aclexplode(
               COALESCE(
                   procedure.proacl,
                   pg_catalog.acldefault('f', procedure.proowner)
               )
           ) AS acl
           WHERE acl.grantee NOT IN (procedure.proowner, expected_role.oid)
              OR acl.privilege_type<>'EXECUTE'
              OR acl.is_grantable
       )
       AND (
           SELECT pg_catalog.count(*)=2
           FROM pg_catalog.aclexplode(
               COALESCE(
                   procedure.proacl,
                   pg_catalog.acldefault('f', procedure.proowner)
               )
           ) AS acl
       )
       AND (
           SELECT pg_catalog.count(*)=1
           FROM pg_catalog.aclexplode(
               COALESCE(
                   procedure.proacl,
                   pg_catalog.acldefault('f', procedure.proowner)
               )
           ) AS acl
           WHERE acl.grantee=expected_role.oid
             AND acl.privilege_type='EXECUTE'
             AND NOT acl.is_grantable
       ) AS has_exact_acl
FROM pg_catalog.pg_proc AS procedure
JOIN pg_catalog.pg_language AS language ON language.oid=procedure.prolang
JOIN pg_catalog.pg_roles AS owner ON owner.oid=procedure.proowner
CROSS JOIN pg_catalog.pg_roles AS expected_role
WHERE procedure.oid=pg_catalog.to_regprocedure($1)
  AND expected_role.rolname=$6
"""


async def assert_strict_v4_authority_lock_topology(
    connection: Any,
    *,
    capability_role: str,
) -> None:
    """Reject any drift before invoking a callable SECURITY DEFINER lock."""

    expected = _EXPECTED.get(capability_role)
    if expected is None:
        raise ProjectionReceiptError("projection_receipt.authority_lock_invalid")
    function_name, body = expected
    signature = f"public.{function_name}(pg_catalog.bpchar,pg_catalog.bpchar)"
    row = await connection.fetchrow(
        _AUTHORITY_LOCK_SQL,
        signature,
        function_name,
        _SAFE_SEARCH_PATH,
        body,
        list(STRICT_V4_CAPABILITY_ROLES),
        capability_role,
    )
    if row is None or not all(value is True for value in row.values()):
        raise ProjectionReceiptError("projection_receipt.authority_lock_invalid")


__all__ = ("assert_strict_v4_authority_lock_topology",)
