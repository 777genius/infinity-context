from hashlib import sha256
from pathlib import Path

from infinity_context_adapters.postgres.migration_runner import _load_migrations


def test_profile_lifecycle_is_forward_only_after_published_0039() -> None:
    migrations = _load_migrations()
    ids = tuple(migration.migration_id for migration in migrations)
    assert ids[-11:] == (
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
    assert "DROP " not in forward.upper()


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
