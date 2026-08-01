CREATE TABLE IF NOT EXISTS memory_comparison_benchmark_runs (
    run_id_sha256 VARCHAR(64) PRIMARY KEY,
    binding_commitment_sha256 VARCHAR(64) NOT NULL,
    infinity_target_identity_sha256 VARCHAR(64) NOT NULL,
    space_id VARCHAR(80) NOT NULL REFERENCES memory_spaces(id),
    space_slug VARCHAR(160) NOT NULL,
    idempotency_key_sha256 VARCHAR(64) NOT NULL,
    registration_fingerprint_sha256 VARCHAR(64) NOT NULL,
    state VARCHAR(40) NOT NULL,
    cleanup_fingerprint_sha256 VARCHAR(64),
    cleanup_receipt_json JSON,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_memory_comparison_benchmark_run_state
        CHECK (state IN ('active', 'cleanup_pending')),
    CONSTRAINT ck_memory_comparison_benchmark_run_cleanup_state CHECK (
        (state = 'active' AND cleanup_fingerprint_sha256 IS NULL
            AND cleanup_receipt_json IS NULL)
        OR
        (state = 'cleanup_pending' AND cleanup_fingerprint_sha256 IS NOT NULL
            AND cleanup_receipt_json IS NOT NULL)
    ),
    CONSTRAINT uq_memory_comparison_benchmark_run_space_id UNIQUE (space_id),
    CONSTRAINT uq_memory_comparison_benchmark_run_space_slug UNIQUE (space_slug),
    CONSTRAINT uq_memory_comparison_benchmark_run_idempotency
        UNIQUE (idempotency_key_sha256)
);
