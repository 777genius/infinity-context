from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_CANONICAL_WRITER_ROLE,
    STRICT_V4_CAPABILITY_ROLES,
    STRICT_V4_DOCUMENT_WRITER_ROLE,
    STRICT_V4_FACT_WRITER_ROLE,
    STRICT_V4_PROTECTED_RELATIONS,
    STRICT_V4_REGISTRAR_ROLE,
    STRICT_V4_SEALER_ROLE,
    assert_strict_v4_runtime_capability,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptError

_POSTGRES_ROOT = (
    Path(__file__).parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres"
)
_STRICT_V4_MIGRATIONS = (
    _POSTGRES_ROOT / "migrations/0036_memory_comparison_strict_v4_preparations.sql",
    _POSTGRES_ROOT / "migrations/0037_strict_v4_fact_writer.sql",
    _POSTGRES_ROOT / "migrations/0038_strict_v4_document_writer.sql",
)
_PROVISIONING_SQL = _POSTGRES_ROOT / "provisioning/strict_v4_roles.sql"
_MIGRATION_0035_AUTHORITY_TABLES = {
    "memory_projection_receipt_claims",
    "memory_projection_target_identities",
    "memory_projection_receipt_identity_links",
    "memory_cleanup_inventory_materializations",
    "memory_cleanup_inventory_keys",
}
_PROTECTED_FUNCTIONS = {
    "memory_cleanup_enforce_v3_context_authority_immutable",
    "memory_comparison_lock_strict_v4_registration_targets",
    "memory_comparison_lock_strict_v4_seal_targets",
    "memory_comparison_enforce_strict_v4_preparation_immutable",
    "memory_comparison_close_strict_v4_preparation",
    "memory_comparison_is_strict_v4_canonical_writer",
    "memory_comparison_lock_benchmark_writer_target",
    "memory_comparison_enforce_benchmark_writer_fence",
    "memory_comparison_lock_benchmark_fact_child_target",
    "memory_comparison_enforce_benchmark_fact_child_fence",
    "memory_comparison_enforce_benchmark_fact_receipt",
    "memory_comparison_verify_benchmark_fact_outbox_receipt",
    "memory_comparison_is_strict_v4_document_writer",
    "memory_comparison_lock_benchmark_document_child_target",
    "memory_comparison_enforce_benchmark_document_child_fence",
    "memory_comparison_enforce_benchmark_document_idempotency",
    "memory_comparison_verify_benchmark_document_receipt",
}


def _migration_sql() -> str:
    return _normalize_sql(
        "\n".join(path.read_text(encoding="utf-8") for path in _STRICT_V4_MIGRATIONS)
    )


class _Connection:
    def __init__(self, row):
        self.row = row
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return self.row


def _accepted_row():
    return {
        "direct_login": True,
        "role_member": True,
        "no_other_membership": True,
        "not_superuser": True,
        "no_bypass_rls": True,
        "no_createdb": True,
        "no_createrole": True,
        "no_replication": True,
        "owns_no_protected_relation": True,
        "owns_no_protected_schema": True,
        "cannot_create_in_protected_schema": True,
        "owns_no_protected_function": True,
        "has_no_direct_relation_acl": True,
        "has_no_direct_schema_acl": True,
        "has_no_direct_function_acl": True,
        "has_no_public_relation_acl": True,
        "has_no_public_function_acl": True,
        "has_exact_effective_relation_acl": True,
        "has_exact_effective_sequence_acl": True,
    }


def test_exact_non_owner_single_capability_login_is_accepted() -> None:
    connection = _Connection(_accepted_row())

    asyncio.run(
        assert_strict_v4_runtime_capability(
            connection,
            capability_role=STRICT_V4_REGISTRAR_ROLE,
            error_code="denied",
        )
    )

    _sql, args = connection.calls[0]
    assert args[0] == STRICT_V4_REGISTRAR_ROLE
    assert set(args[1]) == set(STRICT_V4_PROTECTED_RELATIONS)


def test_all_migration_0035_authority_tables_are_runtime_protected() -> None:
    assert set(STRICT_V4_PROTECTED_RELATIONS) >= _MIGRATION_0035_AUTHORITY_TABLES


