-- Durable, expiring Retrieval V2 activation fences and resumable qualification.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5min';

ALTER TABLE memory_locator_profiles
    ADD COLUMN activation_lease_id VARCHAR(120),
    ADD COLUMN activation_evidence_digest CHAR(64),
    ADD COLUMN activation_lease_issued_at TIMESTAMPTZ,
    ADD COLUMN activation_lease_expires_at TIMESTAMPTZ,
    ADD COLUMN reconciled_at TIMESTAMPTZ,
    ADD COLUMN reconciliation_drifted BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE memory_locator_profiles ADD CONSTRAINT ck_locator_profile_activation_lease
CHECK (
    (activation_lease_id IS NULL AND activation_evidence_digest IS NULL
        AND activation_lease_issued_at IS NULL AND activation_lease_expires_at IS NULL)
    OR
    (activation_lease_id IS NOT NULL
        AND activation_evidence_digest ~ '^[0-9a-f]{64}$'
        AND activation_lease_issued_at IS NOT NULL
        AND activation_lease_expires_at > activation_lease_issued_at)
);

ALTER TABLE memory_locator_profile_lanes
    ADD COLUMN observed_count BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN observed_digest CHAR(64) NOT NULL
        DEFAULT 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
ALTER TABLE memory_locator_profile_lanes ADD CONSTRAINT ck_locator_profile_lane_evidence
CHECK (observed_count >= 0 AND observed_digest ~ '^[0-9a-f]{64}$');

CREATE TABLE memory_locator_profile_attestation_checkpoints (
    profile_id VARCHAR(120) NOT NULL REFERENCES memory_locator_profiles(profile_id),
    operation_id VARCHAR(120) NOT NULL,
    stage VARCHAR(32) NOT NULL,
    cursor VARCHAR(512),
    item_count BIGINT NOT NULL DEFAULT 0,
    digest_accumulator CHAR(64) NOT NULL
        DEFAULT '0000000000000000000000000000000000000000000000000000000000000000',
    started_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deadline_at TIMESTAMPTZ NOT NULL,
    complete BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (profile_id, operation_id),
    CONSTRAINT ck_locator_profile_attestation_checkpoint CHECK (
        stage IN ('canonical', 'receipts', 'qdrant', 'complete')
        AND item_count >= 0
        AND digest_accumulator ~ '^[0-9a-f]{64}$'
        AND deadline_at > started_at
    )
);

CREATE INDEX ix_locator_profile_attestation_resumable
    ON memory_locator_profile_attestation_checkpoints (profile_id, complete, updated_at);
