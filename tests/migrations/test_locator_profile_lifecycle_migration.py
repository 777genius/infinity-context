from hashlib import sha256
from pathlib import Path

from infinity_context_adapters.postgres.migration_runner import _load_migrations


def test_profile_lifecycle_is_forward_only_after_published_0039() -> None:
    migrations = _load_migrations()
    ids = tuple(migration.migration_id for migration in migrations)
    assert ids[-19:] == (
        "0039_locator_retrieval_attributes",
        "0040_locator_profile_lifecycle",
        "0041_locator_profile_attestation_fence",
        "0042_locator_profile_retirement",
        "0043_locator_profile_transition_audit",
        "0044_locator_profile_operator_receipts",
        "0045_locator_profile_incremental_attestation",
        "0046_locator_profile_linearizable_fences",
        "0047_locator_runtime_supervisor_proofs",
        "0048_locator_lifecycle_release_identity",
        "0049_reconciliation_runtime_generation",
        "0050_locator_profile_outbox_transaction_coalescing",
        "0051_locator_profile_acl_search_path_hardening",
        "0052_document_scope_listing_indexes",
        "0052_reconciliation_outbox_binding_index",
        "0053_retrieval_default_lifecycle",
        "0054_locator_profile_exact_delete_generation",
        "0055_generic_vector_rebuild_operations",
        "0056_fact_outbox_receipt_trigger_scope",
    )
    sql = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0040_locator_profile_lifecycle.sql"
    )
    forward = sql.read_text()
    assert "memory_locator_profiles" in forward
    assert "uq_locator_profile_one_building" in forward
    assert "uq_locator_profile_one_active" in forward
    assert "memory_locator_profile_projection_receipts" in forward
    assert "projected_watermark" in forward
    assert "memory_locator_profile_tombstones" in forward
    assert "vector.upsert_locator_profile" in forward
    assert "vector.delete_locator_profile" in forward
    assert "retrieval profile identity is immutable" in forward
    drop_lines = tuple(
        line.strip() for line in forward.splitlines() if line.lstrip().upper().startswith("DROP ")
    )
    assert drop_lines == (
        "DROP TRIGGER IF EXISTS trg_zz_memory_chunk_locator_watermark_bridge_v1 ON memory_chunks;",
        "DROP FUNCTION IF EXISTS memory_chunk_locator_watermark_mirror_v1();",
    )
    assert "ADD COLUMN retrieval_commit_watermark BIGINT NOT NULL" not in forward


def test_fact_receipt_trigger_ignores_non_fact_outbox_events() -> None:
    migration = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0056_fact_outbox_receipt_trigger_scope.sql"
    )
    sql = migration.read_text()

    assert "SET LOCAL lock_timeout = '5s'" in sql
    assert "DROP TRIGGER IF EXISTS trg_memory_outbox_benchmark_fact_receipt" in sql
    assert "CREATE CONSTRAINT TRIGGER trg_memory_outbox_benchmark_fact_receipt" in sql
    assert "WHEN (NEW.aggregate_type = 'fact')" in sql
    assert "memory_comparison_verify_benchmark_fact_outbox_receipt()" in sql


def test_profile_watermark_uses_bounded_online_backfill_and_short_cutover() -> None:
    helper = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/"
        "staged_locator_migrations.py"
    )
    staged = helper.read_text()
    assert "_BATCH_SIZE = 2000" in staged
    assert "FOR UPDATE SKIP LOCKED" in staged
    assert "pg_advisory_lock" not in staged  # the runner owns the session fence
    assert "LOCK TABLE public.memory_chunks IN ACCESS EXCLUSIVE MODE" in staged
    assert "SET LOCAL statement_timeout = '5s'" in staged
    assert "VALIDATE CONSTRAINT ck_memory_chunks_locator_watermark_present" in staged
    assert "trg_00_memory_chunks_benchmark_writer_lock" in staged
    assert "trg_memory_chunks_benchmark_writer_fence" in staged
    assert "trg_memory_chunks_benchmark_document_child_fence" in staged
    assert "NEW.retrieval_version IS DISTINCT FROM OLD.retrieval_version" in staged
    assert "CREATE TRIGGER trg_zz_memory_chunk_locator_watermark_bridge_v1" in staged
    forward = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath(
            "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations",
            "0040_locator_profile_lifecycle.sql",
        )
        .read_text()
    )
    final_trigger = "CREATE TRIGGER trg_zz_memory_chunk_locator_watermark_v2"
    bridge_trigger_drop = "DROP TRIGGER IF EXISTS trg_zz_memory_chunk_locator_watermark_bridge_v1"
    bridge_function_drop = "DROP FUNCTION IF EXISTS memory_chunk_locator_watermark_mirror_v1()"
    assert forward.index(final_trigger) < forward.index(bridge_trigger_drop)
    assert forward.index(bridge_trigger_drop) < forward.index(bridge_function_drop)
    seam_sql = forward[forward.index(final_trigger) : forward.index(bridge_function_drop)]
    transaction_boundaries = {"BEGIN;", "COMMIT;", "ROLLBACK;"}
    seam_statements = (line.strip().upper() for line in seam_sql.splitlines())
    assert transaction_boundaries.isdisjoint(seam_statements)


