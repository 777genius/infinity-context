from datetime import UTC, datetime
from pathlib import Path

from infinity_context_adapters.postgres import migration_runner
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow
from sqlalchemy import create_engine

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
    / "0060_memory_outbox_aggregate_id_width.sql"
)


def test_0060_widens_only_the_outbox_aggregate_id() -> None:
    migrations = migration_runner._load_migrations()
    assert migrations[-2].migration_id == "0059_locator_parent_lifecycle"
    assert migrations[-1].migration_id == "0060_memory_outbox_aggregate_id_width"
    assert MIGRATION.read_text(encoding="utf-8") == (
        "SET LOCAL lock_timeout = '5s';\n"
        "SET LOCAL statement_timeout = '30s';\n"
        "\n"
        "ALTER TABLE public.memory_outbox\n"
        "  ALTER COLUMN aggregate_id TYPE VARCHAR(120);\n"
    )


def test_outbox_model_accepts_a_120_character_aggregate_id_on_sqlite() -> None:
    aggregate_id = "p" * 120
    assert MemoryOutboxRow.__table__.c.aggregate_id.type.length == 120

    engine = create_engine("sqlite://")
    MemoryOutboxRow.__table__.create(engine)
    now = datetime(2026, 9, 15, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            MemoryOutboxRow.__table__.insert(),
            {
                "event_type": "vector.upsert_locator_profile",
                "aggregate_type": "locator_profile",
                "aggregate_id": aggregate_id,
                "payload_json": {},
                "next_attempt_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        assert connection.scalar(
            MemoryOutboxRow.__table__.select().with_only_columns(
                MemoryOutboxRow.aggregate_id
            )
        ) == aggregate_id
