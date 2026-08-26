from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from infinity_context_adapters.postgres.locator_models import (
    MemoryChunkRow,
    MemoryLocatorProjectionTombstoneRow,
)
from infinity_context_adapters.postgres.migration_runner import (
    _load_migrations,
    _validate_history,
)
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow
from infinity_context_adapters.postgres.projection_receipt_models import (
    MemoryProjectionResultReceiptRow,
)
from sqlalchemy import BigInteger, create_engine, select


def test_locator_migration_preserves_legacy_ineligibility_and_fences_projection() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
        / "0039_locator_retrieval_attributes.sql"
    )
    sql = path.read_text()
    assert "ADD COLUMN IF NOT EXISTS retrieval_locator" in sql
    assert "UPDATE memory_chunks" not in sql
    assert "sha256(convert_to(" not in sql
    assert "retrieval_sequence_ordinal" in sql
    assert "retrieval_relative_start_ms" in sql
    assert "retrieval_version BIGINT" in sql
    assert "canonical_version BIGINT" in sql
    assert "ALTER COLUMN aggregate_version TYPE BIGINT" not in sql
    assert "converted online by the staged migration runner" in sql
    assert "CREATE INDEX" not in sql
    assert "DROP INDEX" not in sql
    assert "NOT VALID" in sql
    assert "memory_document_projection_receipts" in sql
    assert "memory_chunk_retrieval_fence_v2" in sql
    assert "OLD.retrieval_version + 1" in sql
    assert "memory_locator_projection_tombstones" in sql
    assert "locator-v2-tombstone:" in sql
    assert "locator-v2-reproject:" in sql
    assert "ON CONFLICT (message_key)" in sql
    assert "NEW.retrieval_version > OLD.retrieval_version" in sql
    assert "canonical_version < EXCLUDED.canonical_version" in sql
    assert "RENAME" not in sql.upper()


def test_published_migration_bytes_match_head_checksums() -> None:
    migrations = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
    )
    expected = {
        "0001_core_facts.sql": "30fda365c4743f3388415ccb2721ec5c11605af3448efc8d7d09c726b19fe919",
        "0035_projection_result_receipts.sql": (
            "a83c0c0ae930b8e677621c855426212b44621c07644ad8c86437f5346e0c40ee"
        ),
        "0050_locator_profile_outbox_transaction_coalescing.sql": (
            "9be1200b51bccbe50f68e935c4c227f8e8a0aefd77f0c46561d352295e5b844f"
        ),
        "0052_reconciliation_outbox_binding_index.sql": (
            "c365eefef764e074249f2fc09444db3c4d26e01aa7c42e1e6b6abfa6d951acc2"
        ),
    }
    for name, checksum in expected.items():
        assert sha256((migrations / name).read_bytes()).hexdigest() == checksum


def test_published_ledger_prefix_continues_through_forward_locator_migration() -> None:
    migrations = _load_migrations()
    history = {
        migration.migration_id: migration.checksum
        for migration in migrations
        if migration.migration_id <= "0038_strict_v4_document_writer"
    }

    _validate_history(migrations, history)

    assert migrations[-1].migration_id == ("0052_reconciliation_outbox_binding_index")


def test_published_locator_checksums_remain_upgrade_compatible() -> None:
    migrations = _load_migrations()
    history = {
        migration.migration_id: migration.checksum
        for migration in migrations
        if migration.migration_id <= "0046_locator_profile_linearizable_fences"
    }
    history["0039_locator_retrieval_attributes"] = (
        "83f22c9e4087e6f4713294665a00ce99f7ffc981893702a2fbb3a575813c418d"
    )
    history["0040_locator_profile_lifecycle"] = (
        "2b972527e5a2f6e99f5bd69b6eca9c22a51b8cb4902b1d4e13f7e0260138edaa"
    )
    history["0046_locator_profile_linearizable_fences"] = (
        "a069a1c2707366c364206e70740b37b9f5720597a133b2d63eab1e324f85313e"
    )

    _validate_history(migrations, history)