def test_migration_protects_all_0035_authority_tables_from_every_capability() -> None:
    sql = _migration_sql()
    roles = {
        "public",
        STRICT_V4_CANONICAL_WRITER_ROLE,
        STRICT_V4_FACT_WRITER_ROLE,
        STRICT_V4_DOCUMENT_WRITER_ROLE,
        STRICT_V4_REGISTRAR_ROLE,
        STRICT_V4_SEALER_ROLE,
    }

    for table in _MIGRATION_0035_AUTHORITY_TABLES:
        assert table in sql
        assert roles <= _relation_revoke_grantees(sql, table)
        assert _relation_privileges(sql, table, roles) == set()


def test_migration_preserves_the_exact_relation_capability_matrix() -> None:
    sql = _migration_sql()
    expected = {
        STRICT_V4_CANONICAL_WRITER_ROLE: {
            "memory_comparison_benchmark_runs": {"select"},
            "memory_cleanup_v3_context_authorities": {"select"},
            "memory_comparison_strict_v4_preparations": {"select"},
            "memory_idempotency_records": {"select", "insert"},
        },
        STRICT_V4_FACT_WRITER_ROLE: {
            "memory_comparison_benchmark_runs": {"select"},
            "memory_cleanup_v3_context_authorities": {"select"},
            "memory_comparison_strict_v4_preparations": {"select"},
            "memory_spaces": {"select"},
            "memory_scopes": {"select", "insert"},
            "memory_threads": {"select", "insert"},
            "memory_facts": {"select", "insert"},
            "memory_fact_versions": {"select", "insert"},
            "memory_source_refs": {"select", "insert", "delete"},
            "memory_outbox": {"select", "insert"},
            "memory_fact_operation_receipts": {"select", "insert"},
        },
        STRICT_V4_DOCUMENT_WRITER_ROLE: {
            "memory_comparison_benchmark_runs": {"select"},
            "memory_cleanup_v3_context_authorities": {"select"},
            "memory_comparison_strict_v4_preparations": {"select"},
            "memory_spaces": {"select"},
            "memory_scopes": {"select", "insert"},
            "memory_threads": {"select", "insert"},
            "memory_documents": {"select", "insert"},
            "memory_chunks": {"select", "insert"},
            "memory_outbox": {"select", "insert"},
            "memory_idempotency_records": {"select", "insert"},
        },
        STRICT_V4_REGISTRAR_ROLE: {
            "memory_comparison_benchmark_runs": {"select"},
            "memory_cleanup_v3_context_authorities": {"select", "insert"},
            "memory_scopes": {"select"},
            "memory_threads": {"select"},
            "memory_facts": {"select"},
            "memory_documents": {"select"},
            "memory_chunks": {"select"},
            "memory_fact_operation_receipts": {"select"},
            "memory_idempotency_records": {"select"},
            "memory_projection_result_receipts": {"select"},
        },
        STRICT_V4_SEALER_ROLE: {
            "memory_comparison_benchmark_runs": {"select"},
            "memory_cleanup_v3_context_authorities": {"select"},
            "memory_comparison_strict_v4_preparations": {"select", "insert"},
            "memory_scopes": {"select"},
            "memory_threads": {"select"},
            "memory_facts": {"select"},
            "memory_documents": {"select"},
            "memory_chunks": {"select"},
            "memory_fact_operation_receipts": {"select"},
            "memory_idempotency_records": {"select"},
            "memory_projection_result_receipts": {"select"},
        },
    }
    relation_names = set(STRICT_V4_PROTECTED_RELATIONS) - {
        name for name in STRICT_V4_PROTECTED_RELATIONS if name.endswith("_seq")
    }
    denied_grantees = {"public", *STRICT_V4_CAPABILITY_ROLES}

    for relation in relation_names:
        assert denied_grantees <= _relation_revoke_grantees(sql, relation)
        assert _relation_privileges(sql, relation, {"public"}) == set()

    for role in STRICT_V4_CAPABILITY_ROLES:
        observed = {
            relation: privileges
            for relation in relation_names
            if (privileges := _relation_privileges(sql, relation, {role}))
        }
        assert observed == expected[role]

    assert _sequence_privileges(
        sql,
        "memory_idempotency_records_id_seq",
        STRICT_V4_CANONICAL_WRITER_ROLE,
    ) == {"usage"}
    for role in (STRICT_V4_REGISTRAR_ROLE, STRICT_V4_SEALER_ROLE):
        assert _sequence_privileges(sql, "memory_idempotency_records_id_seq", role) == set()
    for sequence in (
        "memory_source_refs_id_seq",
        "memory_fact_versions_id_seq",
        "memory_outbox_id_seq",
    ):
        assert _sequence_privileges(sql, sequence, STRICT_V4_FACT_WRITER_ROLE) == {"usage"}
    assert _sequence_privileges(
        sql,
        "memory_outbox_id_seq",
        STRICT_V4_DOCUMENT_WRITER_ROLE,
    ) == {"usage"}
    assert _sequence_privileges(
        sql,
        "memory_idempotency_records_id_seq",
        STRICT_V4_DOCUMENT_WRITER_ROLE,
    ) == {"usage"}


