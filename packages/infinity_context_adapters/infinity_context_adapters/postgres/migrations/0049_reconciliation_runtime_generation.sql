-- Deterministic runtime generations and truthful reconciliation transition evidence.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5min';

ALTER TABLE memory_locator_runtime_incarnations
    ADD COLUMN retired_at TIMESTAMPTZ;

-- A stable instance has exactly zero or one current generation. A replacement is
-- legal only after explicit self-retirement or an authoritative dead-owner seal.
CREATE UNIQUE INDEX uq_locator_runtime_current_instance
    ON memory_locator_runtime_incarnations(instance_id)
    WHERE sealed_dead_generation IS NULL AND retired_at IS NULL;

-- Operations created before this upgrade remain readable for retention, but cannot
-- authorize a reconciliation mutation because their owner provenance is unknown.
ALTER TABLE memory_locator_profile_reconciliation_operations
    ADD COLUMN runtime_instance_id VARCHAR(120),
    ADD COLUMN runtime_generation VARCHAR(120),
    ADD COLUMN lifecycle_identity_sha256 VARCHAR(64),
    ADD CONSTRAINT ck_locator_reconciliation_operation_owner CHECK (
        (runtime_instance_id IS NULL AND runtime_generation IS NULL
         AND lifecycle_identity_sha256 IS NULL)
        OR
        (runtime_instance_id IS NOT NULL AND runtime_generation IS NOT NULL
         AND lifecycle_identity_sha256 ~ '^[0-9a-f]{64}$')
    ),
    ADD CONSTRAINT fk_locator_reconciliation_operation_runtime FOREIGN KEY (
        runtime_instance_id, runtime_generation
    ) REFERENCES memory_locator_runtime_incarnations(instance_id, generation);

CREATE OR REPLACE FUNCTION memory_locator_runtime_dead_seal_v3()
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
       OR (OLD.retired_at IS NOT NULL AND NEW.retired_at IS DISTINCT FROM OLD.retired_at)
       OR (OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL
           AND NEW.sealed_dead_generation IS NOT NULL)
       OR (OLD.sealed_dead_generation IS NOT NULL AND (
           NEW.sealed_dead_generation IS DISTINCT FROM OLD.sealed_dead_generation
           OR NEW.sealed_dead_proof_id IS DISTINCT FROM OLD.sealed_dead_proof_id
           OR NEW.sealed_dead_proof_sha256 IS DISTINCT FROM OLD.sealed_dead_proof_sha256
           OR NEW.sealed_dead_authority IS DISTINCT FROM OLD.sealed_dead_authority
           OR NEW.sealed_dead_at IS DISTINCT FROM OLD.sealed_dead_at))
    THEN
        RAISE EXCEPTION 'retrieval runtime lifecycle identities are immutable';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION memory_locator_runtime_dead_seal_v3() FROM PUBLIC;
DROP TRIGGER trg_locator_runtime_dead_seal ON memory_locator_runtime_incarnations;
CREATE TRIGGER trg_locator_runtime_dead_seal
BEFORE UPDATE OR DELETE ON memory_locator_runtime_incarnations
FOR EACH ROW EXECUTE FUNCTION memory_locator_runtime_dead_seal_v3();

ALTER TABLE memory_locator_profile_transition_audit
    ADD COLUMN operation VARCHAR(32) NOT NULL DEFAULT 'activation',
    ADD COLUMN lease_issued_at TIMESTAMPTZ,
    ADD COLUMN lease_expires_at TIMESTAMPTZ,
    ADD COLUMN requested_expires_at TIMESTAMPTZ,
    ADD COLUMN mutation_epoch BIGINT,
    ADD COLUMN reconciliation_drifted BOOLEAN;

ALTER TABLE memory_locator_profile_transition_audit
    ALTER COLUMN operation DROP DEFAULT,
    ADD CONSTRAINT ck_locator_transition_operation CHECK (
        operation IN ('activation', 'reconciliation', 'reconciliation_drift')
    ),
    ADD CONSTRAINT ck_locator_transition_mutation_epoch CHECK (
        mutation_epoch IS NULL OR mutation_epoch >= 0
    );
