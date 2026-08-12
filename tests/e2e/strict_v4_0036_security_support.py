"""Focused PostgreSQL catalog helpers for strict-v4 migration 0036."""

from __future__ import annotations

from pathlib import Path

from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_WRITER_FENCE_TABLES,
)
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_CANONICAL_WRITER_ROLE,
    STRICT_V4_CAPABILITY_ROLES,
    STRICT_V4_PROTECTED_RELATIONS,
    STRICT_V4_REGISTRAR_ROLE,
    STRICT_V4_SEALER_ROLE,
)

_POSTGRES_ROOT = (
    Path(__file__).parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres"
)
MIGRATION_0036_SQL = (
    _POSTGRES_ROOT / "migrations/0036_memory_comparison_strict_v4_preparations.sql"
).read_text(encoding="utf-8")
PROVISIONING_SQL = (_POSTGRES_ROOT / "provisioning/strict_v4_roles.sql").read_text(encoding="utf-8")

CORE_PROTECTED_FUNCTIONS = (
    "memory_cleanup_enforce_v3_context_authority_immutable",
    "memory_comparison_lock_strict_v4_registration_targets",
    "memory_comparison_lock_strict_v4_seal_targets",
    "memory_comparison_enforce_strict_v4_preparation_immutable",
    "memory_comparison_is_strict_v4_canonical_writer",
    "memory_comparison_lock_benchmark_writer_target",
    "memory_comparison_enforce_benchmark_writer_fence",
)
PROTECTED_SEQUENCES = (
    "memory_source_refs_id_seq",
    "memory_fact_versions_id_seq",
    "memory_outbox_id_seq",
    "memory_idempotency_records_id_seq",
)
_CHILD_READ_TABLES = (
    "memory_scopes",
    "memory_threads",
    "memory_facts",
    "memory_documents",
    "memory_chunks",
    "memory_fact_operation_receipts",
    "memory_idempotency_records",
    "memory_projection_result_receipts",
)
EXPECTED_TABLE_ACL = {
    STRICT_V4_CANONICAL_WRITER_ROLE: {
        "memory_comparison_benchmark_runs": {"SELECT"},
        "memory_cleanup_v3_context_authorities": {"SELECT"},
        "memory_comparison_strict_v4_preparations": {"SELECT"},
        "memory_idempotency_records": {"SELECT", "INSERT"},
    },
    STRICT_V4_REGISTRAR_ROLE: {
        "memory_comparison_benchmark_runs": {"SELECT"},
        "memory_cleanup_v3_context_authorities": {"SELECT", "INSERT"},
        **{table: {"SELECT"} for table in _CHILD_READ_TABLES},
    },
    STRICT_V4_SEALER_ROLE: {
        "memory_comparison_benchmark_runs": {"SELECT"},
        "memory_cleanup_v3_context_authorities": {"SELECT"},
        "memory_comparison_strict_v4_preparations": {"SELECT", "INSERT"},
        **{table: {"SELECT"} for table in _CHILD_READ_TABLES},
    },
}
EXPECTED_FUNCTION_ACL = {
    STRICT_V4_CANONICAL_WRITER_ROLE: {"memory_comparison_is_strict_v4_canonical_writer"},
    STRICT_V4_REGISTRAR_ROLE: {"memory_comparison_lock_strict_v4_registration_targets"},
    STRICT_V4_SEALER_ROLE: {"memory_comparison_lock_strict_v4_seal_targets"},
}


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def role_list(roles: tuple[str, ...]) -> str:
    return ", ".join(quote_identifier(role) for role in roles)


async def apply_0036(connection) -> None:
    transaction = connection.transaction()
    await transaction.start()
    try:
        await connection.execute(MIGRATION_0036_SQL)
    except BaseException:
        await transaction.rollback()
        raise
    await transaction.commit()


async def assert_postgres_18(connection) -> None:
    version = int(await connection.fetchval("SHOW server_version_num"))
    assert 180000 <= version < 190000


async def assert_capability_roles_are_safe(connection) -> None:
    rows = await connection.fetch(
        """
        SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
               rolreplication, rolbypassrls
        FROM pg_catalog.pg_roles
        WHERE rolname=ANY($1::pg_catalog.text[])
        ORDER BY rolname
        """,
        list(STRICT_V4_CAPABILITY_ROLES),
    )
    assert {row["rolname"] for row in rows} == set(STRICT_V4_CAPABILITY_ROLES)
    for row in rows:
        assert row["rolcanlogin"] is False
        assert row["rolsuper"] is False
        assert row["rolcreatedb"] is False
        assert row["rolcreaterole"] is False
        assert row["rolreplication"] is False
        assert row["rolbypassrls"] is False
    inherited_roles = await connection.fetchval(
        """
        SELECT pg_catalog.count(*)
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS member ON member.oid=membership.member
        WHERE member.rolname=ANY($1::pg_catalog.text[])
        """,
        list(STRICT_V4_CAPABILITY_ROLES),
    )
    assert inherited_roles == 0


