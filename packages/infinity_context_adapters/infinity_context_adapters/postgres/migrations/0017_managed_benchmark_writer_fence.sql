CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_writer_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    registry_state VARCHAR(40);
    old_space_id VARCHAR(80);
    new_space_id VARCHAR(80);
BEGIN
    IF TG_TABLE_NAME = 'memory_spaces' THEN
        new_space_id := NEW.id;
        IF TG_OP = 'UPDATE' THEN
            old_space_id := OLD.id;
        END IF;
    ELSE
        new_space_id := NEW.space_id;
        IF TG_OP = 'UPDATE' THEN
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

    IF NEW.status IS DISTINCT FROM 'active' THEN
        RETURN NEW;
    END IF;

    BEGIN
        SELECT benchmark_run.state
        INTO registry_state
        FROM memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = new_space_id
        FOR SHARE NOWAIT;
    EXCEPTION
        WHEN lock_not_available THEN
            RAISE EXCEPTION 'benchmark canonical writer fence rejected active data'
                USING
                    ERRCODE = '23514',
                    CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END;

    IF registry_state = 'cleanup_pending' THEN
        RAISE EXCEPTION 'benchmark canonical writer fence rejected active data'
            USING
                ERRCODE = '23514',
                CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_memory_spaces_benchmark_writer_fence ON memory_spaces;
CREATE TRIGGER trg_memory_spaces_benchmark_writer_fence
BEFORE INSERT OR UPDATE OF id, status ON memory_spaces
FOR EACH ROW
EXECUTE FUNCTION memory_comparison_enforce_benchmark_writer_fence();

DROP TRIGGER IF EXISTS trg_memory_scopes_benchmark_writer_fence ON memory_scopes;
CREATE TRIGGER trg_memory_scopes_benchmark_writer_fence
BEFORE INSERT OR UPDATE OF space_id, status ON memory_scopes
FOR EACH ROW
EXECUTE FUNCTION memory_comparison_enforce_benchmark_writer_fence();

DROP TRIGGER IF EXISTS trg_memory_threads_benchmark_writer_fence ON memory_threads;
CREATE TRIGGER trg_memory_threads_benchmark_writer_fence
BEFORE INSERT OR UPDATE OF space_id, status ON memory_threads
FOR EACH ROW
EXECUTE FUNCTION memory_comparison_enforce_benchmark_writer_fence();

DROP TRIGGER IF EXISTS trg_memory_facts_benchmark_writer_fence ON memory_facts;
CREATE TRIGGER trg_memory_facts_benchmark_writer_fence
BEFORE INSERT OR UPDATE OF space_id, status ON memory_facts
FOR EACH ROW
EXECUTE FUNCTION memory_comparison_enforce_benchmark_writer_fence();

DROP TRIGGER IF EXISTS trg_memory_episodes_benchmark_writer_fence ON memory_episodes;
CREATE TRIGGER trg_memory_episodes_benchmark_writer_fence
BEFORE INSERT OR UPDATE OF space_id, status ON memory_episodes
FOR EACH ROW
EXECUTE FUNCTION memory_comparison_enforce_benchmark_writer_fence();

DROP TRIGGER IF EXISTS trg_memory_documents_benchmark_writer_fence ON memory_documents;
CREATE TRIGGER trg_memory_documents_benchmark_writer_fence
BEFORE INSERT OR UPDATE OF space_id, status ON memory_documents
FOR EACH ROW
EXECUTE FUNCTION memory_comparison_enforce_benchmark_writer_fence();

DROP TRIGGER IF EXISTS trg_memory_chunks_benchmark_writer_fence ON memory_chunks;
CREATE TRIGGER trg_memory_chunks_benchmark_writer_fence
BEFORE INSERT OR UPDATE OF space_id, status ON memory_chunks
FOR EACH ROW
EXECUTE FUNCTION memory_comparison_enforce_benchmark_writer_fence();
