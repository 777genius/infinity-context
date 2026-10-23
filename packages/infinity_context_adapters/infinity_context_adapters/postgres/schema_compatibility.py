"""Compatibility upgrades for unversioned canonical database schemas."""

from __future__ import annotations

import json

from sqlalchemy import JSON, bindparam, inspect, text
from sqlalchemy.engine import Connection

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
        ("claim_token", "VARCHAR(32)"),
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
