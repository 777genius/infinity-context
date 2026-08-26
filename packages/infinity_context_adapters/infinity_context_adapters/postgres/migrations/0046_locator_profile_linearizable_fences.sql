-- Linearizable admission, owner-bound provider writers, and evidence invalidation.
-- Deploy only after every pre-0046 binary has drained: old readers do not register.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5min';

ALTER TABLE memory_locator_profile_cleanups
    ADD COLUMN IF NOT EXISTS delete_token VARCHAR(120),
    ADD COLUMN IF NOT EXISTS delete_epoch BIGINT,
    ADD COLUMN IF NOT EXISTS delete_authorized_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_locator_profile_cleanup_delete_authority'
          AND conrelid = 'memory_locator_profile_cleanups'::regclass
    ) THEN
        ALTER TABLE memory_locator_profile_cleanups
            ADD CONSTRAINT ck_locator_profile_cleanup_delete_authority CHECK (
                (delete_token IS NULL AND delete_epoch IS NULL AND delete_authorized_at IS NULL)
                OR (delete_token IS NOT NULL AND delete_epoch > 0
                    AND delete_authorized_at IS NOT NULL)
            );
    END IF;
END $$;

ALTER TABLE memory_locator_profiles
    ADD COLUMN IF NOT EXISTS activation_evidence_version BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS activation_mutation_epoch BIGINT NOT NULL DEFAULT 0;

ALTER TABLE memory_locator_profile_provider_mutations
    ADD COLUMN IF NOT EXISTS owner_instance_id VARCHAR(120)
        NOT NULL DEFAULT 'pre-0046-owner',
    ADD COLUMN IF NOT EXISTS owner_generation VARCHAR(120)
        NOT NULL DEFAULT 'pre-0046-generation';

COMMENT ON COLUMN memory_locator_profile_provider_mutations.expires_at IS
    'Diagnostic heartbeat deadline only; never authorizes lease stealing or deletion';

CREATE OR REPLACE FUNCTION memory_locator_profile_reject_pre0046_writer_v1()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.owner_instance_id = 'pre-0046-owner'
       OR NEW.owner_generation = 'pre-0046-generation' THEN
        RAISE EXCEPTION 'pre-0046 Retrieval V2 writers are incompatible after migration 0046';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_locator_profile_reject_pre0046_writer
    ON memory_locator_profile_provider_mutations;
CREATE TRIGGER trg_locator_profile_reject_pre0046_writer
BEFORE INSERT OR UPDATE ON memory_locator_profile_provider_mutations
FOR EACH ROW EXECUTE FUNCTION memory_locator_profile_reject_pre0046_writer_v1();

CREATE TABLE IF NOT EXISTS memory_locator_profile_queries (
    profile_id VARCHAR(120) NOT NULL REFERENCES memory_locator_profiles(profile_id),
    operation_id VARCHAR(120) NOT NULL,
    owner_instance_id VARCHAR(120) NOT NULL,
    owner_generation VARCHAR(120) NOT NULL,
    activation_lease_id VARCHAR(120) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (profile_id, operation_id),
    CONSTRAINT ck_locator_profile_query_bounds CHECK (expires_at > started_at)
);

CREATE INDEX IF NOT EXISTS ix_locator_profile_queries_active
    ON memory_locator_profile_queries (profile_id, started_at);

COMMENT ON COLUMN memory_locator_profile_queries.expires_at IS
    'Diagnostic deadline only; an elapsed reader is never silently stolen or deleted';

CREATE TABLE IF NOT EXISTS memory_locator_profile_evidence_versions (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    aggregate_version BIGINT NOT NULL CHECK (aggregate_version >= 0),
    changed_at TIMESTAMPTZ NOT NULL
);

INSERT INTO memory_locator_profile_evidence_versions
    (singleton, aggregate_version, changed_at)