def test_locator_indexes_are_a_separately_fenced_concurrent_phase() -> None:
    path = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/maintenance/"
        "locator_retrieval_v2_concurrent_indexes.sql"
    )
    sql = path.read_text()
    assert sql.count("CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS") == 2
    assert sql.count("CREATE INDEX CONCURRENTLY IF NOT EXISTS") == 2
    assert "DROP INDEX" not in sql


def test_projected_ingestion_and_capability_use_exact_catalog_attestation() -> None:
    root = Path(__file__).resolve().parents[2]
    ingestion = root.joinpath(
        "packages/infinity_context_adapters/infinity_context_adapters/postgres",
        "projected_document_ingestion.py",
    ).read_text()
    composition = root.joinpath(
        "packages/infinity_context_server/infinity_context_server/features",
        "../retrieval_composition.py",
    ).read_text()
    maintenance = root.joinpath(
        "packages/infinity_context_adapters/infinity_context_adapters/postgres",
        "locator_index_maintenance.py",
    ).read_text()
    assert "lock_and_attest_locator_retrieval_v2_catalog(session)" in ingestion
    assert "attest_locator_retrieval_v2_catalog(session)" in composition
    assert "_drop_mismatched_indexes" in maintenance


def test_locator_canonical_versions_use_bigint_in_sqlalchemy_models() -> None:
    assert isinstance(MemoryChunkRow.__table__.c.retrieval_version.type, BigInteger)
    assert isinstance(
        MemoryLocatorProjectionTombstoneRow.__table__.c.canonical_version.type, BigInteger
    )


def test_every_version_bearing_transit_column_uses_bigint() -> None:
    migrations = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
    )
    forward = (migrations / "0039_locator_retrieval_attributes.sql").read_text()
    assert "ALTER COLUMN aggregate_version TYPE BIGINT" not in forward
    staged = (migrations.parent / "staged_locator_migrations.py").read_text()
    assert "aggregate_version_bigint" in staged
    assert "LIMIT {_BATCH_SIZE} FOR UPDATE SKIP LOCKED" in staged
    assert "_BATCH_SIZE = 2000" in staged
    assert "UPDATE OF " in staged
    assert "trg_memory_outbox_benchmark_document_child_fence" in staged
    assert "Keep canonical guards active while excluding migration-only updates" in staged
    assert "CREATE UNIQUE INDEX CONCURRENTLY" in staged
    assert "UNIQUE USING INDEX" in staged
    assert "aggregate_version INTEGER" in (migrations / "0001_core_facts.sql").read_text()
    assert (
        "aggregate_version INTEGER"
        in (migrations / "0035_projection_result_receipts.sql").read_text()
    )
    assert isinstance(MemoryOutboxRow.__table__.c.aggregate_version.type, BigInteger)
    assert isinstance(
        MemoryProjectionResultReceiptRow.__table__.c.aggregate_version.type, BigInteger
    )


def test_safe_integer_max_round_trips_through_outbox_orm() -> None:
    maximum = 9_007_199_254_740_991
    now = datetime(2026, 1, 1, tzinfo=UTC)
    engine = create_engine("sqlite://")
    MemoryOutboxRow.__table__.create(engine)
    with engine.begin() as connection:
        result = connection.execute(
            MemoryOutboxRow.__table__.insert().values(
                event_type="vector.upsert_chunk",
                aggregate_type="locator_chunk",
                aggregate_id="chunk-max-version",
                aggregate_version=maximum,
                workload_class="projection",
                payload_json={"chunk_id": "chunk-max-version"},
                status="pending",
                attempt_count=0,
                next_attempt_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        observed = connection.execute(
            select(MemoryOutboxRow.__table__.c.aggregate_version).where(
                MemoryOutboxRow.__table__.c.id == result.inserted_primary_key[0]
            )
        ).scalar_one()
    assert observed == maximum


def test_sqlalchemy_locator_bounds_match_migration_constraints() -> None:
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in MemoryChunkRow.__table__.constraints
        if getattr(constraint, "sqltext", None) is not None
    }
    assert "BETWEEN 0 AND 2147483647" in constraints["ck_memory_chunks_retrieval_ordinal_range"]
    relative = constraints["ck_memory_chunks_retrieval_relative_time_range"]
    assert "BETWEEN 0 AND 9007199254740991" in relative
    assert "BETWEEN retrieval_relative_start_ms AND 9007199254740991" in relative
