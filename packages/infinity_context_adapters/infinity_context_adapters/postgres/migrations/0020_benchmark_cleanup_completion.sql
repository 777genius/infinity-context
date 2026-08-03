ALTER TABLE memory_comparison_benchmark_runs
    ADD COLUMN IF NOT EXISTS finalization_fingerprint_sha256 VARCHAR(64),
    ADD COLUMN IF NOT EXISTS completion_receipt_json JSONB,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

ALTER TABLE memory_comparison_benchmark_runs
    DROP CONSTRAINT IF EXISTS ck_memory_comparison_benchmark_run_state,
    DROP CONSTRAINT IF EXISTS ck_memory_comparison_benchmark_run_cleanup_state,
    DROP CONSTRAINT IF EXISTS ck_memory_comparison_benchmark_run_projection_cleanup_state,
    DROP CONSTRAINT IF EXISTS ck_memory_comparison_benchmark_run_projection_lifecycle;

ALTER TABLE memory_comparison_benchmark_runs
    ADD CONSTRAINT ck_memory_comparison_benchmark_run_state CHECK (
        state IN ('active', 'cleanup_pending', 'cleanup_complete')
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
        (state = 'cleanup_complete'
            AND cleanup_fingerprint_sha256 IS NOT NULL
            AND cleanup_receipt_json IS NOT NULL
            AND finalization_fingerprint_sha256 IS NOT NULL
            AND completion_receipt_json IS NOT NULL
            AND completed_at IS NOT NULL)
    ) NOT VALID,
    ADD CONSTRAINT ck_memory_comparison_benchmark_run_projection_cleanup_state CHECK (
        projection_cleanup_state IN (
            'unsealed', 'sealed', 'pending', 'blocked', 'complete'
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
    ) NOT VALID;

ALTER TABLE memory_comparison_benchmark_runs
    VALIDATE CONSTRAINT ck_memory_comparison_benchmark_run_state,
    VALIDATE CONSTRAINT ck_memory_comparison_benchmark_run_cleanup_state,
    VALIDATE CONSTRAINT ck_memory_comparison_benchmark_run_projection_cleanup_state,
    VALIDATE CONSTRAINT ck_memory_comparison_benchmark_run_projection_lifecycle;

CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_writer_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    registry_state VARCHAR(40);
    registry_projection_cleanup_state VARCHAR(40);
    old_space_id VARCHAR(80);
    new_space_id VARCHAR(80);
    target_space_id VARCHAR(80);
BEGIN
    IF TG_OP <> 'DELETE' THEN
        IF TG_TABLE_NAME = 'memory_spaces' THEN
            new_space_id := NEW.id;
        ELSE
            new_space_id := NEW.space_id;
        END IF;
    END IF;

    IF TG_OP <> 'INSERT' THEN
        IF TG_TABLE_NAME = 'memory_spaces' THEN
            old_space_id := OLD.id;
        ELSE
            old_space_id := OLD.space_id;
        END IF;
    END IF;

    IF TG_OP = 'UPDATE' AND old_space_id IS DISTINCT FROM new_space_id THEN
        IF EXISTS (
            SELECT 1
            FROM memory_comparison_benchmark_runs AS benchmark_run
            WHERE benchmark_run.space_id IN (old_space_id, new_space_id)
        ) THEN
            RAISE EXCEPTION 'benchmark canonical space identity is immutable'
                USING
                    ERRCODE = '23514',
                    CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
        END IF;
    END IF;

    target_space_id := COALESCE(new_space_id, old_space_id);
    BEGIN
        SELECT benchmark_run.state, benchmark_run.projection_cleanup_state
        INTO registry_state, registry_projection_cleanup_state
        FROM memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = target_space_id
        FOR SHARE NOWAIT;
    EXCEPTION
        WHEN lock_not_available THEN
            RAISE EXCEPTION 'benchmark canonical writer fence rejected data mutation'
                USING
                    ERRCODE = '23514',
                    CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END;

    IF registry_state IS NULL THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    IF registry_state = 'active'
        AND registry_projection_cleanup_state = 'unsealed'
    THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE'
        AND TG_TABLE_NAME IN (
            'memory_spaces', 'memory_scopes', 'memory_threads', 'memory_facts',
            'memory_episodes', 'memory_documents', 'memory_chunks'
        )
    THEN
        IF registry_state = 'cleanup_pending'
            AND registry_projection_cleanup_state IN ('pending', 'blocked')
            AND OLD.status = 'active'
            AND NEW.status = 'deleted'
            AND (to_jsonb(OLD) - 'status' - 'updated_at')
                = (to_jsonb(NEW) - 'status' - 'updated_at')
        THEN
            RETURN NEW;
        END IF;
    END IF;

    RAISE EXCEPTION 'benchmark canonical writer fence rejected data mutation'
        USING
            ERRCODE = '23514',
            CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
END;
$$;

DO $$
DECLARE
    table_name TEXT;
    schema_name TEXT := current_schema();
    required_table_names CONSTANT TEXT[] := ARRAY[
        'memory_spaces',
        'memory_scopes',
        'memory_threads',
        'memory_facts',
        'memory_episodes',
        'memory_documents',
        'memory_chunks'
    ];
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'memory_spaces',
        'memory_scopes',
        'memory_threads',
        'memory_facts',
        'memory_episodes',
        'memory_documents',
        'memory_chunks',
        'memory_anchors',
        'memory_assets',
        'memory_asset_extraction_jobs',
        'memory_fact_relations',
        'memory_suggestions',
        'memory_captures',
        'memory_context_links',
        'memory_context_link_suggestions'
    ]
    LOOP
        IF pg_catalog.to_regclass(
            format('%I.%I', schema_name, table_name)
        ) IS NULL THEN
            IF table_name = ANY(required_table_names) THEN
                RAISE EXCEPTION 'required benchmark writer fence table % is missing',
                    table_name
                    USING ERRCODE = '42P01';
            END IF;
            CONTINUE;
        END IF;
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON %I.%I',
            'trg_' || table_name || '_benchmark_writer_fence',
            schema_name,
            table_name
        );
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE INSERT OR UPDATE OR DELETE ON %I.%I '
            || 'FOR EACH ROW EXECUTE FUNCTION '
            || 'memory_comparison_enforce_benchmark_writer_fence()',
            'trg_' || table_name || '_benchmark_writer_fence',
            schema_name,
            table_name
        );
    END LOOP;
END;
$$;
