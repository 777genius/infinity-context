-- Incremental, content-addressed Qdrant checkpoint revalidation.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5min';

ALTER TABLE memory_locator_profile_attestation_checkpoints
    ADD COLUMN scan_complete BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN scan_page_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN validation_cursor VARCHAR(512),
    ADD COLUMN validation_page_number INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN validation_item_count BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN validation_accumulator CHAR(64) NOT NULL
        DEFAULT '0000000000000000000000000000000000000000000000000000000000000000',
    ADD COLUMN provider_epoch BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN owner_operation_id VARCHAR(120);

ALTER TABLE memory_locator_profiles
    ADD COLUMN provider_mutation_epoch BIGINT NOT NULL DEFAULT 0,
    ADD CONSTRAINT ck_locator_profile_provider_mutation_epoch
        CHECK (provider_mutation_epoch >= 0);

UPDATE memory_locator_profile_attestation_checkpoints
SET scan_complete = complete;

ALTER TABLE memory_locator_profile_attestation_checkpoints
    ADD CONSTRAINT ck_locator_profile_attestation_incremental_bounds CHECK (
        scan_page_count >= 0
        AND validation_page_number >= 0
        AND validation_item_count >= 0
        AND validation_accumulator ~ '^[0-9a-f]{64}$'
    );

CREATE TABLE memory_locator_profile_attestation_pages (
    profile_id VARCHAR(120) NOT NULL,
    operation_id VARCHAR(120) NOT NULL,
    page_number INTEGER NOT NULL,
    start_cursor VARCHAR(512),
    end_cursor VARCHAR(512),
    item_count INTEGER NOT NULL,
    byte_count INTEGER NOT NULL,
    page_digest CHAR(64) NOT NULL,
    PRIMARY KEY (profile_id, operation_id, page_number),
    FOREIGN KEY (profile_id, operation_id)
        REFERENCES memory_locator_profile_attestation_checkpoints(profile_id, operation_id)
        ON DELETE CASCADE,
    CONSTRAINT ck_locator_profile_attestation_page_bounds CHECK (
        page_number >= 0 AND item_count >= 0 AND byte_count >= 0
        AND page_digest ~ '^[0-9a-f]{64}$'
    )
);

-- Exact predecessor identity makes reconciliation completion a true CAS.  Rows
-- are compacted after success, retaining only the current receipt and any one
-- in-progress recovery proof.
CREATE TABLE memory_locator_profile_reconciliation_operations (
    profile_id VARCHAR(120) NOT NULL REFERENCES memory_locator_profiles(profile_id),
    operation_id VARCHAR(120) NOT NULL,
    predecessor_lease_id VARCHAR(120),
    predecessor_generation VARCHAR(160) NOT NULL,
    predecessor_evidence_digest CHAR(64),
    predecessor_lease_issued_at TIMESTAMPTZ,
    predecessor_lease_expires_at TIMESTAMPTZ,
    predecessor_drifted BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (profile_id, operation_id),
    CONSTRAINT ck_locator_profile_reconciliation_predecessor_digest CHECK (
        predecessor_evidence_digest IS NULL
        OR predecessor_evidence_digest ~ '^[0-9a-f]{64}$'
    )
);

-- Provider writes announce a durable epoch before Qdrant I/O and close it
-- afterwards.  Attestation rejects active writers and any epoch change across
-- every page. Expired crash remnants are fenced by an additional epoch bump.
CREATE TABLE memory_locator_profile_provider_mutations (
    profile_id VARCHAR(120) NOT NULL REFERENCES memory_locator_profiles(profile_id),
    operation_id VARCHAR(120) NOT NULL,
    started_epoch BIGINT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (profile_id, operation_id),
    CONSTRAINT ck_locator_profile_provider_mutation_bounds CHECK (
        started_epoch > 0 AND expires_at > started_at
    )
);

-- A rebuild page touches provider state before its canonical checkpoint.  This
-- bounded plan makes that side effect replayable, while the checkpoint,
-- projection receipts and exact operator response commit in one transaction.
CREATE TABLE memory_locator_profile_operator_rebuilds (
    idempotency_key VARCHAR(120) PRIMARY KEY,
    request_fingerprint CHAR(64) NOT NULL,
    profile_id VARCHAR(120) NOT NULL REFERENCES memory_locator_profiles(profile_id),
    plan_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_locator_profile_operator_rebuild_fingerprint CHECK (
        request_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_locator_profile_operator_rebuild_plan CHECK (
        jsonb_typeof(plan_json) = 'object'
    )
);

-- Idempotency-key ownership must survive every bounded in-progress response;
-- otherwise the same key could be redirected to a different profile before a
-- terminal exact-result receipt exists.
CREATE TABLE memory_locator_profile_operator_operations (
    idempotency_key VARCHAR(120) PRIMARY KEY,
    request_fingerprint CHAR(64) NOT NULL,
    operation VARCHAR(24) NOT NULL,
    profile_id VARCHAR(120) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_locator_profile_operator_operation_fingerprint CHECK (
        request_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_locator_profile_operator_operation_kind CHECK (
        operation IN ('create', 'rebuild', 'attest', 'activate')
    )
);
