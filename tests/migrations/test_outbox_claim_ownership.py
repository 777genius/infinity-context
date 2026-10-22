from pathlib import Path

from infinity_context_adapters.postgres import migration_runner
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow


def test_outbox_claim_ownership_is_an_additive_forward_migration() -> None:
    migrations = migration_runner._load_migrations()
    assert [migration.migration_id for migration in migrations][-2:] == [
        "0060_memory_outbox_aggregate_id_width",
        "0061_outbox_claim_ownership",
    ]
    migration = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/"
        "migrations/0061_outbox_claim_ownership.sql"
    )
    assert migration.read_text() == (
        "SET LOCAL lock_timeout = '5s';\n"
        "SET LOCAL statement_timeout = '30s';\n\n"
        "ALTER TABLE public.memory_outbox\n"
        "  ADD COLUMN IF NOT EXISTS claim_token VARCHAR(32);\n"
    )
    column = MemoryOutboxRow.__table__.c.claim_token
    assert column.nullable and column.type.length == 32
