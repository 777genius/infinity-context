ALTER TABLE memory_comparison_benchmark_runs
    ADD COLUMN IF NOT EXISTS projection_manifest_json JSONB,
    ADD COLUMN IF NOT EXISTS projection_manifest_sha256 VARCHAR(64),
    ADD COLUMN IF NOT EXISTS projection_cleanup_state VARCHAR(40);

UPDATE memory_comparison_benchmark_runs
SET projection_cleanup_state = CASE
    WHEN state = 'active' THEN 'unsealed'
    WHEN state = 'cleanup_pending' THEN 'blocked'
END
WHERE projection_cleanup_state IS NULL;

ALTER TABLE memory_comparison_benchmark_runs
    ALTER COLUMN projection_cleanup_state SET DEFAULT 'unsealed',
    ALTER COLUMN projection_cleanup_state SET NOT NULL;

ALTER TABLE memory_comparison_benchmark_runs
    DROP CONSTRAINT IF EXISTS ck_memory_comparison_benchmark_run_manifest_coupling,
    DROP CONSTRAINT IF EXISTS ck_memory_comparison_benchmark_run_projection_cleanup_state,
    DROP CONSTRAINT IF EXISTS ck_memory_comparison_benchmark_run_projection_lifecycle;

ALTER TABLE memory_comparison_benchmark_runs
    ADD CONSTRAINT ck_memory_comparison_benchmark_run_manifest_coupling CHECK (
        (projection_manifest_json IS NULL AND projection_manifest_sha256 IS NULL)
        OR
        (projection_manifest_json IS NOT NULL AND projection_manifest_sha256 IS NOT NULL)
    ) NOT VALID,
    ADD CONSTRAINT ck_memory_comparison_benchmark_run_projection_cleanup_state CHECK (
        projection_cleanup_state IN (
            'unsealed', 'sealed', 'pending', 'blocked'
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
        (state = 'cleanup_pending'
            AND projection_cleanup_state = 'pending'
            AND projection_manifest_json IS NOT NULL)
    ) NOT VALID;

ALTER TABLE memory_comparison_benchmark_runs
    VALIDATE CONSTRAINT ck_memory_comparison_benchmark_run_manifest_coupling,
    VALIDATE CONSTRAINT ck_memory_comparison_benchmark_run_projection_cleanup_state,
    VALIDATE CONSTRAINT ck_memory_comparison_benchmark_run_projection_lifecycle;