def test_attestation_fence_migration_is_additive_and_resumable() -> None:
    migrations = _load_migrations()
    migration = next(
        item for item in migrations if item.migration_id == "0041_locator_profile_attestation_fence"
    )
    assert migration.migration_id == "0041_locator_profile_attestation_fence"
    path = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0041_locator_profile_attestation_fence.sql"
    )
    sql = path.read_text()
    assert "activation_lease_expires_at" in sql
    assert "activation_evidence_digest" in sql
    assert "memory_locator_profile_attestation_checkpoints" in sql
    assert "digest_accumulator" in sql
    assert "DROP " not in sql.upper()


def test_profile_retirement_migration_is_additive_and_pinned() -> None:
    sql = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0042_locator_profile_retirement.sql"
    )
    cleanup = sql.read_text()
    assert "memory_locator_profile_cleanups" in cleanup
    assert "collection_deleted" in cleanup
    assert "postgres_cleaned" in cleanup
    assert "DROP " not in cleanup.upper()
    cleanup_checksum = sha256(sql.read_bytes()).hexdigest()
    assert cleanup_checksum == ("53c8b73263ed86a7d71ab62e828e98212e49f3fad30e3293c50bd3f4dc70d049")


def test_profile_transition_audit_is_append_only_and_lease_fenced() -> None:
    path = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0043_locator_profile_transition_audit.sql"
    )
    sql = path.read_text()
    assert "memory_locator_profile_transition_audit" in sql
    assert "lease_id VARCHAR(120) NOT NULL UNIQUE" in sql
    assert "evidence_digest" in sql
    assert "append-only" in sql
    assert "BEFORE UPDATE OR DELETE" in sql


def test_operator_receipts_and_incremental_manifests_are_forward_only() -> None:
    root = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
    )
    receipts = (root / "0044_locator_profile_operator_receipts.sql").read_text()
    manifests = (root / "0045_locator_profile_incremental_attestation.sql").read_text()
    assert "request_fingerprint" in receipts
    assert "result_json" in receipts
    assert "BEFORE UPDATE OR DELETE" in receipts
    assert "memory_locator_profile_attestation_pages" in manifests
    assert "memory_locator_profile_operator_rebuilds" in manifests
    assert "memory_locator_profile_operator_operations" in manifests
    assert "memory_locator_profile_provider_mutations" in manifests
    assert "memory_locator_profile_reconciliation_operations" in manifests
    assert "provider_mutation_epoch" in manifests
    assert "validation_page_number" in manifests
    assert "byte_count" in manifests
    assert "DROP " not in receipts.upper()
    assert "DROP " not in manifests.upper()


def test_linearizable_profile_fences_are_forward_only_and_non_stealable() -> None:
    path = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0046_locator_profile_linearizable_fences.sql"
    )
    sql = path.read_text()
    assert "delete_token" in sql
    assert "delete_epoch" in sql
    assert "memory_locator_profile_evidence_versions" in sql
    assert "memory_locator_profile_invalidate_evidence_v1" in sql
    assert "memory_locator_profile_queries" in sql
    assert "activation_lease_id" in sql
    assert "Diagnostic deadline only" in sql
    assert "never authorizes lease stealing" in sql
    assert "DELETE FROM memory_locator_profile_provider_mutations" not in sql
    assert "activation_evidence_version" in sql
    assert "activation_mutation_epoch" in sql
    assert "memory_locator_profile_maintenance_fence" in sql
    assert "memory_locator_profile_recovery_receipts" in sql
    assert "pre-0046-owner" in sql
    assert "Deploy only after every pre-0046 binary has drained" in sql


def test_linearizable_profile_outbox_invalidation_is_locator_event_scoped() -> None:
    path = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0046_locator_profile_linearizable_fences.sql"
    )
    sql = path.read_text()
    function = sql.split(
        "CREATE OR REPLACE FUNCTION memory_locator_profile_invalidate_evidence_v1()", 1
    )[1].split("REVOKE ALL ON FUNCTION", 1)[0]
    triggers = sql.split("DROP TRIGGER IF EXISTS trg_locator_profile_outbox_evidence_version", 1)[
        1
    ].split("DROP TRIGGER IF EXISTS trg_locator_profile_canonical", 1)[0]

    assert "IF TG_LEVEL = 'ROW' THEN" in function
    assert "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;" in function
    assert "RETURN NEW;" in function
    assert "CREATE TRIGGER trg_00_locator_profile_outbox_evidence_insert" in triggers
    assert "BEFORE INSERT ON memory_outbox" in triggers
    assert "WHEN (NEW.event_type IN (" in triggers
    assert "CREATE TRIGGER trg_00_locator_profile_outbox_evidence_update" in triggers
    assert "BEFORE UPDATE ON memory_outbox" in triggers
    assert ") OR NEW.event_type IN (" in triggers
    assert "CREATE TRIGGER trg_00_locator_profile_outbox_evidence_delete" in triggers
    assert "BEFORE DELETE ON memory_outbox" in triggers
    assert "WHEN (OLD.event_type IN (" in triggers
    assert triggers.count("'vector.upsert_locator_profile'") == 4
    assert triggers.count("'vector.delete_locator_profile'") == 4
    assert triggers.count("FOR EACH ROW") == 3
    assert "FOR EACH STATEMENT" not in triggers
    assert "strict-v4 fact/document row fences" in triggers
    assert (
        sql.count(
            "FOR EACH STATEMENT EXECUTE FUNCTION memory_locator_profile_invalidate_evidence_v1();"
        )
        == 4
    )
    for preserved_source in ("lane", "tombstone", "receipt", "canonical"):
        assert f"trg_locator_profile_{preserved_source}_evidence_version" in sql


