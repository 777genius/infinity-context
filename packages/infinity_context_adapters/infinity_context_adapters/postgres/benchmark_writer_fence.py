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
                    ERRCODE = '{BENCHMARK_WRITER_FENCE_SQLSTATE}',
                    CONSTRAINT = '{BENCHMARK_WRITER_FENCE_CONSTRAINT}';
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
                    ERRCODE = '{BENCHMARK_WRITER_FENCE_SQLSTATE}',
                    CONSTRAINT = '{BENCHMARK_WRITER_FENCE_CONSTRAINT}';
    END;

    IF registry_state = 'cleanup_pending' THEN
        RAISE EXCEPTION 'benchmark canonical writer fence rejected active data'
            USING
                ERRCODE = '{BENCHMARK_WRITER_FENCE_SQLSTATE}',
                CONSTRAINT = '{BENCHMARK_WRITER_FENCE_CONSTRAINT}';
    END IF;

    RETURN NEW;
END;
$$
""".strip()


def _trigger_statements(table: str, update_columns: str) -> tuple[str, str]:
    trigger_name = f"trg_{table}_benchmark_writer_fence"
    return (
        f"DROP TRIGGER IF EXISTS {trigger_name} ON {table}",
        f"""
        CREATE TRIGGER {trigger_name}
        BEFORE INSERT OR UPDATE OF {update_columns} ON {table}
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