def test_public_and_capabilities_cannot_create_or_execute_internal_lock() -> None:
    migration = _migration_sql()
    provisioning = _normalize_sql(_PROVISIONING_SQL.read_text(encoding="utf-8"))

    assert (
        "revoke create on schema public from public, "
        "infinity_context_canonical_writer, infinity_context_strict_v4_fact_writer, "
        "infinity_context_strict_v4_document_writer, "
        "infinity_context_strict_v4_registrar, "
        "infinity_context_strict_v4_sealer ;"
    ) in provisioning
    capability_sql = _capability_sql()
    obsolete = "memory_comparison_lock_read_strict_v4_canonical_run"
    actual = "memory_comparison_lock_benchmark_writer_target"
    assert obsolete not in migration
    assert obsolete not in capability_sql
    assert actual in migration
    assert actual in capability_sql
    assert (
        "revoke all on function memory_comparison_lock_benchmark_writer_target() "
        "from public, infinity_context_canonical_writer, "
        "infinity_context_strict_v4_registrar, infinity_context_strict_v4_sealer"
    ) in migration


def test_migration_preserves_exact_protected_function_execute_matrix() -> None:
    sql = _migration_sql()
    denied_grantees = {"public", *STRICT_V4_CAPABILITY_ROLES}
    expected = {
        STRICT_V4_CANONICAL_WRITER_ROLE: {
            "memory_comparison_is_strict_v4_canonical_writer",
            "memory_comparison_is_strict_v4_document_writer",
        },
        STRICT_V4_FACT_WRITER_ROLE: {
            "memory_comparison_is_strict_v4_canonical_writer",
            "memory_comparison_is_strict_v4_document_writer",
        },
        STRICT_V4_DOCUMENT_WRITER_ROLE: {
            "memory_comparison_is_strict_v4_canonical_writer",
            "memory_comparison_is_strict_v4_document_writer",
        },
        STRICT_V4_REGISTRAR_ROLE: {"memory_comparison_lock_strict_v4_registration_targets"},
        STRICT_V4_SEALER_ROLE: {"memory_comparison_lock_strict_v4_seal_targets"},
    }

    for function in _PROTECTED_FUNCTIONS:
        assert denied_grantees <= _function_revoke_grantees(sql, function)
        assert _function_privileges(sql, function, "public") == set()
    for role in STRICT_V4_CAPABILITY_ROLES:
        observed = {
            function
            for function in _PROTECTED_FUNCTIONS
            if _function_privileges(sql, function, role) == {"execute"}
        }
        assert observed == expected[role]

    final_normalization = sql
    assert (
        "grant execute on function "
        "public.memory_comparison_lock_strict_v4_registration_targets(char, char) "
        "to infinity_context_strict_v4_registrar"
    ) in final_normalization
    assert (
        "grant execute on function "
        "public.memory_comparison_lock_strict_v4_seal_targets(char, char) "
        "to infinity_context_strict_v4_sealer"
    ) in final_normalization


