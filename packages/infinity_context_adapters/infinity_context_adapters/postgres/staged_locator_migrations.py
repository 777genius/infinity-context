"""Online expand/backfill/cutover support for locator migrations 0039 and 0040."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_BATCH_SIZE = 2000
STAGED_MIGRATION_IDS = frozenset(
    {"0039_locator_retrieval_attributes", "0040_locator_profile_lifecycle"}
)
_OUTBOX_GUARD_TRIGGERS = (
    (
        "trg_00_memory_outbox_benchmark_fact_child_lock",
        "memory_comparison_lock_benchmark_fact_child_target",
        False,
        "NEW.aggregate_type = 'fact'",
    ),
    (
        "trg_memory_outbox_benchmark_fact_child_fence",
        "memory_comparison_enforce_benchmark_fact_child_fence",
        False,
        "NEW.aggregate_type = 'fact'",
    ),
    (
        "trg_00_memory_outbox_benchmark_document_child_lock",
        "memory_comparison_lock_benchmark_document_child_target",
        False,
        "NEW.aggregate_type = 'chunk'",
    ),
    (
        "trg_memory_outbox_benchmark_document_child_fence",
        "memory_comparison_enforce_benchmark_document_child_fence",
        False,
        "NEW.aggregate_type = 'chunk'",
    ),
)
_CHUNK_GUARD_TRIGGERS = (
    (
        "trg_00_memory_chunks_benchmark_writer_lock",
        "memory_comparison_lock_benchmark_writer_target",
        True,
        None,
    ),
    (
        "trg_memory_chunks_benchmark_writer_fence",
        "memory_comparison_enforce_benchmark_writer_fence",
        True,
        None,
    ),
    (
        "trg_00_memory_chunks_benchmark_document_child_lock",
        "memory_comparison_lock_benchmark_document_child_target",
        True,
        None,
    ),
    (
        "trg_memory_chunks_benchmark_document_child_fence",
        "memory_comparison_enforce_benchmark_document_child_fence",
        True,
        None,
    ),
)
_RECEIPT_CANONICAL_JOB_CONSTRAINT = "uq_projection_receipt_canonical_job"
_RECEIPT_CANONICAL_JOB_STAGE_INDEX = "uq_projection_receipt_canonical_job_bigint_stage"


async def apply_staged_locator_migration(
    connection: AsyncConnection, *, migration_id: str
) -> None:
    """Apply one locator migration, committing between bounded online phases."""

    if migration_id == "0039_locator_retrieval_attributes":
        await _stage_integer_to_bigint(connection, table="memory_outbox")
        await _stage_integer_to_bigint(
            connection, table="memory_projection_result_receipts", optional=True
        )
    elif migration_id == "0040_locator_profile_lifecycle":
        await _stage_locator_watermark(connection)
    else:  # pragma: no cover - caller fences the dispatch
        raise ValueError(f"Unsupported staged migration: {migration_id}")


async def _stage_integer_to_bigint(
    connection: AsyncConnection, *, table: str, optional: bool = False
) -> None:
    async with connection.begin():
        exists = await _table_exists(connection, table)
        column_type = (
            await _column_type(connection, table, "aggregate_version") if exists else None
        )
    if optional and not exists:
        return
    if column_type == "bigint":
        return

    shadow = "aggregate_version_bigint"
    function = f"{table}_aggregate_version_bigint_mirror_v1"
    trigger = f"trg_{table}_aggregate_version_bigint_mirror_v1"
    async with connection.begin():
        guard_sql = ""
        if table == "memory_outbox":
            columns = await _column_names(
                connection, table, excluded=frozenset({shadow})
            )
            guard_sql = _render_guard_triggers(
                table=table,
                columns=columns,
                triggers=_OUTBOX_GUARD_TRIGGERS,
                update_only=True,
            )
        await _execute_script(
            connection,
            f"""
            SET LOCAL lock_timeout = '1s';
            SET LOCAL statement_timeout = '30s';
            ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS {shadow} BIGINT;
            CREATE OR REPLACE FUNCTION public.{function}() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                NEW.{shadow} := NEW.aggregate_version::bigint;
                RETURN NEW;
            END $$;
            DROP TRIGGER IF EXISTS {trigger} ON public.{table};
            CREATE TRIGGER {trigger} BEFORE INSERT OR UPDATE OF aggregate_version
                ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.{function}();
            {guard_sql}
            """,
        )

    while True:
        async with connection.begin():
            changed = await connection.scalar(
                text(
                    f"""
                    WITH batch AS (
                        SELECT ctid FROM public.{table}
                        WHERE aggregate_version IS NOT NULL AND {shadow} IS NULL
                        LIMIT {_BATCH_SIZE} FOR UPDATE SKIP LOCKED
                    ), updated AS (
                        UPDATE public.{table} AS target
                        SET {shadow} = target.aggregate_version::bigint
                        FROM batch WHERE target.ctid = batch.ctid RETURNING 1
                    ) SELECT count(*) FROM updated
                    """
                )
            )
        if int(changed or 0) == 0:
            break

    constraint = f"ck_{table}_aggregate_version_bigint_mirror"
    async with connection.begin():
        restore_guards = ""
        drop_guards = ""
        drop_dependencies = ""
        restore_dependencies = ""
        if table == "memory_outbox":
            drop_guards = _render_drop_triggers(
                table=table, triggers=_OUTBOX_GUARD_TRIGGERS
            )
            restore_guards = _render_guard_triggers(
                table=table,
                columns=(),
                triggers=_OUTBOX_GUARD_TRIGGERS,
                update_only=False,
            )
        elif table == "memory_projection_result_receipts":
            drop_dependencies = f"""
            ALTER TABLE public.{table}
                DROP CONSTRAINT IF EXISTS {_RECEIPT_CANONICAL_JOB_CONSTRAINT};
            """
            restore_dependencies = f"""
            ALTER TABLE public.{table}
                ADD CONSTRAINT {_RECEIPT_CANONICAL_JOB_CONSTRAINT}
                UNIQUE USING INDEX {_RECEIPT_CANONICAL_JOB_STAGE_INDEX};
            """
        await _execute_script(
            connection,
            f"""
            ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS {constraint};
            ALTER TABLE public.{table} ADD CONSTRAINT {constraint}
                CHECK ({shadow} IS NOT DISTINCT FROM aggregate_version::bigint) NOT VALID;
            ALTER TABLE public.{table} VALIDATE CONSTRAINT {constraint};
            """,
        )

    if table == "memory_projection_result_receipts":
        await _stage_receipt_canonical_job_index(connection, shadow=shadow)

    async with connection.begin():
        await _execute_script(
            connection,
            f"""
            SET LOCAL lock_timeout = '1s';
            SET LOCAL statement_timeout = '5s';
            LOCK TABLE public.{table} IN ACCESS EXCLUSIVE MODE;
            DROP TRIGGER IF EXISTS {trigger} ON public.{table};
            {drop_guards}
            {drop_dependencies}
            ALTER TABLE public.{table} DROP CONSTRAINT {constraint};
            ALTER TABLE public.{table}
                RENAME COLUMN aggregate_version TO aggregate_version_integer_old;
            ALTER TABLE public.{table} RENAME COLUMN {shadow} TO aggregate_version;
            ALTER TABLE public.{table} DROP COLUMN aggregate_version_integer_old;
            DROP FUNCTION public.{function}();
            {restore_dependencies}
            {restore_guards}
            """,
        )


async def _stage_locator_watermark(connection: AsyncConnection) -> None:
    async with connection.begin():
        column_type = await _column_type(
            connection, "memory_chunks", "retrieval_commit_watermark"
        )
        nullable = None
        if column_type == "bigint":
            nullable = await connection.scalar(
                text(
                    """
                    SELECT is_nullable = 'YES' FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'memory_chunks'
                      AND column_name = 'retrieval_commit_watermark'
                    """
                )
            )
    if column_type == "bigint" and not nullable:
        return

    async with connection.begin():
        columns = await _column_names(
            connection,
            "memory_chunks",
            excluded=frozenset({"retrieval_commit_watermark"}),
        )
        guard_sql = _render_guard_triggers(
            table="memory_chunks",
            columns=columns,
            triggers=_CHUNK_GUARD_TRIGGERS,
            update_only=True,
        )
        await _execute_script(
            connection,
            """
            SET LOCAL lock_timeout = '1s';
            SET LOCAL statement_timeout = '30s';
            CREATE SEQUENCE IF NOT EXISTS public.memory_locator_commit_watermark_seq;
            REVOKE ALL PRIVILEGES ON SEQUENCE
                public.memory_locator_commit_watermark_seq FROM PUBLIC;
            GRANT USAGE ON SEQUENCE public.memory_locator_commit_watermark_seq
                TO infinity_context_canonical_writer;
            ALTER TABLE public.memory_chunks
                ADD COLUMN IF NOT EXISTS retrieval_commit_watermark BIGINT;
            CREATE OR REPLACE FUNCTION public.memory_chunk_locator_watermark_mirror_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                IF NEW.retrieval_commit_watermark IS NULL THEN
                    NEW.retrieval_commit_watermark :=
                        nextval('public.memory_locator_commit_watermark_seq');
                END IF;
                RETURN NEW;
            END $$;
            DROP TRIGGER IF EXISTS trg_memory_chunk_locator_watermark_mirror_v1
                ON public.memory_chunks;
            CREATE TRIGGER trg_memory_chunk_locator_watermark_mirror_v1
                BEFORE INSERT OR UPDATE ON public.memory_chunks FOR EACH ROW
                EXECUTE FUNCTION public.memory_chunk_locator_watermark_mirror_v1();
            """
            + guard_sql
            + """
            """,
        )

    while True:
        async with connection.begin():
            changed = await connection.scalar(
                text(
                    f"""
                    WITH batch AS (
                        SELECT ctid FROM public.memory_chunks
                        WHERE retrieval_commit_watermark IS NULL
                        LIMIT {_BATCH_SIZE} FOR UPDATE SKIP LOCKED
                    ), updated AS (
                        UPDATE public.memory_chunks AS target
                        SET retrieval_commit_watermark =
                            nextval('public.memory_locator_commit_watermark_seq')
                        FROM batch WHERE target.ctid = batch.ctid RETURNING 1
                    ) SELECT count(*) FROM updated
                    """
                )
            )
        if int(changed or 0) == 0:
            break

    async with connection.begin():
        restore_guards = _render_guard_triggers(
            table="memory_chunks",
            columns=(),
            triggers=_CHUNK_GUARD_TRIGGERS,
            update_only=False,
        )
        await _execute_script(
            connection,
            """
            ALTER TABLE public.memory_chunks DROP CONSTRAINT IF EXISTS
                ck_memory_chunks_locator_watermark_present;
            ALTER TABLE public.memory_chunks
                ADD CONSTRAINT ck_memory_chunks_locator_watermark_present
                CHECK (retrieval_commit_watermark IS NOT NULL) NOT VALID;
            ALTER TABLE public.memory_chunks
                VALIDATE CONSTRAINT ck_memory_chunks_locator_watermark_present;
            """,
        )
    async with connection.begin():
        await _execute_script(
            connection,
            """
            SET LOCAL lock_timeout = '1s';
            SET LOCAL statement_timeout = '5s';
            LOCK TABLE public.memory_chunks IN ACCESS EXCLUSIVE MODE;
            ALTER TABLE public.memory_chunks
                ALTER COLUMN retrieval_commit_watermark SET NOT NULL;
            ALTER TABLE public.memory_chunks ALTER COLUMN retrieval_commit_watermark
                SET DEFAULT nextval('public.memory_locator_commit_watermark_seq');
            ALTER TABLE public.memory_chunks
                DROP CONSTRAINT ck_memory_chunks_locator_watermark_present;
            DROP TRIGGER trg_memory_chunk_locator_watermark_mirror_v1
                ON public.memory_chunks;
            CREATE OR REPLACE FUNCTION public.memory_chunk_locator_watermark_mirror_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                NEW.retrieval_commit_watermark := CASE
                    WHEN TG_OP = 'INSERT'
                         OR NEW.retrieval_version IS DISTINCT FROM OLD.retrieval_version
                        THEN nextval('public.memory_locator_commit_watermark_seq')
                    ELSE OLD.retrieval_commit_watermark
                END;
                RETURN NEW;
            END $$;
            CREATE TRIGGER trg_zz_memory_chunk_locator_watermark_bridge_v1
                BEFORE INSERT OR UPDATE ON public.memory_chunks FOR EACH ROW
                EXECUTE FUNCTION public.memory_chunk_locator_watermark_mirror_v1();
            """
            + restore_guards
            + """
            """,
        )


async def _stage_receipt_canonical_job_index(
    connection: AsyncConnection, *, shadow: str
) -> None:
    """Build the shadow-column replacement for the published unique constraint."""

    await _execute_script(
        connection,
        f"DROP INDEX CONCURRENTLY IF EXISTS public.{_RECEIPT_CANONICAL_JOB_STAGE_INDEX}",
    )
    await _execute_script(
        connection,
        f"""
        CREATE UNIQUE INDEX CONCURRENTLY {_RECEIPT_CANONICAL_JOB_STAGE_INDEX}
        ON public.memory_projection_result_receipts (
            run_id_sha256, context_sha256, lane, operation,
            aggregate_type, aggregate_id, {shadow}
        ) NULLS NOT DISTINCT
        """,
    )


async def _table_exists(connection: AsyncConnection, table: str) -> bool:
    return bool(
        await connection.scalar(
            text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{table}"}
        )
    )


async def _column_type(connection: AsyncConnection, table: str, column: str) -> str | None:
    value = await connection.scalar(
        text(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :table AND column_name = :column
            """
        ),
        {"table": table, "column": column},
    )
    return str(value) if value is not None else None


