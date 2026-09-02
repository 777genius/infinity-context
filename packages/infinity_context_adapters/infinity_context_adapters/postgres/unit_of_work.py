"""Postgres unit of work and engine helpers."""

from __future__ import annotations

import json
from types import TracebackType

from infinity_context_core.domain.entities import SourceRef
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.features.memory_facts.public import (
    MemoryFactIdPort,
    ReviewedFactMutationExecutor,
)
from infinity_context_core.ports.clock import ClockPort
from sqlalchemy import JSON, bindparam, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactTransaction,
)
from infinity_context_adapters.postgres.asset_repositories import (
    PostgresAssetExtractionRepository,
    PostgresAssetRepository,
    PostgresContextLinkRepository,
    PostgresContextLinkSuggestionRepository,
)
from infinity_context_adapters.postgres.benchmark_projection_schema import (
    ensure_benchmark_projection_manifest_schema,
)
from infinity_context_adapters.postgres.benchmark_run_repositories import (
    PostgresBenchmarkRunRepository,
)
from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_WRITER_FENCE_CONSTRAINT as _BENCHMARK_WRITER_FENCE_CONSTRAINT,
)
from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_WRITER_FENCE_SQLSTATE as _BENCHMARK_WRITER_FENCE_SQLSTATE,
)
from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_WRITER_FENCE_STATEMENTS,
)
from infinity_context_adapters.postgres.canonical_keyword_trigram import (
    ensure_canonical_keyword_trigram_access_path,
)
from infinity_context_adapters.postgres.document_source_ref_coordination import (
    coordinate_document_source_ref_write,
)
from infinity_context_adapters.postgres.fact_repositories import (
    PostgresFactRelationRepository,
    PostgresFactRepository,
)
from infinity_context_adapters.postgres.record_repositories import (
    PostgresIdempotencyRepository,
    PostgresOutbox,
)
from infinity_context_adapters.postgres.repositories import (
    PostgresAnchorRepository,
    PostgresCaptureRepository,
    PostgresChunkRepository,
    PostgresDocumentRepository,
    PostgresEpisodeRepository,
    PostgresSuggestionRepository,
)
from infinity_context_adapters.postgres.retrieval_schema_singletons import (
    seed_retrieval_schema_singletons,
)
from infinity_context_adapters.postgres.schema_registry import load_schema_metadata
from infinity_context_adapters.postgres.scope_repositories import PostgresScopeRepository
from infinity_context_adapters.postgres.suggestion_resolution_receipts import (
    PostgresSuggestionResolutionReceiptRepository,
)
from infinity_context_adapters.postgres.usage_repositories import PostgresUsageRepository
from infinity_context_adapters.postgres.user_repositories import PostgresUserRepository

_BENCHMARK_WRITER_FENCE_MESSAGE = "Benchmark canonical write conflicted with cleanup in progress"


def _is_benchmark_writer_fence_error(exc: IntegrityError) -> bool:
    """Match only the stable Postgres trigger identity, including wrapped drivers."""

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        diagnostics = getattr(current, "diag", None)
        sqlstate = getattr(current, "sqlstate", None) or getattr(
            current,
            "pgcode",
            None,
        )
        constraint = getattr(current, "constraint_name", None) or getattr(
            diagnostics,
            "constraint_name",
            None,
        )
        if (
            sqlstate == _BENCHMARK_WRITER_FENCE_SQLSTATE
            and constraint == _BENCHMARK_WRITER_FENCE_CONSTRAINT
        ):
            return True
        for nested in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def build_async_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


