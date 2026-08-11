"""Catalog attestation for the ordered strict-v4 canonical writer fence."""

from __future__ import annotations

from typing import Any

from infinity_context_core.features.projection_receipts import ProjectionReceiptError

from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_CANONICAL_WRITER_FUNCTION_BODY,
    BENCHMARK_WRITER_FENCE_FUNCTION,
    BENCHMARK_WRITER_FENCE_TABLES,
    BENCHMARK_WRITER_LOCK_FUNCTION_BODY,
    BENCHMARK_WRITER_POLICY_FUNCTION_BODY,
)
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_CAPABILITY_ROLES,
)

_LOCK_FUNCTION = "memory_comparison_lock_benchmark_writer_target"
_SAFE_SEARCH_PATH = "search_path=pg_catalog, public, pg_temp"

_TOPOLOGY_SQL = """
WITH canonical_checker AS (
    SELECT procedure.*, language.lanname AS language_name,
           owner.rolname AS owner_name
    FROM pg_catalog.pg_proc AS procedure
    JOIN pg_catalog.pg_language AS language ON language.oid=procedure.prolang
    JOIN pg_catalog.pg_roles AS owner ON owner.oid=procedure.proowner
    WHERE procedure.oid=pg_catalog.to_regprocedure(
        'public.memory_comparison_is_strict_v4_canonical_writer()'
    )
),
canonical_role AS (
    SELECT oid FROM pg_catalog.pg_roles
    WHERE rolname='infinity_context_canonical_writer'
),
sentinel_before_insert AS (
    SELECT pg_catalog.count(*)=2 AS has_exact_count
    FROM pg_catalog.pg_trigger AS candidate
    JOIN pg_catalog.pg_class AS relation ON relation.oid=candidate.tgrelid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid=relation.relnamespace
    WHERE namespace.nspname='public'
      AND relation.relname='memory_idempotency_records'
      AND NOT candidate.tgisinternal
      AND candidate.tgtype IN (
          6, 7, 14, 15, 22, 23, 30, 31,
          38, 39, 46, 47, 54, 55, 62, 63
      )
)
SELECT relation.relname::pg_catalog.text AS table_name,
       trigger.tgname::pg_catalog.text AS trigger_name,
       trigger.tgenabled::pg_catalog.text AS trigger_enabled,
       trigger.tgtype::pg_catalog.int4 AS trigger_type,
       trigger.tgqual IS NULL AS has_no_when_clause,
       trigger.tgattr = ''::pg_catalog.int2vector AS has_no_update_column_filter,
       trigger.tgnargs = 0 AS has_no_trigger_arguments,
       function.proname::pg_catalog.text AS function_name,
       function.prosecdef AS security_definer,
       function.prokind::pg_catalog.text AS function_kind,
       function.prorettype = 'pg_catalog.trigger'::pg_catalog.regtype AS returns_trigger,
       pg_catalog.pg_get_function_identity_arguments(function.oid) = '' AS has_no_arguments,
       function.proconfig = ARRAY[$3]::pg_catalog.text[] AS has_safe_search_path,
       function.prosrc = CASE function.proname
           WHEN 'memory_comparison_lock_benchmark_writer_target' THEN $4
           ELSE $5
       END AS has_exact_body,
       NOT canonical_checker.prosecdef
         AND canonical_checker.prokind='f'
         AND canonical_checker.provolatile='s'
         AND canonical_checker.language_name='sql'
         AND canonical_checker.prorettype=
             'pg_catalog.bool'::pg_catalog.regtype
         AND canonical_checker.pronargs=0 AS checker_has_exact_kind,
       canonical_checker.proconfig=ARRAY[$3]::pg_catalog.text[]
         AS checker_has_safe_search_path,
       canonical_checker.prosrc=$6 AS checker_has_exact_body,
       canonical_checker.owner_name<>ALL($2::pg_catalog.text[])
         AS checker_has_safe_owner,
       sentinel_before_insert.has_exact_count
         AS sentinel_has_exact_before_insert_triggers,
       NOT EXISTS (
           SELECT 1
           FROM pg_catalog.aclexplode(
               COALESCE(
                   canonical_checker.proacl,
                   pg_catalog.acldefault(
                       'f', canonical_checker.proowner
                   )
               )
           ) AS acl
           WHERE acl.grantee NOT IN (
                     canonical_checker.proowner, canonical_role.oid
                 )
              OR acl.privilege_type<>'EXECUTE'
              OR acl.is_grantable
       )
       AND (
           SELECT pg_catalog.count(*)=2
           FROM pg_catalog.aclexplode(
               COALESCE(
                   canonical_checker.proacl,
                   pg_catalog.acldefault(
                       'f', canonical_checker.proowner
                   )
               )
           ) AS acl
       )
       AND (
           SELECT pg_catalog.count(*)=1
           FROM pg_catalog.aclexplode(
               COALESCE(
                   canonical_checker.proacl,
                   pg_catalog.acldefault(
                       'f', canonical_checker.proowner
                   )
               )
           ) AS acl
           WHERE acl.grantee=canonical_role.oid
             AND acl.privilege_type='EXECUTE'
             AND NOT acl.is_grantable
       ) AS checker_has_exact_acl,
       NOT EXISTS (
           SELECT 1
           FROM pg_catalog.aclexplode(
               COALESCE(
                   function.proacl,
                   pg_catalog.acldefault('f', function.proowner)
               )
           ) AS acl
           LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid=acl.grantee
           WHERE acl.grantee=0 OR grantee.rolname=ANY($2::pg_catalog.text[])
       ) AS capability_execute_revoked
FROM pg_catalog.pg_trigger AS trigger
JOIN pg_catalog.pg_class AS relation ON relation.oid=trigger.tgrelid
JOIN pg_catalog.pg_namespace AS relation_schema
  ON relation_schema.oid=relation.relnamespace
JOIN pg_catalog.pg_proc AS function ON function.oid=trigger.tgfoid
JOIN pg_catalog.pg_namespace AS function_schema
  ON function_schema.oid=function.pronamespace
CROSS JOIN canonical_checker
CROSS JOIN canonical_role
CROSS JOIN sentinel_before_insert
WHERE NOT trigger.tgisinternal
  AND relation_schema.nspname='public'
  AND function_schema.nspname='public'
  AND relation.relname=ANY($1::pg_catalog.text[])
  AND trigger.tgname IN (
      'trg_00_' || relation.relname || '_benchmark_writer_lock',
      'trg_' || relation.relname || '_benchmark_writer_fence'
  )
ORDER BY relation.relname, trigger.tgname
"""


