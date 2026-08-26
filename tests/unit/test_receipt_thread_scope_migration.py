from hashlib import sha256
from pathlib import Path

import pytest
from infinity_context_adapters.postgres.migration_metadata import (
    PUBLISHED_MIGRATION_CHECKSUMS,
)
from infinity_context_adapters.postgres.migration_runner import (
    _Migration,
    _validate_history,
)

_MIGRATIONS = (
    Path(__file__).resolve().parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
)


def test_published_receipt_migration_repair_keeps_one_explicit_checksum_alias() -> None:
    expected = {
        "0029_schema_parity_and_fact_tenant_integrity.sql": (
            "f5d60fc31735a28d249cf0a40ae1d745761f49afea7a6c01169d4c12e714bfbe"
        ),
        "0030_suggestion_receipt_tenant_integrity.sql": (
            "9565ce71c4e2e2c69fe38a7e105bc221c8570a6abe8af055a89da46461d62322"
        ),
    }

    for name, checksum in expected.items():
        assert sha256((_MIGRATIONS / name).read_bytes()).hexdigest() == checksum
    assert PUBLISHED_MIGRATION_CHECKSUMS["0030_suggestion_receipt_tenant_integrity"] == (
        frozenset(
            {"4d936c3d49f76028eec009a1b1e8ee2bcf214b2b4a03e7ac120bad5321aa3064"}
        )
    )


def test_published_checksum_alias_accepts_only_the_exact_released_digest() -> None:
    migration_id = "0030_suggestion_receipt_tenant_integrity"
    migration = _Migration(migration_id=migration_id, checksum="current", sql="")
    released = next(iter(PUBLISHED_MIGRATION_CHECKSUMS[migration_id]))

    _validate_history((migration,), {migration_id: released})
    with pytest.raises(RuntimeError, match="migration checksum drift"):
        _validate_history((migration,), {migration_id: "unpublished-digest"})


def test_receipt_and_thread_scope_migration_is_locked_and_append_only() -> None:
    sql = (_MIGRATIONS / "0032_receipt_and_thread_scope_integrity.sql").read_text(
        encoding="utf-8"
    )

    assert sql.startswith("LOCK TABLE")
    assert "memory_fact_operation_receipts" in sql
    assert "suggestion_resolution_receipts" in sql
    assert sql.count(") STORED NOT NULL;") == 2
    assert "uq_memory_facts_id_scope_thread" in sql
    assert "uq_memory_fact_temporal_decisions_id_scope_thread" in sql
    assert "BEFORE INSERT ON memory_fact_operation_receipts" in sql
    assert "BEFORE INSERT ON suggestion_resolution_receipts" in sql
    assert sql.count("BEFORE UPDATE OR DELETE") == 2
    assert "ERRCODE = '55000'" in sql
    first_preflight = sql.index("fact thread scope integrity preflight failed")
    first_schema_change = sql.index("ADD COLUMN IF NOT EXISTS thread_scope_key")
    relation_backfill = sql.index("UPDATE memory_fact_relations relation")
    assert sql.index("LOCK TABLE") < first_schema_change < relation_backfill < first_preflight
    for typed_predicate in (
        "result_snapshot_json -> 'schema_version'",
        "result_snapshot_json #> '{identity,thread_id}'",
        "result_snapshot_json #> '{visibility,version}'",
        "result_suggestion_json -> 'schema_version'",
        "result_suggestion_json -> 'id'",
        "result_fact_json -> 'schema_version'",
        "result_fact_json #> '{identity,thread_id}'",
        "result_fact_json #> '{visibility,version}'",
    ):
        assert typed_predicate in sql