_ADDITIVE_SCHEMA_COLUMNS = {
    "memory_service_tokens": (
        ("memory_scope_ids_json", "JSON"),
        ("repository_id", "VARCHAR(80)"),
        ("code_scope_id", "VARCHAR(96)"),
        ("permissions_json", "JSON"),
        ("last_used_at", "TIMESTAMPTZ"),
        ("expires_at", "TIMESTAMPTZ"),
    ),
    "memory_facts": (
        ("classification", "VARCHAR(40) NOT NULL DEFAULT 'internal'"),
        ("category", "VARCHAR(80)"),
        ("tags_json", "JSON NOT NULL DEFAULT '[]'"),
        ("ttl_policy", "VARCHAR(80)"),
        ("expires_at", "TIMESTAMPTZ"),
        ("temporal_kind", "VARCHAR(20) NOT NULL DEFAULT 'state'"),
        ("observed_at", "TIMESTAMPTZ"),
        ("valid_from", "TIMESTAMPTZ"),
        ("valid_to", "TIMESTAMPTZ"),
        ("occurred_from", "TIMESTAMPTZ"),
        ("occurred_to", "TIMESTAMPTZ"),
        ("temporal_basis", "VARCHAR(80) NOT NULL DEFAULT 'migrated_legacy'"),
        ("temporal_precision", "VARCHAR(40) NOT NULL DEFAULT 'unknown'"),
        ("last_confirmed_at", "TIMESTAMPTZ"),
        ("confirmation_basis", "VARCHAR(120)"),
        ("purge_after", "TIMESTAMPTZ"),
        ("epistemic_mode", "VARCHAR(40) NOT NULL DEFAULT 'world_claim'"),
        ("asserted_by", "VARCHAR(160)"),
        ("perspective_subject", "VARCHAR(160)"),
        ("repository_id", "VARCHAR(80)"),
        ("code_scope_id", "VARCHAR(96)"),
    ),
    "memory_fact_versions": (("snapshot_json", "JSON NOT NULL DEFAULT '{}'"),),
    "memory_documents": (("classification", "VARCHAR(40) NOT NULL DEFAULT 'unknown'"),),
    "memory_chunks": (("classification", "VARCHAR(40) NOT NULL DEFAULT 'unknown'"),),
    "memory_outbox": (
        ("message_key", "VARCHAR(160)"),
        ("workload_class", "VARCHAR(80) NOT NULL DEFAULT 'projection'"),
        ("fairness_key", "VARCHAR(160)"),
        ("last_safe_diagnostic_code", "VARCHAR(120)"),
    ),
    "memory_suggestions": (
        ("operation", "VARCHAR(40) NOT NULL DEFAULT 'add'"),
        ("category", "VARCHAR(80)"),
        ("tags_json", "JSON NOT NULL DEFAULT '[]'"),
        ("ttl_policy", "VARCHAR(80)"),
        ("expires_at", "TIMESTAMPTZ"),
        ("expiry_reason", "VARCHAR(160)"),
        ("created_from_capture_id", "VARCHAR(80)"),
        ("candidate_fingerprint", "VARCHAR(80)"),
        ("review_payload_json", "JSON NOT NULL DEFAULT '{}'"),
        ("review_reason", "VARCHAR(320)"),
        ("reviewed_at", "TIMESTAMPTZ"),
    ),
    "memory_asset_extraction_jobs": (
        ("lease_owner", "VARCHAR(120)"),
        ("lease_expires_at", "TIMESTAMPTZ"),
        ("heartbeat_at", "TIMESTAMPTZ"),
        ("retry_after_at", "TIMESTAMPTZ"),
        ("cancellation_requested_at", "TIMESTAMPTZ"),
        ("retry_disposition", "VARCHAR(40)"),
    ),
    "memory_fact_relations": (
        ("thread_id", "VARCHAR(80)"),
        ("observed_at", "TIMESTAMPTZ"),
        ("valid_from", "TIMESTAMPTZ"),
        ("valid_to", "TIMESTAMPTZ"),
        ("source_fact_version", "INTEGER"),
        ("target_fact_version", "INTEGER"),
        ("temporal_decision_id", "VARCHAR(80)"),
    ),
    "memory_anchors": (
        ("confidence", "VARCHAR(40) NOT NULL DEFAULT 'medium'"),
        ("evidence_refs_json", "JSON NOT NULL DEFAULT '[]'"),
        ("observed_at", "TIMESTAMPTZ"),
        ("valid_from", "TIMESTAMPTZ"),
        ("valid_to", "TIMESTAMPTZ"),
    ),
    "memory_source_refs": (
        ("page_number", "INTEGER"),
        ("time_start_ms", "INTEGER"),
        ("time_end_ms", "INTEGER"),
        ("bbox_json", "JSON"),
    ),
}

