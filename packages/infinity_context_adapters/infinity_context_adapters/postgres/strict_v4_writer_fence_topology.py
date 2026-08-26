"""Catalog attestation for the ordered strict-v4 canonical writer fence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infinity_context_core.features.projection_receipts import ProjectionReceiptError

from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_CANONICAL_WRITER_FUNCTION_BODY,
    BENCHMARK_WRITER_FENCE_FUNCTION,
    BENCHMARK_WRITER_FENCE_TABLES,
    BENCHMARK_WRITER_LOCK_FUNCTION_BODY,
)
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_CANONICAL_WRITER_ROLE,
    STRICT_V4_REGISTRAR_ROLE,
    STRICT_V4_SEALER_ROLE,
)

_LOCK_FUNCTION = "memory_comparison_lock_benchmark_writer_target"
_SAFE_SEARCH_PATH = "search_path=pg_catalog, public, pg_temp"
_FINAL_SAFE_SEARCH_PATH = "search_path=pg_catalog, public"
_ALL_WRITER_FENCE_ROLES = (
    STRICT_V4_CANONICAL_WRITER_ROLE,
    STRICT_V4_REGISTRAR_ROLE,
    STRICT_V4_SEALER_ROLE,
)


def _migration_checker_body(migration_name: str) -> str:
    """Extract the checker body from its packaged, checksum-pinned migration."""

    sql = (Path(__file__).with_name("migrations") / migration_name).read_text(encoding="utf-8")
    match = re.search(
        r"CREATE OR REPLACE FUNCTION (?:public\.)?"
        r"memory_comparison_is_strict_v4_canonical_writer\(\).*?"
        r"\bAS \$\$(.*?)\$\$;",
        sql,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError(f"Canonical checker missing from {migration_name}")
    return match.group(1)


_CHECKER_BODY_0037 = _migration_checker_body("0037_strict_v4_fact_writer.sql")


def _migration_function_body(migration_name: str, function_name: str) -> str:
    sql = (Path(__file__).with_name("migrations") / migration_name).read_text(encoding="utf-8")
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION (?:public\.)?{function_name}\(\).*?"
        r"\bAS \$\$(.*?)\$\$;",
        sql,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError(f"{function_name} missing from {migration_name}")
    return match.group(1)


_DOCUMENT_POLICY_BODY_0038 = _migration_function_body(
    "0038_strict_v4_document_writer.sql",
    "memory_comparison_enforce_benchmark_document_idempotency",
)
_WRITER_POLICY_BODY_0037 = _migration_function_body(
    "0037_strict_v4_fact_writer.sql",
    BENCHMARK_WRITER_FENCE_FUNCTION,
)
_WRITER_POLICY_BODY_0036 = _migration_function_body(
    "0036_memory_comparison_strict_v4_preparations.sql",
    BENCHMARK_WRITER_FENCE_FUNCTION,
)


@dataclass(frozen=True, slots=True)
class _Profile:
    checker_body: str
    checker_search_path: str
    policy_body: str
    execute_roles: tuple[str, ...]
    sentinel_names: tuple[str, ...]
    sentinel_functions: tuple[str, ...]
    sentinel_types: tuple[int, ...]
    requires_document_policy: bool


_LEGACY_0036_PROFILE = _Profile(
    BENCHMARK_CANONICAL_WRITER_FUNCTION_BODY,
    _SAFE_SEARCH_PATH,
    _WRITER_POLICY_BODY_0036,
    ("infinity_context_canonical_writer",),
    (
        "trg_00_memory_idempotency_records_benchmark_writer_lock",
        "trg_memory_idempotency_records_benchmark_writer_fence",
    ),
    (_LOCK_FUNCTION, BENCHMARK_WRITER_FENCE_FUNCTION),
    (31, 31),
    False,
)
_FINAL_PROFILE = _Profile(
    _CHECKER_BODY_0037,
    _FINAL_SAFE_SEARCH_PATH,
    _WRITER_POLICY_BODY_0037,
    ("infinity_context_canonical_writer",),
    (
        "trg_00_memory_idempotency_records_benchmark_writer_lock",
        "trg_memory_idempotency_benchmark_document_policy",
        "trg_memory_idempotency_records_benchmark_writer_fence",
    ),
    (
        _LOCK_FUNCTION,
        "memory_comparison_enforce_benchmark_document_idempotency",
        BENCHMARK_WRITER_FENCE_FUNCTION,
    ),
    (31, 7, 31),
    True,
)

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
checker_phase AS (
    SELECT expected.*, canonical_checker.proowner AS checker_owner
    FROM (
        SELECT $6::pg_catalog.text AS body,
               $7::pg_catalog.text AS safe_path,
               $8::pg_catalog.text[] AS execute_roles
    ) AS expected
    JOIN canonical_checker ON canonical_checker.prosrc=expected.body
    WHERE NOT canonical_checker.prosecdef
      AND canonical_checker.prokind='f'
      AND canonical_checker.provolatile='s'
      AND canonical_checker.language_name='sql'
      AND canonical_checker.prorettype='pg_catalog.bool'::pg_catalog.regtype
      AND canonical_checker.pronargs=0
      AND canonical_checker.proconfig=ARRAY[expected.safe_path]::pg_catalog.text[]
      AND canonical_checker.owner_name<>ALL($2::pg_catalog.text[])
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.aclexplode(
              COALESCE(
                  canonical_checker.proacl,
                  pg_catalog.acldefault('f', canonical_checker.proowner)
              )
          ) AS acl
          LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid=acl.grantee
          WHERE (
                  acl.grantee<>canonical_checker.proowner
                  AND (
                      grantee.rolname IS NULL
                      OR grantee.rolname<>ALL(expected.execute_roles)
                  )
                )
             OR acl.privilege_type<>'EXECUTE'
             OR acl.is_grantable
      )
      AND (
          SELECT pg_catalog.count(*)=
              1 + pg_catalog.cardinality(expected.execute_roles)
          FROM pg_catalog.aclexplode(
              COALESCE(
                  canonical_checker.proacl,
                  pg_catalog.acldefault('f', canonical_checker.proowner)
              )
          ) AS acl
      )
      AND (
          SELECT pg_catalog.count(*)=
              pg_catalog.cardinality(expected.execute_roles)
          FROM pg_catalog.aclexplode(
              COALESCE(
                  canonical_checker.proacl,
                  pg_catalog.acldefault('f', canonical_checker.proowner)
              )
          ) AS acl
          LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid=acl.grantee
          WHERE grantee.rolname=ANY(expected.execute_roles)
            AND acl.privilege_type='EXECUTE'
            AND NOT acl.is_grantable
      )
),
sentinel_before_insert AS (
    SELECT pg_catalog.array_agg(candidate.tgname ORDER BY candidate.tgname)=$9
       AND pg_catalog.array_agg(function.oid ORDER BY candidate.tgname)=ARRAY(
               SELECT pg_catalog.to_regprocedure('public.' || name || '()')::pg_catalog.oid
               FROM pg_catalog.unnest($10::pg_catalog.text[]) AS expected(name)
           )
       AND pg_catalog.array_agg(candidate.tgtype ORDER BY candidate.tgname)=$11
       AND pg_catalog.bool_and(candidate.tgenabled='O')
       AND pg_catalog.bool_and(candidate.tgqual IS NULL)
       AND pg_catalog.bool_and(candidate.tgattr=''::pg_catalog.int2vector)
       AND pg_catalog.bool_and(candidate.tgnargs=0) AS has_exact_inventory
    FROM pg_catalog.pg_trigger AS candidate
    JOIN pg_catalog.pg_class AS relation ON relation.oid=candidate.tgrelid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid=relation.relnamespace
    JOIN pg_catalog.pg_proc AS function ON function.oid=candidate.tgfoid
    CROSS JOIN checker_phase
    WHERE namespace.nspname='public'
      AND relation.relname='memory_idempotency_records'
      AND NOT candidate.tgisinternal
      AND candidate.tgtype & 2 = 2
),
document_policy AS (
    SELECT COALESCE((
        SELECT procedure.prokind='f'
           AND NOT procedure.prosecdef
           AND procedure.provolatile='v'
           AND language.lanname='plpgsql'
           AND procedure.prorettype='pg_catalog.trigger'::pg_catalog.regtype
           AND procedure.pronargs=0
           AND procedure.proconfig=ARRAY[$3]::pg_catalog.text[]
           AND procedure.prosrc=$12
           AND owner.rolname<>ALL($2::pg_catalog.text[])
           AND NOT EXISTS (
               SELECT 1
               FROM pg_catalog.aclexplode(COALESCE(
                   procedure.proacl, pg_catalog.acldefault('f', procedure.proowner)
               )) AS acl
               WHERE acl.grantee<>procedure.proowner
                  OR acl.privilege_type<>'EXECUTE'
                  OR acl.is_grantable
           )
           AND (
               SELECT pg_catalog.count(*)=1
               FROM pg_catalog.aclexplode(COALESCE(
                   procedure.proacl, pg_catalog.acldefault('f', procedure.proowner)
               )) AS acl
               WHERE acl.grantee=procedure.proowner
                 AND acl.privilege_type='EXECUTE'
                 AND NOT acl.is_grantable
           )
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_roles AS owner ON owner.oid=procedure.proowner
        JOIN pg_catalog.pg_language AS language ON language.oid=procedure.prolang
        WHERE procedure.oid=pg_catalog.to_regprocedure(
            'public.memory_comparison_enforce_benchmark_document_idempotency()'
        )
    ), FALSE) AS is_exact
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
       function.prokind='f'
         AND function.provolatile='v'
         AND function_language.lanname='plpgsql' AS function_has_exact_kind,
       function.prorettype = 'pg_catalog.trigger'::pg_catalog.regtype AS returns_trigger,
       pg_catalog.pg_get_function_identity_arguments(function.oid) = '' AS has_no_arguments,
       function.proconfig = ARRAY[$3]::pg_catalog.text[] AS has_safe_search_path,
       function.prosrc = CASE function.proname
           WHEN 'memory_comparison_lock_benchmark_writer_target' THEN $4
           ELSE $5
       END AS has_exact_body,
       TRUE AS checker_has_exact_kind,
       TRUE AS checker_has_safe_search_path,
       TRUE AS checker_has_exact_body,
       TRUE AS checker_has_safe_owner,
       sentinel_before_insert.has_exact_inventory
         AS sentinel_has_exact_before_insert_triggers,
       (NOT $13::pg_catalog.bool OR document_policy.is_exact)
         AS document_policy_is_exact,
       TRUE AS checker_has_exact_acl,
       function_owner.rolname<>ALL($2::pg_catalog.text[])
         AS function_has_safe_owner,
       NOT EXISTS (
           SELECT 1
           FROM pg_catalog.aclexplode(
               COALESCE(
                   function.proacl,
                   pg_catalog.acldefault('f', function.proowner)
               )
           ) AS acl
           LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid=acl.grantee
           WHERE acl.grantee<>function.proowner
              OR acl.privilege_type<>'EXECUTE'
              OR acl.is_grantable
       )
       AND (
           SELECT pg_catalog.count(*)=1
           FROM pg_catalog.aclexplode(COALESCE(
               function.proacl, pg_catalog.acldefault('f', function.proowner)
           )) AS acl
           WHERE acl.grantee=function.proowner
             AND acl.privilege_type='EXECUTE'
             AND NOT acl.is_grantable
       ) AS function_has_exact_acl
FROM pg_catalog.pg_trigger AS trigger
JOIN pg_catalog.pg_class AS relation ON relation.oid=trigger.tgrelid
JOIN pg_catalog.pg_namespace AS relation_schema
  ON relation_schema.oid=relation.relnamespace
JOIN pg_catalog.pg_proc AS function ON function.oid=trigger.tgfoid
JOIN pg_catalog.pg_namespace AS function_schema
  ON function_schema.oid=function.pronamespace
JOIN pg_catalog.pg_language AS function_language
  ON function_language.oid=function.prolang
JOIN pg_catalog.pg_roles AS function_owner ON function_owner.oid=function.proowner
CROSS JOIN canonical_checker
CROSS JOIN checker_phase
CROSS JOIN sentinel_before_insert
CROSS JOIN document_policy
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

    await _assert_strict_v4_writer_fence_topology(connection, profile=_FINAL_PROFILE)


async def _assert_strict_v4_writer_fence_topology_0036_compat(connection: Any) -> None:
    """Attest only an isolated migration-0036 compatibility fixture."""

    await _assert_strict_v4_writer_fence_topology(connection, profile=_LEGACY_0036_PROFILE)


async def _assert_strict_v4_writer_fence_topology(connection: Any, *, profile: _Profile) -> None:
    tables = tuple(table for table, _columns in BENCHMARK_WRITER_FENCE_TABLES)
    rows = await connection.fetch(
        _TOPOLOGY_SQL,
        list(tables),
        list(_ALL_WRITER_FENCE_ROLES),
        _SAFE_SEARCH_PATH,
        BENCHMARK_WRITER_LOCK_FUNCTION_BODY,
        profile.policy_body,
        profile.checker_body,
        profile.checker_search_path,
        list(profile.execute_roles),
        list(profile.sentinel_names),
        list(profile.sentinel_functions),
        list(profile.sentinel_types),
        _DOCUMENT_POLICY_BODY_0038,
        profile.requires_document_policy,
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
        and row["function_has_exact_kind"] is True
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
        and row["document_policy_is_exact"] is True
        and row["function_has_safe_owner"] is True
        and row["function_has_exact_acl"] is True
    )


__all__ = ("assert_strict_v4_writer_fence_topology",)
