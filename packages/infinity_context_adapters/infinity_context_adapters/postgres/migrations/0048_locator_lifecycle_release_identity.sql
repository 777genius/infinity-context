-- One release-bound proof identity for runtime, provider, recovery and operator evidence.
-- This remains a forward-only drain boundary. Transactional migration failure rolls back
-- all DDL; operational rollback restores a pre-0048 backup with the pre-0048 binary.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5min';

ALTER TABLE memory_locator_runtime_incarnations
    ADD COLUMN release_revision VARCHAR(40),
    ADD COLUMN release_source_tree_sha256 VARCHAR(71),
    ADD COLUMN release_installed_distribution_sha256 VARCHAR(71),
    ADD COLUMN release_runtime_modules_sha256 VARCHAR(71),
    ADD COLUMN release_identity_sha256 VARCHAR(64);

-- Older incarnations are deliberately unrecoverable: a release identity cannot be
-- invented retroactively. Existing lifecycle rows remain auditable but cannot authorize
-- a new provider recovery after this drain-boundary upgrade.
UPDATE memory_locator_runtime_incarnations
SET release_revision = repeat('0', 40),
    release_source_tree_sha256 = 'sha256:' || repeat('0', 64),
    release_installed_distribution_sha256 = 'sha256:' || repeat('0', 64),
    release_runtime_modules_sha256 = 'sha256:' || repeat('0', 64),
    release_identity_sha256 = repeat('0', 64)
WHERE release_revision IS NULL;

ALTER TABLE memory_locator_runtime_incarnations
    ALTER COLUMN release_revision SET NOT NULL,
    ALTER COLUMN release_source_tree_sha256 SET NOT NULL,
    ALTER COLUMN release_installed_distribution_sha256 SET NOT NULL,
    ALTER COLUMN release_runtime_modules_sha256 SET NOT NULL,
    ALTER COLUMN release_identity_sha256 SET NOT NULL,
    ADD CONSTRAINT ck_locator_runtime_release_identity CHECK (
        release_revision ~ '^[0-9a-f]{40}$'
        AND release_source_tree_sha256 ~ '^sha256:[0-9a-f]{64}$'
        AND release_installed_distribution_sha256 ~ '^sha256:[0-9a-f]{64}$'
        AND release_runtime_modules_sha256 ~ '^sha256:[0-9a-f]{64}$'
        AND release_identity_sha256 ~ '^[0-9a-f]{64}$'
    );

CREATE OR REPLACE FUNCTION memory_locator_runtime_dead_seal_v2()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.instance_id IS DISTINCT FROM OLD.instance_id
       OR NEW.generation IS DISTINCT FROM OLD.generation
       OR NEW.registered_at IS DISTINCT FROM OLD.registered_at
       OR NEW.supervisor_key_id IS DISTINCT FROM OLD.supervisor_key_id
       OR NEW.supervisor_public_key IS DISTINCT FROM OLD.supervisor_public_key
       OR NEW.trust_root_sha256 IS DISTINCT FROM OLD.trust_root_sha256
       OR NEW.trust_registry_generation IS DISTINCT FROM OLD.trust_registry_generation
       OR NEW.launch_token IS DISTINCT FROM OLD.launch_token
       OR NEW.process_pid IS DISTINCT FROM OLD.process_pid
       OR NEW.process_birth_identity IS DISTINCT FROM OLD.process_birth_identity
       OR NEW.executable_identity IS DISTINCT FROM OLD.executable_identity
       OR NEW.executable_sha256 IS DISTINCT FROM OLD.executable_sha256
       OR NEW.release_revision IS DISTINCT FROM OLD.release_revision
       OR NEW.release_source_tree_sha256 IS DISTINCT FROM OLD.release_source_tree_sha256
       OR NEW.release_installed_distribution_sha256 IS DISTINCT FROM
          OLD.release_installed_distribution_sha256
       OR NEW.release_runtime_modules_sha256 IS DISTINCT FROM OLD.release_runtime_modules_sha256
       OR NEW.release_identity_sha256 IS DISTINCT FROM OLD.release_identity_sha256
       OR NEW.launch_identity_sha256 IS DISTINCT FROM OLD.launch_identity_sha256
       OR (OLD.sealed_dead_generation IS NOT NULL AND (
           NEW.sealed_dead_generation IS DISTINCT FROM OLD.sealed_dead_generation
           OR NEW.sealed_dead_proof_id IS DISTINCT FROM OLD.sealed_dead_proof_id
           OR NEW.sealed_dead_proof_sha256 IS DISTINCT FROM OLD.sealed_dead_proof_sha256
           OR NEW.sealed_dead_authority IS DISTINCT FROM OLD.sealed_dead_authority
           OR NEW.sealed_dead_at IS DISTINCT FROM OLD.sealed_dead_at))
    THEN
        RAISE EXCEPTION 'retrieval runtime release, launch identities and dead seals are immutable';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION memory_locator_runtime_dead_seal_v2() FROM PUBLIC;