async def assert_exact_0036_acls(connection) -> None:
    protected_tables = tuple(
        relation
        for relation in STRICT_V4_PROTECTED_RELATIONS
        if relation not in PROTECTED_SEQUENCES
    )
    relation_inventory = await connection.fetch(
        """
        SELECT relation.relname, relation.relkind::pg_catalog.text AS relkind
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid=relation.relnamespace
        WHERE namespace.nspname='public'
          AND relation.relname=ANY($1::pg_catalog.text[])
        ORDER BY relation.relname
        """,
        list(STRICT_V4_PROTECTED_RELATIONS),
    )
    assert [(row["relname"], row["relkind"]) for row in relation_inventory] == sorted(
        [(table, "r") for table in protected_tables]
        + [(sequence, "S") for sequence in PROTECTED_SEQUENCES]
    )
    table_rows = await connection.fetch(
        """
        SELECT relation.relname, grantee.rolname AS grantee,
               acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid=relation.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
        JOIN pg_catalog.pg_roles AS grantee ON grantee.oid=acl.grantee
        WHERE namespace.nspname='public'
          AND relation.relname=ANY($1::pg_catalog.text[])
          AND grantee.rolname=ANY($2::pg_catalog.text[])
        ORDER BY relation.relname, grantee.rolname, acl.privilege_type
        """,
        list(protected_tables),
        list(STRICT_V4_CAPABILITY_ROLES),
    )
    observed_tables = {
        (row["relname"], row["grantee"], row["privilege_type"], row["is_grantable"])
        for row in table_rows
    }
    expected_tables = {
        (table, role, privilege, False)
        for role, tables in EXPECTED_TABLE_ACL.items()
        for table, privileges in tables.items()
        for privilege in privileges
    }
    assert observed_tables == expected_tables

    public_table_acl = await connection.fetchval(
        """
        SELECT pg_catalog.count(*)
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid=relation.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
        WHERE namespace.nspname='public'
          AND relation.relname=ANY($1::pg_catalog.text[])
          AND acl.grantee=0
        """,
        list(STRICT_V4_PROTECTED_RELATIONS),
    )
    assert public_table_acl == 0

    column_acl = await connection.fetchval(
        """
        SELECT pg_catalog.count(*)
        FROM pg_catalog.pg_attribute AS attribute
        JOIN pg_catalog.pg_class AS relation ON relation.oid=attribute.attrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=relation.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
        LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid=acl.grantee
        WHERE namespace.nspname='public'
          AND relation.relname=ANY($1::pg_catalog.text[])
          AND (acl.grantee=0 OR grantee.rolname=ANY($2::pg_catalog.text[]))
        """,
        list(protected_tables),
        list(STRICT_V4_CAPABILITY_ROLES),
    )
    assert column_acl == 0

    sequence_rows = await connection.fetch(
        """
        SELECT relation.relname, grantee.rolname AS grantee,
               acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=relation.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
        JOIN pg_catalog.pg_roles AS grantee ON grantee.oid=acl.grantee
        WHERE namespace.nspname='public'
          AND relation.relname=ANY($1::pg_catalog.text[])
          AND grantee.rolname=ANY($2::pg_catalog.text[])
        """,
        list(PROTECTED_SEQUENCES),
        list(STRICT_V4_CAPABILITY_ROLES),
    )
    assert {
        (row["relname"], row["grantee"], row["privilege_type"], row["is_grantable"])
        for row in sequence_rows
    } == {
        (
            "memory_idempotency_records_id_seq",
            STRICT_V4_CANONICAL_WRITER_ROLE,
            "USAGE",
            False,
        )
    }

    function_inventory = await connection.fetch(
        """
        SELECT procedure.proname
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=procedure.pronamespace
        WHERE namespace.nspname='public'
          AND procedure.proname=ANY($1::pg_catalog.text[])
        ORDER BY procedure.proname
        """,
        list(CORE_PROTECTED_FUNCTIONS),
    )
    assert [row["proname"] for row in function_inventory] == sorted(CORE_PROTECTED_FUNCTIONS)

    function_rows = await connection.fetch(
        """
        SELECT procedure.proname, grantee.rolname AS grantee,
               acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=procedure.pronamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(procedure.proacl) AS acl
        JOIN pg_catalog.pg_roles AS grantee ON grantee.oid=acl.grantee
        WHERE namespace.nspname='public'
          AND procedure.proname=ANY($1::pg_catalog.text[])
          AND grantee.rolname=ANY($2::pg_catalog.text[])
        """,
        list(CORE_PROTECTED_FUNCTIONS),
        list(STRICT_V4_CAPABILITY_ROLES),
    )
    observed_functions = {
        (row["proname"], row["grantee"], row["privilege_type"], row["is_grantable"])
        for row in function_rows
    }
    expected_functions = {
        (function, role, "EXECUTE", False)
        for role, functions in EXPECTED_FUNCTION_ACL.items()
        for function in functions
    }
    assert observed_functions == expected_functions
    public_function_acl = await connection.fetchval(
        """
        SELECT pg_catalog.count(*)
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=procedure.pronamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(procedure.proacl, pg_catalog.acldefault('f', procedure.proowner))
        ) AS acl
        WHERE namespace.nspname='public'
          AND procedure.proname=ANY($1::pg_catalog.text[])
          AND acl.grantee=0
        """,
        list(CORE_PROTECTED_FUNCTIONS),
    )
    assert public_function_acl == 0

    schema_rows = await connection.fetch(
        """
        SELECT grantee.rolname AS grantee, acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_namespace AS namespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl
        JOIN pg_catalog.pg_roles AS grantee ON grantee.oid=acl.grantee
        WHERE namespace.nspname='public'
          AND grantee.rolname=ANY($1::pg_catalog.text[])
        """,
        list(STRICT_V4_CAPABILITY_ROLES),
    )
    assert {
        (row["grantee"], row["privilege_type"], row["is_grantable"]) for row in schema_rows
    } == {(role, "USAGE", False) for role in STRICT_V4_CAPABILITY_ROLES}
    public_schema_create = await connection.fetchval(
        """
        SELECT pg_catalog.count(*)
        FROM pg_catalog.pg_namespace AS namespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(namespace.nspacl, pg_catalog.acldefault('n', namespace.nspowner))
        ) AS acl
        WHERE namespace.nspname='public'
          AND acl.grantee=0
          AND acl.privilege_type='CREATE'
        """
    )
    assert public_schema_create == 0