def test_runtime_death_proofs_are_supervisor_bound_and_non_retroactive() -> None:
    path = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0047_locator_runtime_supervisor_proofs.sql"
    )
    sql = path.read_text()
    assert "supervisor_public_key" in sql
    assert "trust_root_sha256" in sql
    assert "trust_registry_generation" in sql
    assert "sealed_dead_proof_id" in sql
    assert "UNIQUE (sealed_dead_proof_id)" in sql
    assert "legacy-unrecoverable" in sql


def test_release_identity_migration_is_forward_only_and_transactionally_rollback_safe() -> None:
    path = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0048_locator_lifecycle_release_identity.sql"
    )
    sql = path.read_text()
    for field in (
        "release_revision",
        "release_source_tree_sha256",
        "release_installed_distribution_sha256",
        "release_runtime_modules_sha256",
        "release_identity_sha256",
        "lifecycle_identity_sha256",
    ):
        assert field in sql
    assert "forward-only drain boundary" in sql
    assert "Transactional migration failure rolls back" in sql
    assert "pre-0048 backup" in sql


def test_reconciliation_generation_migration_fences_current_owner_and_operation() -> None:
    path = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0049_reconciliation_runtime_generation.sql"
    )
    sql = path.read_text()
    assert "uq_locator_runtime_current_instance" in sql
    assert "WHERE sealed_dead_generation IS NULL AND retired_at IS NULL" in sql
    assert "runtime_instance_id" in sql
    assert "runtime_generation" in sql
    assert "lifecycle_identity_sha256" in sql
    assert "fk_locator_reconciliation_operation_runtime" in sql
    assert "reconciliation_drift" in sql


def test_populated_0049_operator_runbook_requires_read_only_preflight_and_no_winner() -> None:
    readme = (Path(__file__).resolve().parents[2] / "docs/README.md").read_text()
    assert "retrieval-profile-upgrade-preflight" in readme
    assert "blocked_competing_generations" in readme
    assert "never delete rows or choose" in readme


def test_retrieval_default_cutover_retires_only_the_historical_event_lane() -> None:
    path = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0053_retrieval_default_lifecycle.sql"
    )
    sql = path.read_text()
    assert "DROP TRIGGER IF EXISTS trg_memory_chunk_locator_projection_events_v2" in sql
    assert "DROP FUNCTION IF EXISTS memory_chunk_locator_projection_events_v2()" in sql
    assert "DROP TABLE IF EXISTS memory_locator_projection_tombstones" in sql
    assert "aggregate_type = 'locator_chunk'" in sql
    assert "status = 'running'" in sql
    assert "retrieval.legacy_projection_retired" in sql
    assert "trg_memory_chunk_locator_profile_events_v2" not in sql


def test_exact_delete_generation_migration_requires_observed_provider_evidence() -> None:
    path = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations/"
        "0054_locator_profile_exact_delete_generation.sql"
    )
    sql = path.read_text()
    assert "ADD COLUMN delete_canonical_version BIGINT" in sql
    assert "ADD COLUMN provider_observed_at TIMESTAMPTZ" in sql
    assert "ADD COLUMN delete_authorized_mutation_epoch BIGINT" in sql
    assert "ADD COLUMN delete_completed_mutation_epoch BIGINT" in sql
    assert "delete_canonical_version = NULL" in sql
    assert "provider_observed_at = NULL" in sql
    assert "delete_authorized_mutation_epoch = NULL" in sql
    assert "delete_completed_mutation_epoch = NULL" in sql
    assert "ck_locator_profile_tombstone_authorized_epoch" in sql
    assert "ck_locator_profile_tombstone_completed_epoch" in sql
    assert "CREATE TABLE public.memory_locator_profile_tombstone_replays" in sql
    assert "requested_epoch BIGINT NOT NULL" in sql
    assert "cursor_chunk_id VARCHAR(80)" in sql
    assert "locator-profile-delete-observe:" in sql
    assert "completed_at = NULL" in sql
    assert "canonical_version - 1" not in sql
    assert "memory_locator_profile_projection_receipts AS receipts" not in sql
    assert "CREATE OR REPLACE FUNCTION public.memory_chunk_locator_profile_events_v2()" in sql
