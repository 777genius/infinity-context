from __future__ import annotations

import re
from pathlib import Path

_POSTGRES = (
    Path(__file__).parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres"
)
_MIGRATION = _POSTGRES / "migrations/0036_memory_comparison_strict_v4_preparations.sql"
_PROVISIONING = _POSTGRES / "provisioning/strict_v4_roles.sql"
_ROLES = {
    "infinity_context_canonical_writer",
    "infinity_context_strict_v4_registrar",
    "infinity_context_strict_v4_sealer",
}
_AUTHORITY_0035 = {
    "memory_projection_receipt_claims",
    "memory_projection_target_identities",
    "memory_projection_receipt_identity_links",
    "memory_cleanup_inventory_materializations",
    "memory_cleanup_inventory_keys",
}


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_provisioning_owns_exactly_three_nologin_capabilities_and_schema_acl() -> None:
    sql = _normalized(_PROVISIONING)
    role_loop = sql.split("foreach capability_role in array array[", 1)[1].split("]", 1)[0]

    assert set(re.findall(r"'([^']+)'", role_loop)) == _ROLES
    assert "strict_v4_fact_writer" not in sql
    assert "strict_v4_document_writer" not in sql
    assert "set search_path = pg_catalog, public, pg_temp" in sql
    assert sql.endswith("reset search_path;")
    assert "create role %i nologin nosuperuser nocreatedb nocreaterole" in sql
    assert "noreplication nobypassrls" in sql
    assert "execute pg_catalog.format" in sql
    assert "revoke create on schema public from public" in sql
    assert "revoke all privileges on schema public" in sql
    assert "grant usage on schema public" in sql
    assert "pg_catalog.aclexplode(namespace.nspacl)" in sql
    assert "acl.privilege_type <> 'usage' or acl.is_grantable" in sql


def test_0036_is_qualified_role_ddl_free_and_below_the_file_cap() -> None:
    raw = _MIGRATION.read_text(encoding="utf-8")
    sql = " ".join(raw.lower().split())

    assert len(raw.splitlines()) <= 1000
    assert re.search(r"\b(create|alter|drop)\s+role\b", sql) is None
    assert "set local search_path = pg_catalog, public, pg_temp" in sql
    assert sql.endswith("set local search_path = public, pg_catalog, pg_temp;")
    assert "create table public.memory_comparison_strict_v4_preparations" in sql
    assert "references public.memory_comparison_benchmark_runs" in sql
    assert "references public.memory_cleanup_v3_context_authorities" in sql
    assert "create or replace function memory_" not in sql
    assert "execute function memory_" not in sql


def test_0036_normalizes_protected_table_column_sequence_and_function_acls() -> None:
    sql = _normalized(_MIGRATION)
    acl_loop = sql.split("foreach protected_relation in array array[", 1)[1].split("]", 1)[0]
    protected = set(re.findall(r"'([^']+)'", acl_loop))

    assert protected >= _AUTHORITY_0035
    assert {
        "memory_comparison_benchmark_runs",
        "memory_cleanup_v3_context_authorities",
        "memory_comparison_strict_v4_preparations",
        "memory_idempotency_records",
        "memory_source_refs",
        "memory_fact_versions",
        "memory_outbox",
    } <= protected
    assert "revoke all privileges on table public.%i from public" in sql
    assert "revoke select (%1$s), insert (%1$s), update (%1$s)" in sql
    assert "references (%1$s) on table public.%2$i from public" in sql
    assert "revoke all privileges on sequence public.memory_source_refs_id_seq" in sql
    assert "public.memory_idempotency_records_id_seq" in sql
    assert "grant select, insert on public.memory_idempotency_records" in sql
    assert "grant usage on sequence public.memory_idempotency_records_id_seq" in sql
    assert "grant insert on public.memory_facts" not in sql
    assert "revoke all privileges on function public.memory_comparison" in sql


