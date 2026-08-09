import inspect
import re
from pathlib import Path

from infinity_context_adapters.postgres.benchmark_run_repositories import (
    PostgresBenchmarkRunRepository,
    _registry_query,
)
from infinity_context_adapters.postgres.models import (
    Base,
    MemoryComparisonBenchmarkRunRow,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

RUN = "a" * 64


def test_cleanup_authorizes_registry_before_canonical_tombstones() -> None:
    source = inspect.getsource(PostgresBenchmarkRunRepository.begin_cleanup)
    ordered = (
        source.index("delete(MemoryOutboxRow)"),
        source.index("self._session.add_all"),
        source.index("await self._session.flush()", source.index("self._session.add_all")),
        source.index("receipt = BenchmarkCleanupReceipt"),
        source.index('row.state = "cleanup_pending"'),
        source.index("await self._session.flush()", source.index('row.state = "cleanup_pending"')),
        source.index("await self._soft_delete"),
    )
    assert ordered == tuple(sorted(ordered))


def test_managed_cleanup_proves_cognee_never_projected_before_pruning_upserts() -> None:
    source = inspect.getsource(PostgresBenchmarkRunRepository.begin_cleanup)
    assert source.index("_require_managed_cognee_never_projected") < source.index(
        "delete(MemoryOutboxRow)"
    )
    assert "cognee_jobs: list[MemoryOutboxRow] = []" in source
    assert 'event_type="cognee.forget_document"' not in source


def test_cleanup_query_uses_postgres_row_lock() -> None:
    sql = str(_registry_query(RUN, for_update=True).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql


def test_registry_model_enforces_current_state_coupling() -> None:
    ddl = str(
        CreateTable(MemoryComparisonBenchmarkRunRow.__table__).compile(dialect=postgresql.dialect())
    )
    for marker in (
        "state = 'active' AND cleanup_fingerprint_sha256 IS NULL",
        "state = 'cleanup_pending' AND cleanup_fingerprint_sha256 IS NOT NULL",
        "projection_cleanup_state = 'unsealed'",
        "projection_cleanup_state = 'sealed'",
        "projection_cleanup_state = 'blocked'",
        "projection_cleanup_state = 'pending'",
        "projection_manifest_json JSONB",
        "state = 'cleanup_complete'",
        "projection_cleanup_state = 'complete'",
        "finalization_fingerprint_sha256 VARCHAR(64)",
        "completion_receipt_json JSONB",
        "completed_at TIMESTAMP WITH TIME ZONE",
    ):
        assert marker in ddl
    assert "cleaned" not in ddl


def test_projection_manifest_migration_preserves_truthful_lifecycle() -> None:
    migration = Path(
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0018_benchmark_projection_manifest.sql"
    ).read_text()
    for marker in (
        "WHEN state = 'cleanup_pending' THEN 'blocked'",
        "projection_cleanup_state = 'sealed'",
        "projection_manifest_json JSONB",
        "projection_cleanup_state = 'pending'",
        "VALIDATE CONSTRAINT",
    ):
        assert marker in migration
    assert "verified_absent" not in migration


def test_completion_migration_triggers_only_direct_space_tables() -> None:
    migration = Path(
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0020_benchmark_cleanup_completion.sql"
    ).read_text()
    trigger_block = migration.split("FOREACH table_name IN ARRAY ARRAY[", 1)[1].split("]", 1)[0]
    triggered = set(re.findall(r"'(memory_[a-z_]+)'", trigger_block))
    assert triggered
    assert all(
        name in Base.metadata.tables and "space_id" in Base.metadata.tables[name].c
        for name in triggered
        if name != "memory_spaces"
    )
    assert "memory_asset_extraction_artifacts" not in triggered