_LEGACY_PROFILE_ID_TABLES = (
    "memory_facts",
    "memory_threads",
    "memory_episodes",
    "memory_documents",
    "memory_chunks",
    "memory_fact_relations",
    "memory_suggestions",
    "memory_captures",
)


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _ensure_legacy_profile_schema(connection: Connection) -> None:
    """Upgrade pre-MemoryScope schemas in-place before SQLAlchemy creates tables."""

    table_names = set(inspect(connection).get_table_names())
    if "memory_profiles" in table_names:
        if "memory_scopes" not in table_names:
            connection.execute(text("ALTER TABLE memory_profiles RENAME TO memory_scopes"))
        else:
            legacy_to_current = _copy_legacy_profiles_to_memory_scopes(connection)
            _repoint_legacy_profile_references(connection, legacy_to_current)
            connection.execute(text("DROP TABLE memory_profiles"))

    table_names = set(inspect(connection).get_table_names())
    for table_name in _LEGACY_PROFILE_ID_TABLES:
        if table_name in table_names:
            _rename_or_backfill_legacy_column(
                connection,
                table_name=table_name,
                legacy_column="profile_id",
                current_column="memory_scope_id",
            )
    if "memory_service_tokens" in table_names:
        _rename_or_backfill_legacy_column(
            connection,
            table_name="memory_service_tokens",
            legacy_column="profile_ids_json",
            current_column="memory_scope_ids_json",
        )


def _copy_legacy_profiles_to_memory_scopes(connection: Connection) -> dict[str, str]:
    legacy_rows = list(
        connection.execute(
            text(
                """
                SELECT id, space_id, external_ref, name, status, created_at, updated_at
                FROM memory_profiles
                """
            )
        )
        .mappings()
        .all()
    )
    current_rows = list(
        connection.execute(text("SELECT id, space_id, external_ref FROM memory_scopes"))
        .mappings()
        .all()
    )
    current_ids = {str(row["id"]) for row in current_rows}
    current_by_ref = {
        (str(row["space_id"]), str(row["external_ref"])): str(row["id"]) for row in current_rows
    }
    legacy_to_current: dict[str, str] = {}

    insert_scope = text(
        """
        INSERT INTO memory_scopes (
            id,
            space_id,
            external_ref,
            name,
            status,
            created_at,
            updated_at
        )
        VALUES (
            :id,
            :space_id,
            :external_ref,
            :name,
            :status,
            :created_at,
            :updated_at
        )
        """
    )
    for legacy in legacy_rows:
        legacy_id = str(legacy["id"])
        ref_key = (str(legacy["space_id"]), str(legacy["external_ref"]))
        if legacy_id in current_ids:
            legacy_to_current[legacy_id] = legacy_id
            continue
        if ref_key in current_by_ref:
            legacy_to_current[legacy_id] = current_by_ref[ref_key]
            continue
        connection.execute(insert_scope, dict(legacy))
        current_ids.add(legacy_id)
        current_by_ref[ref_key] = legacy_id
        legacy_to_current[legacy_id] = legacy_id

    return legacy_to_current


def _repoint_legacy_profile_references(
    connection: Connection,
    legacy_to_current: dict[str, str],
) -> None:
    remapped_ids = {
        legacy_id: current_id
        for legacy_id, current_id in legacy_to_current.items()
        if legacy_id != current_id
    }
    if not remapped_ids:
        return

    table_names = set(inspect(connection).get_table_names())
    for table_name in _LEGACY_PROFILE_ID_TABLES:
        if table_name not in table_names:
            continue
        columns = _column_names(connection, table_name)
        for column_name in ("profile_id", "memory_scope_id"):
            if column_name not in columns:
                continue
            _repoint_scalar_scope_column(connection, table_name, column_name, remapped_ids)

    if "memory_service_tokens" in table_names:
        columns = _column_names(connection, "memory_service_tokens")
        for column_name in ("profile_ids_json", "memory_scope_ids_json"):
            if column_name in columns:
                _repoint_token_scope_json(connection, column_name, remapped_ids)


def _repoint_scalar_scope_column(
    connection: Connection,
    table_name: str,
    column_name: str,
    remapped_ids: dict[str, str],
) -> None:
    statement = text(
        f"""
        UPDATE {table_name}
        SET {column_name} = :current_id
        WHERE {column_name} = :legacy_id
        """
    )
    for legacy_id, current_id in remapped_ids.items():
        connection.execute(
            statement,
            {"legacy_id": legacy_id, "current_id": current_id},
        )


def _repoint_token_scope_json(
    connection: Connection,
    column_name: str,
    remapped_ids: dict[str, str],
) -> None:
    rows = connection.execute(
        text(f"SELECT id, {column_name} FROM memory_service_tokens WHERE {column_name} IS NOT NULL")
    )
    update_statement = text(
        f"""
        UPDATE memory_service_tokens
        SET {column_name} = :scope_ids
        WHERE id = :token_id
        """
    ).bindparams(bindparam("scope_ids", type_=JSON))
    for row in rows.mappings():
        scope_ids = _decode_json_string_list(row[column_name])
        remapped_scope_ids = [remapped_ids.get(scope_id, scope_id) for scope_id in scope_ids]
        if remapped_scope_ids != scope_ids:
            connection.execute(
                update_statement,
                {"token_id": row["id"], "scope_ids": remapped_scope_ids},
            )