DROP TRIGGER trg_locator_runtime_dead_seal
    ON memory_locator_runtime_incarnations;
CREATE TRIGGER trg_locator_runtime_dead_seal
BEFORE UPDATE OR DELETE ON memory_locator_runtime_incarnations
FOR EACH ROW EXECUTE FUNCTION memory_locator_runtime_dead_seal_v2();

ALTER TABLE memory_locator_provider_reconciliation_receipts
    ADD COLUMN launch_identity_sha256 VARCHAR(64),
    ADD COLUMN release_identity_sha256 VARCHAR(64),
    ADD COLUMN lifecycle_identity_sha256 VARCHAR(64);
UPDATE memory_locator_provider_reconciliation_receipts
SET launch_identity_sha256 = repeat('0', 64),
    release_identity_sha256 = repeat('0', 64),
    lifecycle_identity_sha256 = repeat('0', 64)
WHERE launch_identity_sha256 IS NULL;
ALTER TABLE memory_locator_provider_reconciliation_receipts
    ALTER COLUMN launch_identity_sha256 SET NOT NULL,
    ALTER COLUMN release_identity_sha256 SET NOT NULL,
    ALTER COLUMN lifecycle_identity_sha256 SET NOT NULL,
    ADD CONSTRAINT ck_locator_provider_receipt_lifecycle_identity CHECK (
        launch_identity_sha256 ~ '^[0-9a-f]{64}$'
        AND release_identity_sha256 ~ '^[0-9a-f]{64}$'
        AND lifecycle_identity_sha256 ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT fk_locator_provider_receipt_runtime FOREIGN KEY (
        owner_instance_id, owner_generation
    ) REFERENCES memory_locator_runtime_incarnations(instance_id, generation);

ALTER TABLE memory_locator_profile_recovery_receipts
    ADD COLUMN launch_identity_sha256 VARCHAR(64),
    ADD COLUMN sealed_dead_proof_id VARCHAR(120),
    ADD COLUMN sealed_dead_proof_sha256 VARCHAR(64),
    ADD COLUMN release_identity_sha256 VARCHAR(64),
    ADD COLUMN lifecycle_identity_sha256 VARCHAR(64);
UPDATE memory_locator_profile_recovery_receipts
SET launch_identity_sha256 = repeat('0', 64),
    sealed_dead_proof_id = 'legacy-unrecoverable-' || md5(idempotency_key),
    sealed_dead_proof_sha256 = repeat('0', 64),
    release_identity_sha256 = repeat('0', 64),
    lifecycle_identity_sha256 = repeat('0', 64)
WHERE launch_identity_sha256 IS NULL;
ALTER TABLE memory_locator_profile_recovery_receipts
    ALTER COLUMN launch_identity_sha256 SET NOT NULL,
    ALTER COLUMN sealed_dead_proof_id SET NOT NULL,
    ALTER COLUMN sealed_dead_proof_sha256 SET NOT NULL,
    ALTER COLUMN release_identity_sha256 SET NOT NULL,
    ALTER COLUMN lifecycle_identity_sha256 SET NOT NULL,
    ADD CONSTRAINT ck_locator_recovery_lifecycle_identity CHECK (
        launch_identity_sha256 ~ '^[0-9a-f]{64}$'
        AND sealed_dead_proof_id <> ''
        AND sealed_dead_proof_sha256 ~ '^[0-9a-f]{64}$'
        AND release_identity_sha256 ~ '^[0-9a-f]{64}$'
        AND lifecycle_identity_sha256 ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT fk_locator_recovery_runtime FOREIGN KEY (
        owner_instance_id, owner_generation
    ) REFERENCES memory_locator_runtime_incarnations(instance_id, generation);

ALTER TABLE memory_locator_profile_operator_receipts
    ADD COLUMN runtime_instance_id VARCHAR(120),
    ADD COLUMN runtime_generation VARCHAR(120),
    ADD COLUMN launch_identity_sha256 VARCHAR(64),
    ADD COLUMN release_identity_sha256 VARCHAR(64),
    ADD COLUMN lifecycle_identity_sha256 VARCHAR(64),
    ADD CONSTRAINT ck_locator_operator_lifecycle_identity CHECK (
        (runtime_instance_id IS NULL AND runtime_generation IS NULL
            AND launch_identity_sha256 IS NULL AND release_identity_sha256 IS NULL
            AND lifecycle_identity_sha256 IS NULL)
        OR (runtime_instance_id IS NOT NULL AND runtime_generation IS NOT NULL
            AND launch_identity_sha256 ~ '^[0-9a-f]{64}$'
            AND release_identity_sha256 ~ '^[0-9a-f]{64}$'
            AND lifecycle_identity_sha256 ~ '^[0-9a-f]{64}$')
    );

ALTER TABLE memory_locator_profile_transition_audit
    ADD COLUMN runtime_instance_id VARCHAR(120),
    ADD COLUMN runtime_generation VARCHAR(120),
    ADD COLUMN lifecycle_identity_sha256 VARCHAR(64),
    ADD CONSTRAINT ck_locator_transition_lifecycle_identity CHECK (
        (runtime_instance_id IS NULL AND runtime_generation IS NULL
            AND lifecycle_identity_sha256 IS NULL)
        OR (runtime_instance_id IS NOT NULL AND runtime_generation IS NOT NULL
            AND lifecycle_identity_sha256 ~ '^[0-9a-f]{64}$')
    ),
    ADD CONSTRAINT fk_locator_transition_runtime FOREIGN KEY (
        runtime_instance_id, runtime_generation
    ) REFERENCES memory_locator_runtime_incarnations(instance_id, generation);

-- Extend append-only provider evidence to the release/lifecycle identity columns.
CREATE OR REPLACE FUNCTION memory_locator_provider_receipt_immutable_v3()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'retrieval provider observation receipts are immutable';
    END IF;
    IF OLD.consumed_by_recovery_key IS NOT NULL
       OR NEW.receipt_id IS DISTINCT FROM OLD.receipt_id
       OR NEW.profile_id IS DISTINCT FROM OLD.profile_id
       OR NEW.profile_generation IS DISTINCT FROM OLD.profile_generation
       OR NEW.collection_name IS DISTINCT FROM OLD.collection_name
       OR NEW.maintenance_generation IS DISTINCT FROM OLD.maintenance_generation
       OR NEW.evidence_epoch IS DISTINCT FROM OLD.evidence_epoch
       OR NEW.operation_id IS DISTINCT FROM OLD.operation_id
       OR NEW.owner_instance_id IS DISTINCT FROM OLD.owner_instance_id
       OR NEW.owner_generation IS DISTINCT FROM OLD.owner_generation
       OR NEW.mutation_epoch IS DISTINCT FROM OLD.mutation_epoch
       OR NEW.stale_deadline IS DISTINCT FROM OLD.stale_deadline
       OR NEW.observed_count IS DISTINCT FROM OLD.observed_count
       OR NEW.observed_digest IS DISTINCT FROM OLD.observed_digest
       OR NEW.provider_state IS DISTINCT FROM OLD.provider_state
       OR NEW.receipt_sha256 IS DISTINCT FROM OLD.receipt_sha256
       OR NEW.launch_identity_sha256 IS DISTINCT FROM OLD.launch_identity_sha256
       OR NEW.release_identity_sha256 IS DISTINCT FROM OLD.release_identity_sha256
       OR NEW.lifecycle_identity_sha256 IS DISTINCT FROM OLD.lifecycle_identity_sha256
       OR NEW.observed_at IS DISTINCT FROM OLD.observed_at
       OR (NEW.consumed_by_recovery_key IS NULL) <> (NEW.consumed_at IS NULL)
    THEN
        RAISE EXCEPTION 'retrieval provider observation receipts are immutable';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION memory_locator_provider_receipt_immutable_v3() FROM PUBLIC;
DROP TRIGGER trg_locator_provider_reconciliation_receipt_append_only
    ON memory_locator_provider_reconciliation_receipts;
CREATE TRIGGER trg_locator_provider_reconciliation_receipt_append_only
BEFORE UPDATE OR DELETE ON memory_locator_provider_reconciliation_receipts
FOR EACH ROW EXECUTE FUNCTION memory_locator_provider_receipt_immutable_v3();