def test_0036_preparation_is_fully_immutable_and_strict_scope_is_sentinel_only() -> None:
    sql = _normalized(_MIGRATION)
    immutable = sql.split(
        "create or replace function "
        "public.memory_comparison_enforce_strict_v4_preparation_immutable()",
        1,
    )[1].split("$$;", 1)[0]

    assert "raise exception 'strict-v4 preparation audit is immutable'" in immutable
    assert "return new" not in immutable
    assert "memory_comparison_close_strict_v4_preparation" not in sql
    assert "trg_benchmark_run_close_strict_v4_preparation" not in sql
    assert "legacy_write_authorized <> strict_v4_write_authorized" not in sql
    assert "strict_v4_writer_credential boolean := pg_catalog.pg_has_role(" in sql
    assert "strict_v4_authority_credential boolean := pg_catalog.pg_has_role(" in sql
    assert "if strict_v4_writer_credential then strict_v4_writer_login :=" in sql
    assert "if registry_state is null and not strict_v4_writer_credential" in sql
    assert (
        "not legacy_write_authorized and strict_v4_write_authorized "
        "and tg_table_name = "
        "'memory_idempotency_records'" in sql
    )
    assert "legacy_write_authorized and not strict_v4_writer_credential" in sql
    assert "and not strict_v4_authority_credential" in sql
    assert "pg_catalog.to_jsonb(old)" in sql
    assert "pg_catalog.to_jsonb(new)" in sql


def test_0036_authority_locks_reject_all_five_0035_tables_before_first_write() -> None:
    sql = _normalized(_MIGRATION)
    for function_name, durable_table, constraint_name in (
        (
            "memory_comparison_lock_strict_v4_registration_targets",
            "memory_cleanup_v3_context_authorities",
            "ck_memory_comparison_strict_v4_registration_pristine",
        ),
        (
            "memory_comparison_lock_strict_v4_seal_targets",
            "memory_comparison_strict_v4_preparations",
            "ck_memory_comparison_strict_v4_seal_pristine",
        ),
    ):
        body = sql.split(f"create or replace function public.{function_name}", 1)[1].split(
            "$$;", 1
        )[0]
        assert f"if not exists (select 1 from public.{durable_table}" in body
        assert all(f"public.{name}" in body for name in _AUTHORITY_0035)
        assert "using errcode = '23514'" in body
        assert constraint_name in body


def test_0036_preserves_ordered_noncallable_definer_then_invoker_policy() -> None:
    sql = _normalized(_MIGRATION)
    lock = sql.split(
        "create or replace function public.memory_comparison_lock_benchmark_writer_target()",
        1,
    )[1].split("$$;", 1)[0]
    policy = sql.split(
        "create or replace function public.memory_comparison_enforce_benchmark_writer_fence()",
        1,
    )[1].split("$$;", 1)[0]

    assert "security definer" in lock
    assert "security invoker" in policy
    assert "revoke all privileges on function public.memory_comparison_lock" in sql
    assert (
        "grant execute on function public.memory_comparison_lock_benchmark_writer_target" not in sql
    )
    assert "lock_trigger := 'trg_00_'" in sql
    assert "policy_trigger := 'trg_'" in sql
    assert "on public.%i" in sql
    assert "public.memory_comparison_lock_benchmark_writer_target()" in sql
    assert "public.memory_comparison_enforce_benchmark_writer_fence()" in sql


def test_0036_canonical_checker_rejects_acl_and_role_drift_at_insert_time() -> None:
    sql = _normalized(_MIGRATION)

    assert "not capability.rolcanlogin and not capability.rolsuper" in sql
    assert "from pg_catalog.pg_auth_members as membership" in sql
    assert "membership.admin_option" in sql
    assert "from pg_catalog.pg_attribute as attribute" in sql
    assert "acl.grantee in (0, role.oid, capability.oid)" in sql
    assert "acl.is_grantable" in sql
    assert "'trigger', 'maintain'" in sql
    assert "pg_catalog.has_function_privilege" in sql
    assert "acl.privilege_type = 'usage' and not acl.is_grantable" in sql
    assert "and not strict_v4_authority_exists" in sql
