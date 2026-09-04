"""Static contract for the canonical active reconciliation binding index."""

from pathlib import Path

from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow

MIGRATION = (
    Path(__file__)
    .resolve()
    .parents[2]
    .joinpath(
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations",
        "0052_reconciliation_outbox_binding_index.sql",
    )
)
INDEX_NAME = "ix_memory_outbox_active_reconciliation_binding"


def test_0052_adds_the_exact_partial_active_binding_index() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert f"CREATE INDEX IF NOT EXISTS {INDEX_NAME}" in sql
    assert "(aggregate_id, event_type, aggregate_type, aggregate_version)" in sql
    assert "WHERE status IN ('pending', 'running', 'retry_pending')" in sql
    assert "DROP " not in sql.upper()


def test_orm_inventory_matches_the_published_index_identity() -> None:
    indexes = {index.name: index for index in MemoryOutboxRow.__table__.indexes}
    index = indexes[INDEX_NAME]
    assert tuple(column.name for column in index.columns) == (
        "aggregate_id",
        "event_type",
        "aggregate_type",
        "aggregate_version",
    )
    assert str(index.dialect_options["postgresql"]["where"]) == (
        "status IN ('pending', 'running', 'retry_pending')"
    )