async def assert_strict_v4_writer_fence_topology(connection: Any) -> None:
    """Require the exact lock-first and invoker-policy stages on every table."""

    tables = tuple(table for table, _columns in BENCHMARK_WRITER_FENCE_TABLES)
    rows = await connection.fetch(
        _TOPOLOGY_SQL,
        list(tables),
        list(STRICT_V4_CAPABILITY_ROLES),
        _SAFE_SEARCH_PATH,
        BENCHMARK_WRITER_LOCK_FUNCTION_BODY,
        BENCHMARK_WRITER_POLICY_FUNCTION_BODY,
        BENCHMARK_CANONICAL_WRITER_FUNCTION_BODY,
    )
    observed: dict[tuple[str, str], Any] = {}
    for row in rows:
        key = (str(row["table_name"]), str(row["trigger_name"]))
        if key in observed:
            raise ProjectionReceiptError("projection_receipt.writer_fence_invalid")
        observed[key] = row

    for table in tables:
        lock_name = f"trg_00_{table}_benchmark_writer_lock"
        policy_name = f"trg_{table}_benchmark_writer_fence"
        lock = observed.get((table, lock_name))
        policy = observed.get((table, policy_name))
        if (
            lock is None
            or policy is None
            or lock_name >= policy_name
            or not _exact_trigger(lock, function_name=_LOCK_FUNCTION, security_definer=True)
            or not _exact_trigger(
                policy,
                function_name=BENCHMARK_WRITER_FENCE_FUNCTION,
                security_definer=False,
            )
        ):
            raise ProjectionReceiptError("projection_receipt.writer_fence_invalid")
    if len(observed) != len(tables) * 2:
        raise ProjectionReceiptError("projection_receipt.writer_fence_invalid")


def _exact_trigger(row: Any, *, function_name: str, security_definer: bool) -> bool:
    return bool(
        row["trigger_enabled"] == "O"
        and row["trigger_type"] == 31
        and row["has_no_when_clause"] is True
        and row["has_no_update_column_filter"] is True
        and row["has_no_trigger_arguments"] is True
        and row["function_name"] == function_name
        and row["security_definer"] is security_definer
        and row["function_kind"] == "f"
        and row["returns_trigger"] is True
        and row["has_no_arguments"] is True
        and row["has_safe_search_path"] is True
        and row["has_exact_body"] is True
        and row["checker_has_exact_kind"] is True
        and row["checker_has_safe_search_path"] is True
        and row["checker_has_exact_body"] is True
        and row["checker_has_safe_owner"] is True
        and row["checker_has_exact_acl"] is True
        and row["sentinel_has_exact_before_insert_triggers"] is True
        and row["capability_execute_revoked"] is True
    )


__all__ = ("assert_strict_v4_writer_fence_topology",)