VALUES (TRUE, 1, CURRENT_TIMESTAMP)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS memory_locator_profile_maintenance_fence (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    fence_generation BIGINT NOT NULL CHECK (fence_generation >= 0),
    active BOOLEAN NOT NULL DEFAULT FALSE,
    reason VARCHAR(500),
    changed_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE memory_locator_profile_maintenance_fence
    ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS reason VARCHAR(500);

INSERT INTO memory_locator_profile_maintenance_fence
    (singleton, fence_generation, changed_at)
VALUES (TRUE, 0, CURRENT_TIMESTAMP)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS memory_locator_runtime_incarnations (
    instance_id VARCHAR(120) NOT NULL,
    generation VARCHAR(120) NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    acknowledged_generation BIGINT NOT NULL DEFAULT 0 CHECK (acknowledged_generation >= 0),
    sealed_dead_generation BIGINT,
    sealed_dead_proof_sha256 VARCHAR(64),
    sealed_dead_authority VARCHAR(120),
    sealed_dead_at TIMESTAMPTZ,
    PRIMARY KEY (instance_id, generation),
    CONSTRAINT ck_locator_runtime_dead_proof CHECK (
        (sealed_dead_generation IS NULL AND sealed_dead_proof_sha256 IS NULL
            AND sealed_dead_authority IS NULL AND sealed_dead_at IS NULL)
        OR (sealed_dead_generation > 0 AND sealed_dead_proof_sha256 ~ '^[0-9a-f]{64}$'
            AND sealed_dead_authority IS NOT NULL AND sealed_dead_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS memory_locator_provider_reconciliation_receipts (
    receipt_id VARCHAR(120) PRIMARY KEY,
    profile_id VARCHAR(120) NOT NULL,
    profile_generation VARCHAR(160) NOT NULL,
    collection_name VARCHAR(240) NOT NULL,
    maintenance_generation BIGINT NOT NULL CHECK (maintenance_generation > 0),
    evidence_epoch BIGINT NOT NULL CHECK (evidence_epoch >= 0),
    observed_count BIGINT NOT NULL CHECK (observed_count >= 0),
    observed_digest VARCHAR(64) NOT NULL CHECK (observed_digest ~ '^[0-9a-f]{64}$'),
    provider_state VARCHAR(32) NOT NULL CHECK (provider_state IN ('present', 'absent')),
    receipt_sha256 VARCHAR(64) NOT NULL UNIQUE CHECK (receipt_sha256 ~ '^[0-9a-f]{64}$'),
    observed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_locator_profile_recovery_receipts (
    idempotency_key VARCHAR(120) PRIMARY KEY,
    request_fingerprint VARCHAR(64) NOT NULL,
    fence_kind VARCHAR(32) NOT NULL CHECK (fence_kind IN ('reader', 'provider_mutation')),
    profile_id VARCHAR(120) NOT NULL,
    operation_id VARCHAR(120) NOT NULL,
    owner_instance_id VARCHAR(120) NOT NULL,
    owner_generation VARCHAR(120) NOT NULL,
    lease_id VARCHAR(120),
    mutation_epoch BIGINT,
    stale_deadline TIMESTAMPTZ NOT NULL,
    reason VARCHAR(500) NOT NULL,
    reconciliation_digest VARCHAR(64),
    maintenance_generation BIGINT NOT NULL CHECK (maintenance_generation > 0),
    recovered_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_locator_profile_recovery_exact_kind CHECK (
        (fence_kind = 'reader' AND lease_id IS NOT NULL AND mutation_epoch IS NULL
            AND reconciliation_digest IS NULL)
        OR
        (fence_kind = 'provider_mutation' AND lease_id IS NULL AND mutation_epoch > 0
            AND reconciliation_digest IS NOT NULL)
    )
);

CREATE OR REPLACE FUNCTION memory_locator_profile_recovery_receipt_append_only_v1()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'retrieval profile recovery receipts are append-only';
END;
$$;

REVOKE ALL ON FUNCTION memory_locator_profile_recovery_receipt_append_only_v1() FROM PUBLIC;
DROP TRIGGER IF EXISTS trg_memory_locator_profile_recovery_receipt_append_only
    ON memory_locator_profile_recovery_receipts;
CREATE TRIGGER trg_memory_locator_profile_recovery_receipt_append_only
BEFORE UPDATE OR DELETE ON memory_locator_profile_recovery_receipts
FOR EACH ROW EXECUTE FUNCTION memory_locator_profile_recovery_receipt_append_only_v1();

DROP TRIGGER IF EXISTS trg_locator_provider_reconciliation_receipt_append_only
    ON memory_locator_provider_reconciliation_receipts;
CREATE TRIGGER trg_locator_provider_reconciliation_receipt_append_only
BEFORE UPDATE OR DELETE ON memory_locator_provider_reconciliation_receipts
FOR EACH ROW EXECUTE FUNCTION memory_locator_profile_recovery_receipt_append_only_v1();

CREATE OR REPLACE FUNCTION memory_locator_runtime_dead_seal_v1()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.sealed_dead_generation IS NOT NULL AND (
        NEW.sealed_dead_generation IS DISTINCT FROM OLD.sealed_dead_generation
        OR NEW.sealed_dead_proof_sha256 IS DISTINCT FROM OLD.sealed_dead_proof_sha256
        OR NEW.sealed_dead_authority IS DISTINCT FROM OLD.sealed_dead_authority
        OR NEW.sealed_dead_at IS DISTINCT FROM OLD.sealed_dead_at
    ) THEN
        RAISE EXCEPTION 'retrieval runtime dead-owner seals are immutable';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_locator_runtime_dead_seal
    ON memory_locator_runtime_incarnations;
CREATE TRIGGER trg_locator_runtime_dead_seal
BEFORE UPDATE ON memory_locator_runtime_incarnations
FOR EACH ROW EXECUTE FUNCTION memory_locator_runtime_dead_seal_v1();

-- Pre-0046 leases were created without an evidence-version/read-fence contract.
-- Preserve their identities for audit, but make every one unroutable until a fresh
-- bounded reconciliation issues a versioned lease.
UPDATE memory_locator_profiles
SET reconciliation_drifted = CASE WHEN state = 'active' THEN TRUE
                                  ELSE reconciliation_drifted END,
    activation_lease_expires_at = CASE
        WHEN activation_lease_issued_at IS NULL THEN activation_lease_expires_at
        ELSE GREATEST(
            activation_lease_issued_at + INTERVAL '1 microsecond', CURRENT_TIMESTAMP
        )
    END,
    activation_evidence_version = 0,
    activation_mutation_epoch = 0
WHERE state IN ('building', 'active', 'retained')
  AND activation_lease_id IS NOT NULL
  AND activation_evidence_version = 0;

CREATE OR REPLACE FUNCTION memory_locator_profile_invalidate_evidence_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    -- Global lock order is evidence -> profiles -> trigger-bearing/dependent rows.
    UPDATE public.memory_locator_profile_evidence_versions
    SET aggregate_version = aggregate_version + 1,
        changed_at = CURRENT_TIMESTAMP
    WHERE singleton = TRUE;

    UPDATE public.memory_locator_profiles
    SET reconciliation_drifted = CASE WHEN state = 'active' THEN TRUE
                                      ELSE reconciliation_drifted END,
        activation_lease_expires_at = CASE
            WHEN activation_lease_issued_at IS NULL THEN activation_lease_expires_at
            ELSE GREATEST(
                activation_lease_issued_at + INTERVAL '1 microsecond', CURRENT_TIMESTAMP
            )
        END
    WHERE state IN ('building', 'active', 'retained')
      AND activation_lease_id IS NOT NULL;

    IF TG_LEVEL = 'ROW' THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION memory_locator_profile_invalidate_evidence_v1() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_locator_profile_lane_evidence_version
    ON memory_locator_profile_lanes;
CREATE TRIGGER trg_locator_profile_lane_evidence_version
BEFORE INSERT OR UPDATE OR DELETE ON memory_locator_profile_lanes
FOR EACH STATEMENT EXECUTE FUNCTION memory_locator_profile_invalidate_evidence_v1();

DROP TRIGGER IF EXISTS trg_locator_profile_tombstone_evidence_version
    ON memory_locator_profile_tombstones;
CREATE TRIGGER trg_locator_profile_tombstone_evidence_version
BEFORE INSERT OR UPDATE OR DELETE ON memory_locator_profile_tombstones
FOR EACH STATEMENT EXECUTE FUNCTION memory_locator_profile_invalidate_evidence_v1();

DROP TRIGGER IF EXISTS trg_locator_profile_receipt_evidence_version
    ON memory_locator_profile_projection_receipts;
CREATE TRIGGER trg_locator_profile_receipt_evidence_version
BEFORE INSERT OR UPDATE OR DELETE ON memory_locator_profile_projection_receipts
FOR EACH STATEMENT EXECUTE FUNCTION memory_locator_profile_invalidate_evidence_v1();

DROP TRIGGER IF EXISTS trg_locator_profile_outbox_evidence_version ON memory_outbox;
-- These names sort before the strict-v4 fact/document row fences, preserving
-- evidence -> profiles -> dependent-row lock order for relevant outbox rows.
DROP TRIGGER IF EXISTS trg_00_locator_profile_outbox_evidence_insert ON memory_outbox;
DROP TRIGGER IF EXISTS trg_00_locator_profile_outbox_evidence_update ON memory_outbox;
DROP TRIGGER IF EXISTS trg_00_locator_profile_outbox_evidence_delete ON memory_outbox;

CREATE TRIGGER trg_00_locator_profile_outbox_evidence_insert
BEFORE INSERT ON memory_outbox
FOR EACH ROW
WHEN (NEW.event_type IN (
    'vector.upsert_locator_profile', 'vector.delete_locator_profile'
))
EXECUTE FUNCTION memory_locator_profile_invalidate_evidence_v1();

CREATE TRIGGER trg_00_locator_profile_outbox_evidence_update
BEFORE UPDATE ON memory_outbox
FOR EACH ROW
WHEN (
    OLD.event_type IN (
        'vector.upsert_locator_profile', 'vector.delete_locator_profile'
    ) OR NEW.event_type IN (
        'vector.upsert_locator_profile', 'vector.delete_locator_profile'
    )
)
EXECUTE FUNCTION memory_locator_profile_invalidate_evidence_v1();

CREATE TRIGGER trg_00_locator_profile_outbox_evidence_delete
BEFORE DELETE ON memory_outbox
FOR EACH ROW
WHEN (OLD.event_type IN (
    'vector.upsert_locator_profile', 'vector.delete_locator_profile'
))
EXECUTE FUNCTION memory_locator_profile_invalidate_evidence_v1();

DROP TRIGGER IF EXISTS trg_locator_profile_canonical_evidence_version ON memory_chunks;
CREATE TRIGGER trg_locator_profile_canonical_evidence_version
BEFORE INSERT OR UPDATE OR DELETE ON memory_chunks
FOR EACH STATEMENT EXECUTE FUNCTION memory_locator_profile_invalidate_evidence_v1();
