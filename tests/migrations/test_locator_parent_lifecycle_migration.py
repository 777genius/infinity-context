from pathlib import Path

import pytest
from infinity_context_adapters.postgres import migration_runner

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
    / "0059_locator_parent_lifecycle.sql"
)


def test_parent_lifecycle_repair_is_the_next_forward_only_migration() -> None:
    migrations = migration_runner._load_migrations()
    assert migrations[-1].migration_id == "0059_locator_parent_lifecycle"
    assert sum(item.migration_id == "0059_locator_parent_lifecycle" for item in migrations) == 1


def test_pre_0059_binary_rejects_the_forward_only_history_row() -> None:
    migrations = migration_runner._load_migrations()
    old_binary_migrations = migrations[:-1]
    history = {item.migration_id: item.checksum for item in migrations}

    with pytest.raises(RuntimeError, match="Unknown applied PostgreSQL migration: 0059"):
        migration_runner._validate_history(old_binary_migrations, history)


def test_parent_lifecycle_migration_versions_children_and_fails_closed() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS retrieval_parent_version BIGINT NOT NULL DEFAULT 1" in sql
    assert "OLD.retrieval_parent_version" in sql
    assert "NEW.retrieval_parent_version" in sql
    assert "document.status = 'active'" in sql
    assert "document.retrieval_projected = TRUE" in sql
    for binding in (
        "parent.space_id IS DISTINCT FROM NEW.space_id",
        "parent.memory_scope_id IS DISTINCT FROM NEW.memory_scope_id",
        "parent.thread_id IS DISTINCT FROM NEW.thread_id",
        "parent.source_type IS DISTINCT FROM NEW.source_type",
        "parent.source_external_id IS DISTINCT FROM NEW.source_external_id",
        "parent.classification IS DISTINCT FROM NEW.classification",
    ):
        assert binding in sql
    assert "pg_catalog.hashtextextended('locator-parent:' || NEW.document_id, 0)" in sql
    assert "memory_document_lock_locator_parent_v1" in sql
    assert "'locator-parent:' || document_key" in sql
    assert "FOR NO KEY UPDATE OF document" in sql
    assert "ERRCODE = '23503'" in sql
    assert "OLD.id IS DISTINCT FROM NEW.id" in sql
    assert "canonical document identity is immutable" in sql
    assert "AFTER INSERT ON public.memory_documents" in sql
    assert "BEFORE UPDATE ON public.memory_documents" in sql
    assert "BEFORE DELETE ON public.memory_documents" in sql
    assert "trg_01_document_locator_parent_lock_update" in sql
    assert sql.count("AFTER UPDATE ON public.memory_documents") == 1
    assert sql.count("AFTER DELETE ON public.memory_documents") == 1
    assert "SET retrieval_parent_version = retrieval_parent_version + 1" in sql
    assert "vector.delete_locator_profile" in sql
    assert "memory_locator_projection_tombstones" not in sql
    assert "memory_chunk_locator_projection_events_v2" not in sql
    assert "vector.delete_chunks" not in sql


def test_parent_lifecycle_migration_preserves_online_and_security_guards() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "SET LOCAL lock_timeout = '1s'" in sql
    assert "SET LOCAL statement_timeout = '30s'" in sql
    assert "sealed_dead_generation IS NULL" in sql
    assert "locator_parent_capability <> 1" in sql
    assert "unknown migration-history row" in sql
    assert "locator_parent_capability BIGINT NOT NULL DEFAULT 0" in sql
    assert "infinity_context.locator_parent_capability" in sql
    assert "runtime binary lacks locator parent lifecycle capability 0059" in sql
    assert "SECURITY INVOKER" in sql
    assert "SECURITY DEFINER" in sql
    assert "SET search_path = pg_catalog, public, pg_temp" in sql
    assert "REVOKE ALL ON FUNCTION" in sql
    assert "CROSS JOIN" not in sql
    assert len(sql.splitlines()) < 1_000


def test_parent_maintenance_bypasses_only_the_new_version_column() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    trigger_start = sql.index(
        "CREATE TRIGGER trg_00_memory_chunks_benchmark_document_child_lock"
    )
    trigger_end = sql.index(
        "DROP TRIGGER IF EXISTS trg_memory_chunks_benchmark_document_child_fence",
        trigger_start,
    )
    lock_trigger = sql[trigger_start:trigger_end]
    policy_start = sql.index(
        "CREATE TRIGGER trg_memory_chunks_benchmark_document_child_fence"
    )
    policy_end = sql.index("-- The advisory identity also exists", policy_start)
    policy_trigger = sql[policy_start:policy_end]

    for trigger in (lock_trigger, policy_trigger):
        assert "BEFORE INSERT OR DELETE OR UPDATE OF" in trigger
        assert "retrieval_parent_version" not in trigger
        for fenced_column in (
            "id",
            "space_id",
            "document_id",
            "source_external_id",
            "text",
            "status",
            "classification",
            "retrieval_locator",
            "retrieval_commit_watermark",
        ):
            assert fenced_column in trigger
    assert "session_replication_role" not in sql
    assert "DISABLE TRIGGER" not in sql


def test_parent_repair_is_bounded_resumable_and_profile_only() -> None:
    staged = (MIGRATION.parent.parent / "staged_locator_migrations.py").read_text(encoding="utf-8")

    assert '"0059_locator_parent_lifecycle"' in staged
    assert "retrieval_parent_version = 1" in staged
    assert 'cursor = ""' in staged
    assert "chunk.id > :cursor" in staged
    assert "WITH batch AS MATERIALIZED" in staged
    assert "Start the physical transaction" in staged
    assert "ORDER BY chunk.id" in staged
    assert "LIMIT {_BATCH_SIZE}" in staged
    assert "FOR UPDATE OF chunk" in staged
    assert "SET LOCAL lock_timeout = '1s'" in staged
    assert "SET LOCAL statement_timeout = '30s'" in staged
    assert "VALIDATE CONSTRAINT" in staged
    assert "memory_locator_projection_tombstones" not in staged
    assert "vector.delete_chunks" not in staged
