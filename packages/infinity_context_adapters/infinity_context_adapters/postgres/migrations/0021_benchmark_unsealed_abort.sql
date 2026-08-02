ALTER TABLE memory_comparison_benchmark_runs
    DROP CONSTRAINT IF EXISTS ck_memory_comparison_benchmark_run_state,
    DROP CONSTRAINT IF EXISTS ck_memory_comparison_benchmark_run_cleanup_state,
    DROP CONSTRAINT IF EXISTS ck_memory_comparison_benchmark_run_projection_cleanup_state,
    DROP CONSTRAINT IF EXISTS ck_memory_comparison_benchmark_run_projection_lifecycle;

ALTER TABLE memory_comparison_benchmark_runs
    ADD CONSTRAINT ck_memory_comparison_benchmark_run_state CHECK (
        state IN ('active', 'cleanup_pending', 'cleanup_complete', 'cleanup_aborted')
    ) NOT VALID,
    ADD CONSTRAINT ck_memory_comparison_benchmark_run_cleanup_state CHECK (
        (state = 'active'
            AND cleanup_fingerprint_sha256 IS NULL
            AND cleanup_receipt_json IS NULL
            AND finalization_fingerprint_sha256 IS NULL
            AND completion_receipt_json IS NULL
            AND completed_at IS NULL)
        OR
        (state = 'cleanup_pending'
            AND cleanup_fingerprint_sha256 IS NOT NULL
            AND cleanup_receipt_json IS NOT NULL
            AND finalization_fingerprint_sha256 IS NULL
            AND completion_receipt_json IS NULL
            AND completed_at IS NULL)
        OR
        (state IN ('cleanup_complete', 'cleanup_aborted')
            AND cleanup_fingerprint_sha256 IS NOT NULL
            AND cleanup_receipt_json IS NOT NULL
            AND finalization_fingerprint_sha256 IS NOT NULL
            AND completion_receipt_json IS NOT NULL
            AND completed_at IS NOT NULL)
    ) NOT VALID,
    ADD CONSTRAINT ck_memory_comparison_benchmark_run_projection_cleanup_state CHECK (
        projection_cleanup_state IN (
            'unsealed', 'sealed', 'pending', 'blocked', 'complete',
            'unsealed_abort_complete'
        )
    ) NOT VALID,
    ADD CONSTRAINT ck_memory_comparison_benchmark_run_projection_lifecycle CHECK (
        (state = 'active' AND projection_cleanup_state = 'unsealed'
            AND projection_manifest_json IS NULL)
        OR
        (state = 'active' AND projection_cleanup_state = 'sealed'
            AND projection_manifest_json IS NOT NULL)
        OR
        (state = 'cleanup_pending' AND projection_cleanup_state = 'blocked'
            AND projection_manifest_json IS NULL)
        OR
        (state = 'cleanup_pending' AND projection_cleanup_state = 'pending'
            AND projection_manifest_json IS NOT NULL)
        OR
        (state = 'cleanup_complete' AND projection_cleanup_state = 'complete'
            AND projection_manifest_json IS NOT NULL)
        OR
        (state = 'cleanup_aborted'
            AND projection_cleanup_state = 'unsealed_abort_complete'
            AND projection_manifest_json IS NULL)
    ) NOT VALID;

ALTER TABLE memory_comparison_benchmark_runs
    VALIDATE CONSTRAINT ck_memory_comparison_benchmark_run_state,
    VALIDATE CONSTRAINT ck_memory_comparison_benchmark_run_cleanup_state,
    VALIDATE CONSTRAINT ck_memory_comparison_benchmark_run_projection_cleanup_state,
    VALIDATE CONSTRAINT ck_memory_comparison_benchmark_run_projection_lifecycle;
