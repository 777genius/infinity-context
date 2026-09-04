from hashlib import sha256
from pathlib import Path

from infinity_context_adapters.postgres import migration_runner
from infinity_context_adapters.postgres.models import MemoryVectorRebuildOperationRow

MIGRATIONS = (
    Path(__file__).parents[2]
    / "packages"
    / "infinity_context_adapters"
    / "infinity_context_adapters"
    / "postgres"
    / "migrations"
)
MIGRATION = MIGRATIONS / "0055_generic_vector_rebuild_operations.sql"


def test_vector_rebuild_operation_migration_is_append_only_and_globally_unique() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE public.memory_vector_rebuild_operations" in sql
    assert "operation_id VARCHAR(80) PRIMARY KEY" in sql
    assert "canonical_watermark BIGINT NOT NULL" in sql
    assert "dead_event_watermark BIGINT NOT NULL" in sql
    assert "processed_count BIGINT NOT NULL" in sql
    assert "failed_count BIGINT NOT NULL" in sql
    assert "batch_size BETWEEN 1 AND 256" in sql
    assert "ALTER TABLE memory_chunks" not in sql
    assert len(sql.splitlines()) < 1_000


def test_vector_rebuild_operation_model_uses_operation_id_as_the_database_key() -> None:
    table = MemoryVectorRebuildOperationRow.__table__
    assert tuple(column.name for column in table.primary_key.columns) == ("operation_id",)
    assert {"space_id", "memory_scope_id"}.issubset(table.columns.keys())


def test_vector_rebuild_migration_loads_after_published_retrieval_lifecycle() -> None:
    migrations = migration_runner._load_migrations()
    ids = tuple(item.migration_id for item in migrations)
    assert ids.index("0055_generic_vector_rebuild_operations") > ids.index(
        "0053_retrieval_default_lifecycle"
    )
    loaded = next(
        item for item in migrations if item.migration_id == "0055_generic_vector_rebuild_operations"
    )
    assert loaded.checksum == sha256(MIGRATION.read_bytes()).hexdigest()