def _decode_json_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _rename_or_backfill_legacy_column(
    connection: Connection,
    *,
    table_name: str,
    legacy_column: str,
    current_column: str,
) -> None:
    columns = _column_names(connection, table_name)
    if legacy_column not in columns:
        return
    if current_column not in columns:
        connection.execute(
            text(f"ALTER TABLE {table_name} RENAME COLUMN {legacy_column} TO {current_column}")
        )
        return
    connection.execute(
        text(
            f"""
            UPDATE {table_name}
            SET {current_column} = {legacy_column}
            WHERE {current_column} IS NULL
              AND {legacy_column} IS NOT NULL
            """
        )
    )


def _ensure_additive_schema_columns(connection: Connection) -> None:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    for table_name, columns in _ADDITIVE_SCHEMA_COLUMNS.items():
        if table_name not in table_names:
            continue
        existing_column_names = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, ddl in columns:
            if column_name not in existing_column_names:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
    if "memory_asset_extraction_jobs" in table_names:
        connection.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_asset_extraction_jobs_running_lease
                ON memory_asset_extraction_jobs(status, lease_expires_at, heartbeat_at)
                """
            )
        )


def _ensure_document_thread_unique_indexes(connection: Connection) -> None:
    inspector = inspect(connection)
    if "memory_documents" not in set(inspector.get_table_names()):
        return
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("ALTER TABLE memory_documents DROP CONSTRAINT IF EXISTS uq_document_source_hash")
        )
    elif connection.dialect.name == "sqlite":
        _rebuild_sqlite_memory_documents_without_legacy_unique(connection, inspector)
    connection.execute(text("DROP INDEX IF EXISTS uq_document_content_hash_profile_wide"))
    connection.execute(text("DROP INDEX IF EXISTS uq_document_source_hash_profile_wide"))
    connection.execute(text("DROP INDEX IF EXISTS uq_document_source_hash_memory_scope_wide"))
    connection.execute(text("DROP INDEX IF EXISTS uq_document_source_hash_thread"))
    connection.execute(text("DROP INDEX IF EXISTS uq_document_content_hash_memory_scope_wide"))
    connection.execute(text("DROP INDEX IF EXISTS uq_document_content_hash_thread"))
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_document_content_hash_memory_scope_wide
            ON memory_documents (
                space_id,
                memory_scope_id,
                content_hash
            )
            WHERE thread_id IS NULL AND status != 'deleted'
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_document_content_hash_thread
            ON memory_documents (
                space_id,
                memory_scope_id,
                thread_id,
                content_hash
            )
            WHERE thread_id IS NOT NULL AND status != 'deleted'
            """
        )
    )


def _rebuild_sqlite_memory_documents_without_legacy_unique(
    connection: Connection,
    inspector,
) -> None:
    legacy_columns = (
        "space_id",
        "memory_scope_id",
        "source_type",
        "source_external_id",
        "content_hash",
    )
    has_legacy_constraint = any(
        tuple(constraint.get("column_names") or ()) == legacy_columns
        for constraint in inspector.get_unique_constraints("memory_documents")
    ) or _sqlite_memory_documents_table_sql_has_legacy_unique(connection)
    if not has_legacy_constraint:
        return

    old_table = "_memory_documents_old_unique_rebuild"
    connection.execute(text(f"DROP TABLE IF EXISTS {old_table}"))
    connection.execute(text(f"ALTER TABLE memory_documents RENAME TO {old_table}"))
    connection.execute(
        text(
            """
            CREATE TABLE memory_documents (
                id VARCHAR(80) NOT NULL,
                space_id VARCHAR(80) NOT NULL,
                memory_scope_id VARCHAR(80) NOT NULL,
                thread_id VARCHAR(80),
                title VARCHAR(300) NOT NULL,
                source_type VARCHAR(80) NOT NULL,
                source_external_id VARCHAR(240) NOT NULL,
                content_hash VARCHAR(80) NOT NULL,
                classification VARCHAR(40) NOT NULL DEFAULT 'unknown',
                status VARCHAR(40) NOT NULL DEFAULT 'active',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id)
            )
            """
        )
    )
    connection.execute(
        text(
            f"""
            INSERT INTO memory_documents (
                id,
                space_id,
                memory_scope_id,
                thread_id,
                title,
                source_type,
                source_external_id,
                content_hash,
                classification,
                status,
                created_at,
                updated_at
            )
            SELECT
                id,
                space_id,
                memory_scope_id,
                thread_id,
                title,
                source_type,
                source_external_id,
                content_hash,
                classification,
                status,
                created_at,
                updated_at
            FROM {old_table}
            """
        )
    )
    connection.execute(text(f"DROP TABLE {old_table}"))