async def assert_ordered_writer_triggers(connection) -> None:
    rows = await connection.fetch(
        """
        SELECT relation.relname, trigger.tgname,
               trigger.tgenabled::pg_catalog.text AS tgenabled,
               trigger.tgtype, trigger.tgqual IS NULL AS no_when,
               trigger.tgattr = ''::pg_catalog.int2vector AS no_columns,
               trigger.tgnargs, procedure.proname, procedure.prosecdef
        FROM pg_catalog.pg_trigger AS trigger
        JOIN pg_catalog.pg_class AS relation ON relation.oid=trigger.tgrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=relation.relnamespace
        JOIN pg_catalog.pg_proc AS procedure ON procedure.oid=trigger.tgfoid
        WHERE namespace.nspname='public'
          AND relation.relname=ANY($1::pg_catalog.text[])
          AND NOT trigger.tgisinternal
          AND trigger.tgname LIKE '%benchmark_writer%'
        ORDER BY relation.relname, trigger.tgname
        """,
        [table for table, _columns in BENCHMARK_WRITER_FENCE_TABLES],
    )
    observed = {
        (row["relname"], row["tgname"], row["proname"], row["prosecdef"])
        for row in rows
        if row["tgenabled"] == "O"
        and row["tgtype"] == 31
        and row["no_when"] is True
        and row["no_columns"] is True
        and row["tgnargs"] == 0
    }
    expected = {
        (
            table,
            trigger_name,
            function_name,
            security_definer,
        )
        for table, _columns in BENCHMARK_WRITER_FENCE_TABLES
        for trigger_name, function_name, security_definer in (
            (
                f"trg_00_{table}_benchmark_writer_lock",
                "memory_comparison_lock_benchmark_writer_target",
                True,
            ),
            (
                f"trg_{table}_benchmark_writer_fence",
                "memory_comparison_enforce_benchmark_writer_fence",
                False,
            ),
        )
    }
    assert observed == expected
    assert len(rows) == len(expected)


__all__ = (
    "CORE_PROTECTED_FUNCTIONS",
    "MIGRATION_0036_SQL",
    "PROTECTED_SEQUENCES",
    "PROVISIONING_SQL",
    "apply_0036",
    "assert_capability_roles_are_safe",
    "assert_exact_0036_acls",
    "assert_ordered_writer_triggers",
    "assert_postgres_18",
    "quote_identifier",
    "role_list",
)
