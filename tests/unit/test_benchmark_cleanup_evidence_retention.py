from pathlib import Path

from infinity_context_adapters.postgres.benchmark_run_completion import (
    _cleanup_outbox_rows_query,
)
from sqlalchemy.dialects import postgresql


def test_cleanup_completion_locks_exact_outbox_evidence_rows() -> None:
    sql = str(_cleanup_outbox_rows_query((1, 2)).compile(dialect=postgresql.dialect()))

    assert "memory_outbox.id IN" in sql
    assert "ORDER BY memory_outbox.id" in sql
    assert "FOR UPDATE" in sql


def test_completion_migration_skips_only_absent_optional_fence_tables() -> None:
    migration = Path(
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0020_benchmark_cleanup_completion.sql"
    ).read_text()

    assert "pg_catalog.to_regclass" in migration
    assert "IF table_name = ANY(required_table_names)" in migration
    assert "USING ERRCODE = '42P01'" in migration
    assert "CONTINUE;" in migration
    assert "ON %I.%I" in migration
    assert "FOR SHARE NOWAIT" in migration
    assert "WHEN lock_not_available THEN" in migration
    assert "registry_projection_cleanup_state = 'unsealed'" in migration
    assert "registry_projection_cleanup_state IN ('pending', 'blocked')" in migration
    assert "OLD.status = 'active'" in migration
    assert "NEW.status = 'deleted'" in migration
    assert "to_jsonb(OLD) - 'status' - 'updated_at'" in migration
    required_block = migration.split("required_table_names CONSTANT TEXT[] := ARRAY[", 1)[1].split(
        "]", 1
    )[0]
    for table_name in (
        "memory_spaces",
        "memory_scopes",
        "memory_threads",
        "memory_facts",
        "memory_episodes",
        "memory_documents",
        "memory_chunks",
    ):
        assert f"'{table_name}'" in required_block