def _sqlite_memory_documents_table_sql_has_legacy_unique(connection: Connection) -> bool:
    table_sql = connection.execute(
        text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'memory_documents'")
    ).scalar_one_or_none()
    if not table_sql:
        return False
    normalized = " ".join(str(table_sql).lower().replace('"', "").split())
    return (
        "constraint uq_document_source_hash unique" in normalized
        or "unique ( space_id, memory_scope_id, source_type, source_external_id, content_hash )"
        in normalized
        or "unique (space_id, memory_scope_id, source_type, source_external_id, content_hash)"
        in normalized
    )


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


class PostgresUnitOfWork:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: ClockPort,
        memory_fact_ids: MemoryFactIdPort | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._memory_fact_ids = memory_fact_ids
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> PostgresUnitOfWork:
        self._session = self._session_factory()
        self.benchmark_runs = PostgresBenchmarkRunRepository(self._session)
        now = self._clock.now()
        self.scope = PostgresScopeRepository(self._session)
        self.users = PostgresUserRepository(self._session)
        self.facts = PostgresFactRepository(self._session, now=now)
        self.fact_relations = PostgresFactRelationRepository(self._session)
        self.assets = PostgresAssetRepository(self._session)
        self.asset_extractions = PostgresAssetExtractionRepository(self._session)
        self.context_links = PostgresContextLinkRepository(self._session)
        self.context_link_suggestions = PostgresContextLinkSuggestionRepository(self._session)
        self.anchors = PostgresAnchorRepository(self._session)
        self.episodes = PostgresEpisodeRepository(self._session)
        self.documents = PostgresDocumentRepository(self._session)
        self.chunks = PostgresChunkRepository(self._session)
        self.captures = PostgresCaptureRepository(self._session)
        self.suggestions = PostgresSuggestionRepository(self._session)
        self.suggestion_resolution_receipts = PostgresSuggestionResolutionReceiptRepository(
            self._session
        )
        self.usage = PostgresUsageRepository(self._session)
        self.idempotency = PostgresIdempotencyRepository(self._session, now=now)
        self.outbox = PostgresOutbox(self._session, now=now)
        if self._memory_fact_ids is not None:
            memory_fact_transaction = PostgresMemoryFactTransaction(self._session, now=now)
            self.reviewed_facts = ReviewedFactMutationExecutor(
                transaction=memory_fact_transaction,
                clock=self._clock,
                ids=self._memory_fact_ids,
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        integrity_error = exc if isinstance(exc, IntegrityError) else None
        if exc_type is not None or not self._committed:
            await self._session.rollback()
        await self._session.close()
        self._session = None
        self._committed = False
        if integrity_error is not None:
            message = (
                _BENCHMARK_WRITER_FENCE_MESSAGE
                if _is_benchmark_writer_fence_error(integrity_error)
                else "Canonical write conflicted with existing data"
            )
            raise MemoryConflictError(message) from integrity_error

    async def commit(self) -> None:
        if self._session is None:
            msg = "UnitOfWork is not open"
            raise RuntimeError(msg)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _is_benchmark_writer_fence_error(exc):
                raise MemoryConflictError(_BENCHMARK_WRITER_FENCE_MESSAGE) from exc
            raise MemoryConflictError("Canonical write conflicted with existing data") from exc
        self._committed = True

    async def coordinate_fact_source_refs(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        source_refs: tuple[SourceRef, ...],
    ) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork is not open")
        await coordinate_document_source_ref_write(
            self._session,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            source_refs=source_refs,
        )

    async def rollback(self) -> None:
        if self._session is None:
            return
        await self._session.rollback()
        self._committed = False


class PostgresUnitOfWorkFactory:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: ClockPort,
        memory_fact_ids: MemoryFactIdPort | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._memory_fact_ids = memory_fact_ids

    def __call__(self) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(
            session_factory=self._session_factory,
            clock=self._clock,
            memory_fact_ids=self._memory_fact_ids,
        )
