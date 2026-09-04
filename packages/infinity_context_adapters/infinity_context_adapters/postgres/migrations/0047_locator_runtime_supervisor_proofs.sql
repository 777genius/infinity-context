-- Bind every runtime incarnation to its original supervisor verification key.
-- 0046 is unreleased; populated upgrade fixtures are assigned an explicitly
-- unrecoverable key so an operator cannot retroactively mint death authority.

ALTER TABLE memory_locator_runtime_incarnations
    ADD COLUMN IF NOT EXISTS supervisor_key_id VARCHAR(120),
    ADD COLUMN IF NOT EXISTS supervisor_public_key VARCHAR(64),
    ADD COLUMN IF NOT EXISTS trust_root_sha256 VARCHAR(64),
    ADD COLUMN IF NOT EXISTS trust_registry_generation BIGINT,
    ADD COLUMN IF NOT EXISTS sealed_dead_proof_id VARCHAR(120),
    ADD COLUMN IF NOT EXISTS launch_token VARCHAR(120),
    ADD COLUMN IF NOT EXISTS process_pid BIGINT,
    ADD COLUMN IF NOT EXISTS process_birth_identity VARCHAR(120),
    ADD COLUMN IF NOT EXISTS executable_identity VARCHAR(512),
    ADD COLUMN IF NOT EXISTS executable_sha256 VARCHAR(64),
    ADD COLUMN IF NOT EXISTS launch_identity_sha256 VARCHAR(64);

UPDATE memory_locator_runtime_incarnations
SET supervisor_key_id = 'legacy-unrecoverable',
    supervisor_public_key = repeat('0', 64),
    trust_root_sha256 = repeat('0', 64),
    trust_registry_generation = 0
WHERE supervisor_key_id IS NULL OR supervisor_public_key IS NULL;

UPDATE memory_locator_runtime_incarnations
SET trust_root_sha256 = repeat('0', 64), trust_registry_generation = 0
WHERE trust_root_sha256 IS NULL OR trust_registry_generation IS NULL;

UPDATE memory_locator_runtime_incarnations
SET launch_token = 'legacy-unrecoverable-' || md5(instance_id || ':' || generation),
    process_pid = 1,
    process_birth_identity = 'legacy-unrecoverable',
    executable_identity = '/legacy/unrecoverable',
    executable_sha256 = repeat('0', 64),
    launch_identity_sha256 = repeat('0', 64)
WHERE launch_token IS NULL;

ALTER TABLE memory_locator_runtime_incarnations
    ALTER COLUMN supervisor_key_id SET NOT NULL,
    ALTER COLUMN supervisor_public_key SET NOT NULL,
    ALTER COLUMN trust_root_sha256 SET NOT NULL,
    ALTER COLUMN trust_registry_generation SET NOT NULL,
    ALTER COLUMN launch_token SET NOT NULL,
    ALTER COLUMN process_pid SET NOT NULL,
    ALTER COLUMN process_birth_identity SET NOT NULL,
    ALTER COLUMN executable_identity SET NOT NULL,
    ALTER COLUMN executable_sha256 SET NOT NULL,
    ALTER COLUMN launch_identity_sha256 SET NOT NULL;

ALTER TABLE memory_locator_runtime_incarnations
    ADD CONSTRAINT ck_locator_runtime_supervisor_key
        CHECK (supervisor_key_id <> '' AND supervisor_public_key ~ '^[0-9a-f]{64}$'
            AND trust_root_sha256 ~ '^[0-9a-f]{64}$'
            AND trust_registry_generation >= 0),
    ADD CONSTRAINT uq_locator_runtime_dead_proof_id UNIQUE (sealed_dead_proof_id),
    ADD CONSTRAINT uq_locator_runtime_launch_token UNIQUE (launch_token),
    ADD CONSTRAINT ck_locator_runtime_launch_identity CHECK (
        process_pid > 0 AND process_birth_identity <> '' AND executable_identity <> ''
        AND executable_sha256 ~ '^[0-9a-f]{64}$'
        AND launch_identity_sha256 ~ '^[0-9a-f]{64}$'
    );

ALTER TABLE memory_locator_provider_reconciliation_receipts
    ADD COLUMN IF NOT EXISTS operation_id VARCHAR(120),
    ADD COLUMN IF NOT EXISTS owner_instance_id VARCHAR(120),
    ADD COLUMN IF NOT EXISTS owner_generation VARCHAR(120),
    ADD COLUMN IF NOT EXISTS mutation_epoch BIGINT,
    ADD COLUMN IF NOT EXISTS stale_deadline TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS consumed_by_recovery_key VARCHAR(120),
    ADD COLUMN IF NOT EXISTS consumed_at TIMESTAMPTZ;

-- 0046 is unreleased. Any populated pre-binding receipts are deliberately unusable.
UPDATE memory_locator_provider_reconciliation_receipts
SET operation_id = 'legacy-unrecoverable', owner_instance_id = 'legacy-unrecoverable',
    owner_generation = 'legacy-unrecoverable', mutation_epoch = 1,
    stale_deadline = observed_at
