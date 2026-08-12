from __future__ import annotations

import re
from pathlib import Path

from infinity_context_adapters.postgres.strict_v4_document_graph_fence import (
    STRICT_V4_DOCUMENT_CHILD_TABLES,
    STRICT_V4_DOCUMENT_GRAPH_FENCE_STATEMENTS,
)

_MIGRATION = (
    Path(__file__).parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/"
    "migrations/0038_strict_v4_document_writer.sql"
)
_FACT_MIGRATION = _MIGRATION.with_name("0037_strict_v4_fact_writer.sql")


def _normalize(value: str) -> str:
    return re.sub(r"[;\s]+", " ", value).strip().lower()


def test_document_graph_runtime_sql_is_pinned_in_migration() -> None:
    migration = _normalize(_MIGRATION.read_text(encoding="utf-8"))

    assert STRICT_V4_DOCUMENT_CHILD_TABLES == ("memory_chunks", "memory_outbox")
    for statement in STRICT_V4_DOCUMENT_GRAPH_FENCE_STATEMENTS:
        assert _normalize(statement) in migration


def test_document_and_fact_outbox_triggers_are_exactly_lane_scoped() -> None:
    migration = _normalize(_MIGRATION.read_text(encoding="utf-8"))

    assert "when (new.aggregate_type = 'fact')" in migration
    assert "when (old.aggregate_type = 'fact')" in migration
    assert "when (new.aggregate_type = 'chunk')" in migration
    assert "when (old.aggregate_type = 'chunk')" in migration
    assert "deferrable initially deferred" in migration
    assert "managed-benchmark-document-v4-%" in migration
    assert "memory_comparison_is_strict_v4_canonical_writer" in migration


def test_document_idempotency_policy_only_claims_document_scoped_records() -> None:
    migration = _normalize(_MIGRATION.read_text(encoding="utf-8"))

    generic_escape = (
        "if new.result_type <> 'document' and new.key not like "
        "'managed-benchmark-document-v4-%' then return new end if"
    )
    assert generic_escape in migration
    # Either document discriminator is enough to enter strict validation, so a
    # malformed receipt cannot evade it by corrupting only its type or key.
    assert "new.result_type <> 'document' and new.key not like" in migration
    assert ") or new.result_type <> 'document' or new.key not like" in migration


def test_canonical_writer_does_not_attest_retired_preparation_closer() -> None:
    migrations = tuple(
        _normalize(path.read_text(encoding="utf-8")) for path in (_FACT_MIGRATION, _MIGRATION)
    )

    assert all(
        "memory_comparison_close_strict_v4_preparation" not in migration for migration in migrations
    )
    document_migration = migrations[1]
    assert "memory_comparison_is_strict_v4_canonical_writer" in document_migration
    assert "memory_comparison_is_strict_v4_document_writer" not in document_migration
    assert "infinity_context_strict_v4_document_writer" not in document_migration
    assert "infinity_context_strict_v4_fact_writer" not in document_migration


def test_canonical_writer_attests_every_document_graph_function() -> None:
    fact_migration = _normalize(_FACT_MIGRATION.read_text(encoding="utf-8"))

    for function_name in (
        "memory_comparison_lock_benchmark_document_child_target",
        "memory_comparison_enforce_benchmark_document_child_fence",
        "memory_comparison_enforce_benchmark_document_idempotency",
        "memory_comparison_verify_benchmark_document_receipt",
    ):
        # Owner, direct/PUBLIC ACL, and exact effective EXECUTE inventories.
        assert fact_migration.count(f"'{function_name}'") == 4


def test_canonical_writer_checker_attests_capability_hardening() -> None:
    migration = _normalize(_FACT_MIGRATION.read_text(encoding="utf-8"))

    for invariant in (
        "cross join pg_catalog.pg_roles as capability",
        "capability.rolname = 'infinity_context_canonical_writer'",
        "not capability.rolcanlogin",
        "membership.admin_option",
        "acl.grantee = capability.oid and acl.is_grantable",
        "acl.grantee = role.oid or (acl.grantee = capability.oid and acl.is_grantable)",
        "acl.grantee in (0, role.oid, capability.oid)",
        "has_function_privilege( role.oid, procedure.oid, 'execute' ) is distinct from",
    ):
        assert invariant in migration


def test_document_graph_migration_stays_reviewable() -> None:
    assert len(_MIGRATION.read_text(encoding="utf-8").splitlines()) < 1_000