async def _column_names(
    connection: AsyncConnection, table: str, *, excluded: frozenset[str]
) -> tuple[str, ...]:
    rows = (
        await connection.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table
                ORDER BY ordinal_position
                """
            ),
            {"table": table},
        )
    ).scalars()
    return tuple(str(column) for column in rows if str(column) not in excluded)


def _render_guard_triggers(
    *,
    table: str,
    columns: tuple[str, ...],
    triggers: tuple[tuple[str, str, bool, str | None], ...],
    update_only: bool,
) -> str:
    """Keep canonical guards active while excluding migration-only updates."""

    update_event = "UPDATE OF " + ", ".join(_quote_identifier(item) for item in columns)
    if not update_only:
        update_event = "UPDATE"
    statements: list[str] = []
    for name, function, includes_delete, condition in triggers:
        events = f"INSERT OR {update_event}"
        if includes_delete:
            events += " OR DELETE"
        when = f" WHEN ({condition})" if condition is not None else ""
        statements.append(
            f"DROP TRIGGER IF EXISTS {_quote_identifier(name)} ON public.{table};\n"
            f"CREATE TRIGGER {_quote_identifier(name)} BEFORE {events} ON public.{table}\n"
            f"FOR EACH ROW{when} EXECUTE FUNCTION public.{function}();"
        )
    return "\n".join(statements)


def _render_drop_triggers(
    *, table: str, triggers: tuple[tuple[str, str, bool, str | None], ...]
) -> str:
    return "\n".join(
        f"DROP TRIGGER IF EXISTS {_quote_identifier(name)} ON public.{table};"
        for name, _function, _includes_delete, _condition in triggers
    )


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


async def _execute_script(connection: AsyncConnection, sql: str) -> None:
    raw_connection = await connection.get_raw_connection()
    await raw_connection.driver_connection.execute(sql)


__all__ = ("STAGED_MIGRATION_IDS", "apply_staged_locator_migration")