@pytest.mark.parametrize(
    "rejected_field",
    (
        "direct_login",
        "role_member",
        "no_other_membership",
        "not_superuser",
        "no_bypass_rls",
        "no_createdb",
        "no_createrole",
        "no_replication",
        "owns_no_protected_relation",
        "owns_no_protected_schema",
        "cannot_create_in_protected_schema",
        "owns_no_protected_function",
        "has_no_direct_relation_acl",
        "has_no_direct_schema_acl",
        "has_no_direct_function_acl",
        "has_no_public_relation_acl",
        "has_no_public_function_acl",
        "has_exact_effective_relation_acl",
        "has_exact_effective_sequence_acl",
    ),
)
def test_privileged_multirole_or_owner_login_is_rejected(rejected_field: str) -> None:
    row = _accepted_row()
    row[rejected_field] = False

    with pytest.raises(ProjectionReceiptError, match="denied"):
        asyncio.run(
            assert_strict_v4_runtime_capability(
                _Connection(row),
                capability_role=STRICT_V4_REGISTRAR_ROLE,
                error_code="denied",
            )
        )


def test_missing_attestation_field_is_rejected_fail_closed() -> None:
    row = _accepted_row()
    row.pop("has_no_public_relation_acl")

    with pytest.raises(ProjectionReceiptError, match="denied"):
        asyncio.run(
            assert_strict_v4_runtime_capability(
                _Connection(row),
                capability_role=STRICT_V4_REGISTRAR_ROLE,
                error_code="denied",
            )
        )


def test_unknown_capability_is_rejected_without_query() -> None:
    connection = _Connection(_accepted_row())

    with pytest.raises(ProjectionReceiptError, match="denied"):
        asyncio.run(
            assert_strict_v4_runtime_capability(
                connection,
                capability_role="untrusted",
                error_code="denied",
            )
        )
    assert connection.calls == []


def _normalize_sql(value: str) -> str:
    return " ".join(value.lower().replace(";", " ; ").split())


def _capability_sql() -> str:
    connection = _Connection(_accepted_row())
    asyncio.run(
        assert_strict_v4_runtime_capability(
            connection,
            capability_role=STRICT_V4_REGISTRAR_ROLE,
            error_code="denied",
        )
    )
    return _normalize_sql(connection.calls[0][0])


def _relation_privileges(sql: str, relation: str, grantees: set[str]) -> set[str]:
    observed: set[str] = set()
    for privileges, relations, roles in re.findall(
        r"grant ([a-z, ]+) on (?!function|sequence)(.+?) to (.+?) ;", sql
    ):
        relation_set = {item.strip().removeprefix("public.") for item in relations.split(",")}
        role_set = {item.strip() for item in roles.split(",")}
        if relation in relation_set and role_set & grantees:
            observed.update(item.strip() for item in privileges.split(","))
    return observed


def _relation_revoke_grantees(sql: str, relation: str) -> set[str]:
    observed: set[str] = set()
    for relations, roles in re.findall(
        r"revoke all on (?!function|sequence)(.+?) from (.+?) ;", sql
    ):
        relation_set = {item.strip().removeprefix("public.") for item in relations.split(",")}
        if relation in relation_set:
            observed.update(item.strip() for item in roles.split(","))
    return observed


def _sequence_privileges(sql: str, sequence: str, grantee: str) -> set[str]:
    observed: set[str] = set()
    for privileges, sequences, roles in re.findall(
        r"grant ([a-z, ]+) on sequence (.+?) to (.+?) ;", sql
    ):
        sequence_set = {item.strip().removeprefix("public.") for item in sequences.split(",")}
        role_set = {item.strip() for item in roles.split(",")}
        if sequence in sequence_set and grantee in role_set:
            observed.update(item.strip() for item in privileges.split(","))
    return observed


def _function_revoke_grantees(sql: str, function: str) -> set[str]:
    observed: set[str] = set()
    for signatures, roles in re.findall(r"revoke all on function (.+?) from (.+?) ;", sql):
        names = {
            name.removeprefix("public.")
            for name in re.findall(r"([a-z0-9_.]+)\([^)]*\)", signatures)
        }
        if function in names:
            observed.update(item.strip() for item in roles.split(","))
    return observed


def _function_privileges(sql: str, function: str, grantee: str) -> set[str]:
    observed: set[str] = set()
    for privileges, signatures, roles in re.findall(
        r"grant ([a-z, ]+) on function (.+?) to (.+?) ;", sql
    ):
        names = {
            name.removeprefix("public.")
            for name in re.findall(r"([a-z0-9_.]+)\([^)]*\)", signatures)
        }
        if function in names and grantee in {item.strip() for item in roles.split(",")}:
            observed.update(item.strip() for item in privileges.split(","))
    return observed
