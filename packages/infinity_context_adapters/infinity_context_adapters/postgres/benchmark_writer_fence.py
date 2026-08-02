"""Postgres DDL for the managed benchmark canonical writer fence."""

from __future__ import annotations

BENCHMARK_WRITER_FENCE_SQLSTATE = "23514"
BENCHMARK_WRITER_FENCE_CONSTRAINT = "ck_memory_comparison_benchmark_run_writer_fence"
BENCHMARK_WRITER_FENCE_FUNCTION = "memory_comparison_enforce_benchmark_writer_fence"
BENCHMARK_WRITER_FENCE_TABLES = (
    ("memory_spaces", "id, status"),
    ("memory_scopes", "space_id, status"),
    ("memory_threads", "space_id, status"),
    ("memory_facts", "space_id, status"),
    ("memory_episodes", "space_id, status"),
    ("memory_documents", "space_id, status"),
    ("memory_chunks", "space_id, status"),
)

BENCHMARK_WRITER_FENCE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {BENCHMARK_WRITER_FENCE_FUNCTION}()
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
                    ERRCODE = '{BENCHMARK_WRITER_FENCE_SQLSTATE}',
                    CONSTRAINT = '{BENCHMARK_WRITER_FENCE_CONSTRAINT}';
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
                    ERRCODE = '{BENCHMARK_WRITER_FENCE_SQLSTATE}',
                    CONSTRAINT = '{BENCHMARK_WRITER_FENCE_CONSTRAINT}';
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

    IF TG_OP = 'UPDATE' THEN
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
            ERRCODE = '{BENCHMARK_WRITER_FENCE_SQLSTATE}',
            CONSTRAINT = '{BENCHMARK_WRITER_FENCE_CONSTRAINT}';
END;
$$
""".strip()


def _trigger_statements(table: str, _update_columns: str) -> tuple[str, str]:
    trigger_name = f"trg_{table}_benchmark_writer_fence"
    return (
        f"DROP TRIGGER IF EXISTS {trigger_name} ON {table}",
        f"""
        CREATE TRIGGER {trigger_name}
        BEFORE INSERT OR UPDATE OR DELETE ON {table}
        FOR EACH ROW
        EXECUTE FUNCTION {BENCHMARK_WRITER_FENCE_FUNCTION}()
        """.strip(),
    )


BENCHMARK_WRITER_FENCE_STATEMENTS = (
    BENCHMARK_WRITER_FENCE_FUNCTION_SQL,
    *(
        statement
        for table, update_columns in BENCHMARK_WRITER_FENCE_TABLES
        for statement in _trigger_statements(table, update_columns)
    ),
)

__all__ = (
    "BENCHMARK_WRITER_FENCE_CONSTRAINT",
    "BENCHMARK_WRITER_FENCE_FUNCTION",
    "BENCHMARK_WRITER_FENCE_SQLSTATE",
    "BENCHMARK_WRITER_FENCE_STATEMENTS",
    "BENCHMARK_WRITER_FENCE_TABLES",
)