WHERE operation_id IS NULL;

ALTER TABLE memory_locator_provider_reconciliation_receipts
    ALTER COLUMN operation_id SET NOT NULL,
    ALTER COLUMN owner_instance_id SET NOT NULL,
    ALTER COLUMN owner_generation SET NOT NULL,
    ALTER COLUMN mutation_epoch SET NOT NULL,
    ALTER COLUMN stale_deadline SET NOT NULL,
    ADD CONSTRAINT ck_locator_provider_receipt_mutation_epoch CHECK (mutation_epoch > 0),
    ADD CONSTRAINT ck_locator_provider_receipt_consumption CHECK (
        (consumed_by_recovery_key IS NULL AND consumed_at IS NULL)
        OR (consumed_by_recovery_key IS NOT NULL AND consumed_at IS NOT NULL)
    ),
    ADD CONSTRAINT ck_locator_provider_receipt_state_evidence CHECK (
        provider_state = 'present'
        OR (provider_state = 'absent' AND observed_count = 0
            AND observed_digest =
                'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
    );

ALTER TABLE memory_locator_profile_recovery_receipts
    ADD COLUMN IF NOT EXISTS provider_receipt_id VARCHAR(120),
    ADD CONSTRAINT uq_locator_recovery_provider_receipt UNIQUE (provider_receipt_id);

ALTER TABLE memory_locator_profile_recovery_receipts
    DROP CONSTRAINT IF EXISTS ck_locator_profile_recovery_exact_kind;
ALTER TABLE memory_locator_profile_recovery_receipts
    ADD CONSTRAINT ck_locator_profile_recovery_exact_kind CHECK (
        (fence_kind = 'reader' AND lease_id IS NOT NULL AND mutation_epoch IS NULL
            AND reconciliation_digest IS NULL AND provider_receipt_id IS NULL)
        OR
        (fence_kind = 'provider_mutation' AND lease_id IS NULL AND mutation_epoch > 0
            AND reconciliation_digest IS NOT NULL AND provider_receipt_id IS NOT NULL)
    );

CREATE OR REPLACE FUNCTION memory_locator_provider_receipt_immutable_v2()
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
       OR NEW.observed_at IS DISTINCT FROM OLD.observed_at
       OR (NEW.consumed_by_recovery_key IS NULL) <> (NEW.consumed_at IS NULL)
    THEN
        RAISE EXCEPTION 'retrieval provider observation receipts are immutable';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION memory_locator_provider_receipt_immutable_v2() FROM PUBLIC;
DROP TRIGGER IF EXISTS trg_locator_provider_reconciliation_receipt_append_only
    ON memory_locator_provider_reconciliation_receipts;
CREATE TRIGGER trg_locator_provider_reconciliation_receipt_append_only
BEFORE UPDATE OR DELETE ON memory_locator_provider_reconciliation_receipts
FOR EACH ROW EXECUTE FUNCTION memory_locator_provider_receipt_immutable_v2();

ALTER TABLE memory_locator_runtime_incarnations
    DROP CONSTRAINT IF EXISTS ck_locator_runtime_dead_proof;

ALTER TABLE memory_locator_runtime_incarnations
    ADD CONSTRAINT ck_locator_runtime_dead_proof CHECK (
        (sealed_dead_generation IS NULL AND sealed_dead_proof_id IS NULL
            AND sealed_dead_proof_sha256 IS NULL AND sealed_dead_authority IS NULL
            AND sealed_dead_at IS NULL)
        OR (sealed_dead_generation > 0 AND sealed_dead_proof_id IS NOT NULL
            AND sealed_dead_proof_sha256 ~ '^[0-9a-f]{64}$'
            AND sealed_dead_authority IS NOT NULL AND sealed_dead_at IS NOT NULL)
    );

CREATE OR REPLACE FUNCTION memory_locator_runtime_dead_seal_v1()
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
       OR NEW.launch_identity_sha256 IS DISTINCT FROM OLD.launch_identity_sha256
       OR (OLD.sealed_dead_generation IS NOT NULL AND (
           NEW.sealed_dead_generation IS DISTINCT FROM OLD.sealed_dead_generation
           OR NEW.sealed_dead_proof_id IS DISTINCT FROM OLD.sealed_dead_proof_id
           OR NEW.sealed_dead_proof_sha256 IS DISTINCT FROM OLD.sealed_dead_proof_sha256
           OR NEW.sealed_dead_authority IS DISTINCT FROM OLD.sealed_dead_authority
           OR NEW.sealed_dead_at IS DISTINCT FROM OLD.sealed_dead_at))
    THEN
        RAISE EXCEPTION 'retrieval runtime launch identities and dead-owner seals are immutable';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION memory_locator_runtime_dead_seal_v1() FROM PUBLIC;
