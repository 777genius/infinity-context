"""Canonical schema bootstrap, separate from transaction/session ownership."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from infinity_context_adapters.postgres.benchmark_projection_schema import (
    ensure_benchmark_projection_manifest_schema,
)
from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_WRITER_FENCE_STATEMENTS,
)
from infinity_context_adapters.postgres.canonical_keyword_trigram import (
    ensure_canonical_keyword_trigram_access_path,
)
from infinity_context_adapters.postgres.retrieval_schema_singletons import (
    seed_retrieval_schema_singletons,
)
from infinity_context_adapters.postgres.schema_compatibility import (
    _column_names,
    _ensure_additive_schema_columns,
    _ensure_document_thread_unique_indexes,
    _ensure_legacy_profile_schema,
)
from infinity_context_adapters.postgres.schema_registry import load_schema_metadata


async def create_schema(engine: AsyncEngine) -> None:
    if engine.dialect.name == "postgresql":
        from infinity_context_adapters.postgres.migration_runner import upgrade_schema

        await upgrade_schema(engine)
        return
    async with engine.begin() as connection:
        await connection.run_sync(_ensure_runtime_schema)


def _ensure_runtime_schema(connection: Connection) -> None:
    """Bring an unversioned legacy schema to the forward-migration baseline."""

    _ensure_legacy_profile_schema(connection)
    load_schema_metadata().create_all(connection)
    seed_retrieval_schema_singletons(connection)
    ensure_benchmark_projection_manifest_schema(connection)
    _ensure_additive_schema_columns(connection)
    _backfill_memory_fact_temporal_columns(connection)
    _ensure_memory_fact_temporal_indexes(connection)
    _ensure_memory_fact_code_scope_indexes(connection)
    _ensure_memory_fact_supersession_indexes(connection)
    _ensure_document_thread_unique_indexes(connection)
    _ensure_outbox_lifecycle_indexes(connection)
    _ensure_capture_indexes(connection)
    _ensure_suggestion_metadata_indexes(connection)
    ensure_canonical_keyword_trigram_access_path(connection)
    _ensure_managed_benchmark_writer_fence(connection)


def _backfill_memory_fact_temporal_columns(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_facts" not in set(inspector.get_table_names()):
        return
    columns = _column_names(connection, "memory_facts")
    if {"observed_at", "created_at"} <= columns:
        connection.execute(
            text(
                """
                UPDATE memory_facts
                SET observed_at = created_at
                WHERE observed_at IS NULL
                """
            )
        )
    if {"temporal_kind", "temporal_basis", "valid_from", "created_at"} <= columns:
        connection.execute(
            text(
                """
                UPDATE memory_facts
                SET valid_from = created_at
                WHERE temporal_kind = 'state'
                  AND temporal_basis = 'migrated_legacy'
                  AND valid_from IS NULL
                """
            )
        )


def _ensure_memory_fact_temporal_indexes(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_facts" not in set(inspector.get_table_names()):
        return
    columns = _column_names(connection, "memory_facts")
    required = {"space_id", "memory_scope_id", "status", "temporal_kind", "valid_from", "valid_to"}
    if not required <= columns:
        return
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_memory_facts_temporal_selection
            ON memory_facts (
                space_id,
                memory_scope_id,
                status,
                temporal_kind,
                valid_from,
                valid_to
            )
            """
        )
    )


def _ensure_memory_fact_supersession_indexes(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_fact_relations" not in set(inspector.get_table_names()):
        return
    columns = _column_names(connection, "memory_fact_relations")
    required = {"target_fact_id", "relation_type", "status", "temporal_decision_id"}
    if not required <= columns:
        return
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_fact_single_active_supersession
            ON memory_fact_relations(target_fact_id)
            WHERE relation_type = 'supersedes'
              AND status = 'active'
              AND temporal_decision_id IS NOT NULL
            """
        )
    )


def _ensure_memory_fact_code_scope_indexes(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_facts" not in set(inspector.get_table_names()):
        return
    columns = _column_names(connection, "memory_facts")
    required = {
        "space_id",
        "memory_scope_id",
        "repository_id",
        "code_scope_id",
        "status",
    }
    if not required <= columns:
        return
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_memory_facts_code_scope
            ON memory_facts (
                space_id,
                memory_scope_id,
                repository_id,
                code_scope_id,
                status
            )
            """
        )
    )


def _ensure_managed_benchmark_writer_fence(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    for statement in BENCHMARK_WRITER_FENCE_STATEMENTS:
        connection.execute(text(statement))


def _ensure_outbox_lifecycle_indexes(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_outbox" not in set(inspector.get_table_names()):
        return
    connection.execute(
        text(
            """
            UPDATE memory_outbox
            SET fairness_key = aggregate_type || ':' || aggregate_id
            WHERE fairness_key IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_outbox_message_key
            ON memory_outbox(message_key)
            WHERE message_key IS NOT NULL
            """
        )
    )


def _ensure_capture_indexes(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_captures" not in set(inspector.get_table_names()):
        return
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_capture_idempotency
            ON memory_captures(space_id, idempotency_key)
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_memory_captures_consolidation
            ON memory_captures(space_id, memory_scope_id, consolidation_status, created_at)
            """
        )
    )


def _ensure_suggestion_metadata_indexes(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_suggestions" not in set(inspector.get_table_names()):
        return
    _expire_duplicate_pending_suggestions_before_unique_indexes(connection)
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_memory_suggestions_expiry
            ON memory_suggestions(space_id, memory_scope_id, status, expires_at)
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_suggestion_fingerprint_no_target
            ON memory_suggestions(space_id, memory_scope_id, operation, candidate_fingerprint)
            WHERE status = 'pending'
              AND candidate_fingerprint IS NOT NULL
              AND target_fact_id IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_suggestion_fingerprint_target
            ON memory_suggestions(
                space_id,
                memory_scope_id,
                operation,
                target_fact_id,
                candidate_fingerprint
            )
            WHERE status = 'pending'
              AND candidate_fingerprint IS NOT NULL
              AND target_fact_id IS NOT NULL
            """
        )
    )


def _expire_duplicate_pending_suggestions_before_unique_indexes(connection: Connection) -> None:
    connection.execute(
        text(
            """
            UPDATE memory_suggestions
            SET
                status = 'expired',
                updated_at = CURRENT_TIMESTAMP,
                reviewed_at = COALESCE(reviewed_at, CURRENT_TIMESTAMP),
                review_reason = COALESCE(review_reason, 'deduped_by_schema_upgrade')
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY
                                space_id,
                                memory_scope_id,
                                operation,
                                target_fact_id,
                                candidate_fingerprint
                            ORDER BY updated_at DESC, created_at DESC, id DESC
                        ) AS duplicate_rank
                    FROM memory_suggestions
                    WHERE status = 'pending'
                      AND candidate_fingerprint IS NOT NULL
                ) ranked
                WHERE duplicate_rank > 1
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_memory_outbox_workload_fairness
            ON memory_outbox(status, workload_class, fairness_key, next_attempt_at)
            """
        )
    )
