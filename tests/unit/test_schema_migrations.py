import asyncio
from pathlib import Path

from infinity_context_adapters.postgres import build_async_engine, create_schema
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

_MIGRATIONS = (
    Path(__file__).resolve().parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
)


def test_temporal_sql_migration_declares_thread_scope_key_once_per_table() -> None:
    sql = (_MIGRATIONS / "0023_memory_fact_temporal_architecture.sql").read_text(encoding="utf-8")

    def create_table_body(table_name: str) -> str:
        start = sql.index(f"CREATE TABLE IF NOT EXISTS {table_name} (")
        return sql[start : sql.index("\n);", start)]

    receipt_body = create_table_body("memory_fact_operation_receipts")
    decision_body = create_table_body("memory_fact_temporal_decisions")

    assert receipt_body.count("thread_scope_key VARCHAR(87) NOT NULL") == 1
    assert decision_body.count("thread_scope_key VARCHAR(87) NOT NULL") == 1
    assert (
        "UNIQUE (\n      space_id,\n      memory_scope_id,\n      thread_scope_key" in receipt_body
    )
    assert (
        "UNIQUE (\n      space_id,\n      memory_scope_id,\n      thread_scope_key" in decision_body
    )


def test_repository_integrity_migration_fails_closed_and_adds_composite_fks() -> None:
    sql = (_MIGRATIONS / "0027_review_replay_and_repository_integrity.sql").read_text(
        encoding="utf-8"
    )

    assert "repository integrity preflight failed" in sql
    assert "FOREIGN KEY (repository_id, space_id)" in sql
    assert "fk_memory_facts_repository_space" in sql
    assert "fk_memory_service_tokens_repository_space" in sql
    assert "suggestion_resolution_receipts" in sql


def test_dynamic_code_scope_migration_uses_server_owned_repository_allowlist() -> None:
    sql = (_MIGRATIONS / "0028_code_scope_authorizations.sql").read_text(encoding="utf-8")

    assert "code_scope_authorizations" in sql
    assert "FOREIGN KEY (repository_id, space_id)" in sql
    assert "UNIQUE (repository_id, code_scope_id)" in sql
    assert "code-scope-v1-[0-9a-f]{64}" in sql


def test_schema_parity_migration_binds_relations_to_exact_temporal_decisions() -> None:
    sql = (_MIGRATIONS / "0029_schema_parity_and_fact_tenant_integrity.sql").read_text(
        encoding="utf-8"
    )

    assert "uq_memory_fact_temporal_decision_relation_identity" in sql
    assert "fk_memory_fact_relation_temporal_decision_identity" in sql
    assert "decision.thread_id IS DISTINCT FROM relation.thread_id" in sql
    assert "decision.effective_at IS DISTINCT FROM relation.valid_from" in sql


def test_suggestion_receipt_migration_binds_exact_result_to_tenant_and_decision() -> None:
    sql = (_MIGRATIONS / "0030_suggestion_receipt_tenant_integrity.sql").read_text(encoding="utf-8")

    assert "suggestion receipt tenant integrity preflight failed" in sql
    assert "fk_suggestion_resolution_receipt_suggestion_scope" in sql
    assert "fk_suggestion_resolution_receipt_fact_scope" in sql
    assert "fk_suggestion_resolution_receipt_fact_version" in sql
    assert "fk_suggestion_resolution_receipt_decision_scope" in sql
    assert "fk_suggestion_resolution_receipt_relation_decision" in sql
    assert "relation_id IS NULL OR temporal_decision_id IS NOT NULL" in sql
    assert "trg_suggestion_resolution_receipt_compatibility_fields" in sql


def test_append_only_receipt_snapshot_migration_normalizes_and_validates_identity() -> None:
    sql = (_MIGRATIONS / "0031_receipt_snapshot_identity.sql").read_text(encoding="utf-8")

    assert "jsonb_typeof(result_fact_json) = 'null'" in sql
    assert "SET result_fact_json = NULL" in sql
    assert "fact operation receipt snapshot identity preflight failed" in sql
    assert "trg_memory_fact_operation_receipt_snapshot_identity" in sql
    assert "suggestion receipt snapshot identity preflight failed" in sql
    assert "suggestion receipt fact snapshot identity preflight failed" in sql
    assert "ck_suggestion_resolution_receipt_suggestion_snapshot_identity" in sql
    assert "ck_suggestion_resolution_receipt_fact_snapshot_identity" in sql


def test_create_schema_adds_classification_to_existing_memory_tables(tmp_path: Path) -> None:
    async def run() -> dict[str, dict[str, object]]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old-schema.db'}")
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_service_tokens (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80),
                            description VARCHAR(240) NOT NULL,
                            token_hash VARCHAR(80) UNIQUE NOT NULL,
                            status VARCHAR(40) NOT NULL DEFAULT 'active',
                            created_at DATETIME NOT NULL,
                            revoked_at DATETIME
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_facts (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            memory_scope_id VARCHAR(80) NOT NULL,
                            thread_id VARCHAR(80),
                            kind VARCHAR(80) NOT NULL,
                            text TEXT NOT NULL,
                            status VARCHAR(40) NOT NULL,
                            confidence VARCHAR(40) NOT NULL,
                            trust_level VARCHAR(40) NOT NULL,
                            version INTEGER NOT NULL,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_facts (
                            id,
                            space_id,
                            memory_scope_id,
                            thread_id,
                            kind,
                            text,
                            status,
                            confidence,
                            trust_level,
                            version,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            'fact_legacy',
                            'space_1',
                            'scope_1',
                            NULL,
                            'note',
                            'Legacy fact remains visible.',
                            'active',
                            'medium',
                            'medium',
                            1,
                            '2026-05-25T10:00:00+00:00',
                            '2026-05-25T10:00:00+00:00'
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_documents (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            memory_scope_id VARCHAR(80) NOT NULL,
                            thread_id VARCHAR(80),
                            title VARCHAR(300) NOT NULL,
                            source_type VARCHAR(80) NOT NULL,
                            source_external_id VARCHAR(240) NOT NULL,
                            content_hash VARCHAR(80) NOT NULL,
                            status VARCHAR(40) NOT NULL DEFAULT 'active',
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_chunks (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            memory_scope_id VARCHAR(80) NOT NULL,
                            thread_id VARCHAR(80),
                            document_id VARCHAR(80),
                            episode_id VARCHAR(80),
                            source_type VARCHAR(80) NOT NULL,
                            source_external_id VARCHAR(240) NOT NULL,
                            source_hash VARCHAR(80) NOT NULL,
                            kind VARCHAR(80) NOT NULL,
                            text TEXT NOT NULL,
                            normalized_text TEXT NOT NULL,
                            status VARCHAR(40) NOT NULL DEFAULT 'active',
                            sequence INTEGER NOT NULL,
                            char_start INTEGER NOT NULL,
                            char_end INTEGER NOT NULL,
                            token_estimate INTEGER NOT NULL,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            metadata_json JSON NOT NULL
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_fact_relations (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            memory_scope_id VARCHAR(80) NOT NULL,
                            source_fact_id VARCHAR(80) NOT NULL,
                            target_fact_id VARCHAR(80) NOT NULL,
                            relation_type VARCHAR(80) NOT NULL,
                            reason VARCHAR(320) NOT NULL,
                            status VARCHAR(40) NOT NULL DEFAULT 'active',
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_fact_relations (
                            id,
                            space_id,
                            memory_scope_id,
                            source_fact_id,
                            target_fact_id,
                            relation_type,
                            reason,
                            status,
                            created_at,
                            updated_at
                        )
                        VALUES
                            (
                                'legacy_supersession_a',
                                'space_1',
                                'scope_1',
                                'legacy_successor_a',
                                'legacy_target',
                                'supersedes',
                                'legacy relation',
                                'active',
                                '2026-05-25T10:00:00+00:00',
                                '2026-05-25T10:00:00+00:00'
                            ),
                            (
                                'legacy_supersession_b',
                                'space_1',
                                'scope_1',
                                'legacy_successor_b',
                                'legacy_target',
                                'supersedes',
                                'legacy duplicate',
                                'active',
                                '2026-05-25T10:00:00+00:00',
                                '2026-05-25T10:00:00+00:00'
                            )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_source_refs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            fact_id VARCHAR(80) NOT NULL,
                            fact_version INTEGER NOT NULL,
                            source_type VARCHAR(80) NOT NULL,
                            source_id VARCHAR(160) NOT NULL,
                            chunk_id VARCHAR(160),
                            char_start INTEGER,
                            char_end INTEGER,
                            quote_preview VARCHAR(240)
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_source_refs (
                            fact_id,
                            fact_version,
                            source_type,
                            source_id,
                            chunk_id,
                            char_start,
                            char_end,
                            quote_preview
                        )
                        VALUES (
                            'fact_legacy',
                            1,
                            'manual',
                            'legacy-source',
                            NULL,
                            NULL,
                            NULL,
                            NULL
                        )
                        """
                    )
                )

            await create_schema(engine)

            def get_additive_columns(connection) -> dict[str, dict[str, object]]:
                inspector = inspect(connection)
                classification_columns = {
                    table_name: {
                        column["name"]: column
                        for column in inspector.get_columns(table_name)
                        if column["name"] == "classification"
                    }
                    for table_name in ("memory_facts", "memory_documents", "memory_chunks")
                }
                token_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("memory_service_tokens")
                    if column["name"]
                    in {"memory_scope_ids_json", "permissions_json", "last_used_at", "expires_at"}
                }
                fact_taxonomy_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("memory_facts")
                    if column["name"] in {"category", "tags_json", "ttl_policy", "expires_at"}
                }
                fact_temporal_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("memory_facts")
                    if column["name"]
                    in {
                        "temporal_kind",
                        "observed_at",
                        "valid_from",
                        "valid_to",
                        "occurred_from",
                        "occurred_to",
                        "temporal_basis",
                        "temporal_precision",
                        "last_confirmed_at",
                        "confirmation_basis",
                        "purge_after",
                        "epistemic_mode",
                        "asserted_by",
                        "perspective_subject",
                    }
                }
                fact_version_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("memory_fact_versions")
                    if column["name"] == "snapshot_json"
                }
                fact_code_scope_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("memory_facts")
                    if column["name"] in {"repository_id", "code_scope_id"}
                }
                outbox_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("memory_outbox")
                    if column["name"] == "message_key"
                }
                fact_relation_temporal_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("memory_fact_relations")
                    if column["name"]
                    in {
                        "thread_id",
                        "observed_at",
                        "valid_from",
                        "valid_to",
                        "source_fact_version",
                        "target_fact_version",
                        "temporal_decision_id",
                    }
                }
                temporal_decision_columns = {
                    column["name"]
                    for column in inspector.get_columns("memory_fact_temporal_decisions")
                }
                relation_indexes = {
                    index["name"] for index in inspector.get_indexes("memory_fact_relations")
                }
                temporal_decision_indexes = {
                    index["name"]
                    for index in inspector.get_indexes("memory_fact_temporal_decisions")
                }
                source_ref_multimodal_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("memory_source_refs")
                    if column["name"]
                    in {"page_number", "time_start_ms", "time_end_ms", "bbox_json"}
                }
                document_indexes = {
                    index["name"]: index for index in inspector.get_indexes("memory_documents")
                }
                source_ref_count = connection.execute(
                    text("SELECT COUNT(*) FROM memory_source_refs WHERE fact_id = 'fact_legacy'")
                ).scalar_one()
                legacy_temporal = connection.execute(
                    text(
                        """
                        SELECT observed_at, valid_from, temporal_basis
                        FROM memory_facts
                        WHERE id = 'fact_legacy'
                        """
                    )
                ).one()
                return {
                    **classification_columns,
                    "memory_fact_taxonomy": fact_taxonomy_columns,
                    "memory_fact_temporal": fact_temporal_columns,
                    "memory_fact_versions": fact_version_columns,
                    "memory_fact_code_scope": fact_code_scope_columns,
                    "memory_outbox": outbox_columns,
                    "memory_fact_relation_temporal": fact_relation_temporal_columns,
                    "memory_fact_temporal_decisions": temporal_decision_columns,
                    "memory_fact_relation_indexes": relation_indexes,
                    "memory_fact_temporal_decision_indexes": temporal_decision_indexes,
                    "memory_source_ref_multimodal": source_ref_multimodal_columns,
                    "memory_source_ref_count": source_ref_count,
                    "memory_fact_legacy_temporal": tuple(legacy_temporal),
                    "memory_service_tokens": token_columns,
                    "memory_document_indexes": document_indexes,
                }

            async with engine.connect() as connection:
                return await connection.run_sync(get_additive_columns)
        finally:
            await engine.dispose()

    columns = asyncio.run(run())

    assert columns["memory_facts"]["classification"]["nullable"] is False
    assert columns["memory_documents"]["classification"]["nullable"] is False
    assert columns["memory_chunks"]["classification"]["nullable"] is False
    assert set(columns["memory_fact_taxonomy"]) == {
        "category",
        "tags_json",
        "ttl_policy",
        "expires_at",
    }
    assert set(columns["memory_fact_temporal"]) == {
        "temporal_kind",
        "observed_at",
        "valid_from",
        "valid_to",
        "occurred_from",
        "occurred_to",
        "temporal_basis",
        "temporal_precision",
        "last_confirmed_at",
        "confirmation_basis",
        "purge_after",
        "epistemic_mode",
        "asserted_by",
        "perspective_subject",
    }
    assert set(columns["memory_fact_versions"]) == {"snapshot_json"}
    assert set(columns["memory_fact_code_scope"]) == {
        "repository_id",
        "code_scope_id",
    }
    assert set(columns["memory_outbox"]) == {"message_key"}
    assert set(columns["memory_fact_relation_temporal"]) == {
        "thread_id",
        "observed_at",
        "valid_from",
        "valid_to",
        "source_fact_version",
        "target_fact_version",
        "temporal_decision_id",
    }
    assert {
        "id",
        "decision_type",
        "space_id",
        "memory_scope_id",
        "thread_id",
        "thread_scope_key",
        "source_fact_id",
        "source_fact_version",
        "target_fact_id",
        "target_fact_version",
        "effective_at",
        "evidence_refs_json",
        "actor_id",
        "policy_version",
        "reason_code",
        "applied_at",
        "idempotency_key",
        "compensates_decision_id",
    } <= columns["memory_fact_temporal_decisions"]
    assert "uq_memory_fact_single_active_supersession" in columns["memory_fact_relation_indexes"]
    assert (
        "uq_memory_fact_temporal_decision_compensation"
        in columns["memory_fact_temporal_decision_indexes"]
    )
    assert set(columns["memory_source_ref_multimodal"]) == {
        "page_number",
        "time_start_ms",
        "time_end_ms",
        "bbox_json",
    }
    assert columns["memory_source_ref_count"] == 1
    assert columns["memory_fact_legacy_temporal"][0] is not None
    assert columns["memory_fact_legacy_temporal"][0] == columns["memory_fact_legacy_temporal"][1]
    assert columns["memory_fact_legacy_temporal"][2] == "migrated_legacy"
    assert set(columns["memory_service_tokens"]) == {
        "memory_scope_ids_json",
        "permissions_json",
        "last_used_at",
        "expires_at",
    }
    assert "uq_document_content_hash_memory_scope_wide" in columns["memory_document_indexes"]
    assert "uq_document_content_hash_thread" in columns["memory_document_indexes"]


def test_create_schema_adds_capture_tables_and_suggestion_metadata(tmp_path: Path) -> None:
    async def run() -> dict[str, object]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'captures-schema.db'}")
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_suggestions (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            memory_scope_id VARCHAR(80) NOT NULL,
                            candidate_text TEXT NOT NULL,
                            kind VARCHAR(80) NOT NULL,
                            status VARCHAR(40) NOT NULL,
                            source_refs_json JSON NOT NULL,
                            confidence VARCHAR(40) NOT NULL,
                            trust_level VARCHAR(40) NOT NULL,
                            safe_reason VARCHAR(320) NOT NULL,
                            target_fact_id VARCHAR(80),
                            target_fact_version INTEGER,
                            review_reason VARCHAR(320),
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            reviewed_at DATETIME
                        )
                        """
                    )
                )

            await create_schema(engine)

            def inspect_schema(connection) -> dict[str, object]:
                inspector = inspect(connection)
                return {
                    "tables": set(inspector.get_table_names()),
                    "suggestion_columns": {
                        column["name"] for column in inspector.get_columns("memory_suggestions")
                    },
                    "capture_indexes": {
                        index["name"] for index in inspector.get_indexes("memory_captures")
                    },
                    "suggestion_indexes": {
                        index["name"] for index in inspector.get_indexes("memory_suggestions")
                    },
                }

            async with engine.connect() as connection:
                return await connection.run_sync(inspect_schema)
        finally:
            await engine.dispose()

    result = asyncio.run(run())

    assert "memory_captures" in result["tables"]
    assert {
        "operation",
        "category",
        "tags_json",
        "ttl_policy",
        "expires_at",
        "created_from_capture_id",
        "candidate_fingerprint",
        "review_payload_json",
    } <= result["suggestion_columns"]
    assert "ix_memory_captures_consolidation" in result["capture_indexes"]
    assert "ix_memory_suggestions_expiry" in result["suggestion_indexes"]
    assert "uq_pending_suggestion_fingerprint_no_target" in result["suggestion_indexes"]
    assert "uq_pending_suggestion_fingerprint_target" in result["suggestion_indexes"]


def test_create_schema_adds_asset_and_context_link_tables(tmp_path: Path) -> None:
    async def run() -> dict[str, object]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'asset-schema.db'}")
        try:
            await create_schema(engine)

            def inspect_schema(connection) -> dict[str, object]:
                inspector = inspect(connection)
                return {
                    "tables": set(inspector.get_table_names()),
                    "asset_indexes": {
                        index["name"] for index in inspector.get_indexes("memory_assets")
                    },
                    "asset_extraction_job_indexes": {
                        index["name"]
                        for index in inspector.get_indexes("memory_asset_extraction_jobs")
                    },
                    "asset_extraction_job_columns": {
                        column["name"]
                        for column in inspector.get_columns("memory_asset_extraction_jobs")
                    },
                    "asset_extraction_artifact_indexes": {
                        index["name"]
                        for index in inspector.get_indexes("memory_asset_extraction_artifacts")
                    },
                    "context_link_indexes": {
                        index["name"] for index in inspector.get_indexes("memory_context_links")
                    },
                    "context_link_suggestion_indexes": {
                        index["name"]
                        for index in inspector.get_indexes("memory_context_link_suggestions")
                    },
                    "anchor_indexes": {
                        index["name"] for index in inspector.get_indexes("memory_anchors")
                    },
                    "anchor_columns": {
                        column["name"] for column in inspector.get_columns("memory_anchors")
                    },
                    "usage_indexes": {
                        index["name"] for index in inspector.get_indexes("memory_usage_records")
                    },
                    "user_indexes": {
                        index["name"] for index in inspector.get_indexes("memory_users")
                    },
                    "space_membership_indexes": {
                        index["name"] for index in inspector.get_indexes("memory_space_memberships")
                    },
                }

            async with engine.connect() as connection:
                return await connection.run_sync(inspect_schema)
        finally:
            await engine.dispose()

    result = asyncio.run(run())

    assert "memory_assets" in result["tables"]
    assert "memory_asset_extraction_jobs" in result["tables"]
    assert "memory_asset_extraction_artifacts" in result["tables"]
    assert "memory_context_links" in result["tables"]
    assert "memory_context_link_suggestions" in result["tables"]
    assert "memory_anchors" in result["tables"]
    assert "memory_usage_records" in result["tables"]
    assert "memory_users" in result["tables"]
    assert "memory_space_memberships" in result["tables"]
    assert "ix_memory_assets_scope_status" in result["asset_indexes"]
    assert "ix_memory_assets_hash_scope" in result["asset_indexes"]
    assert "ix_asset_extraction_jobs_asset_status" in result["asset_extraction_job_indexes"]
    assert "ix_asset_extraction_jobs_scope_status" in result["asset_extraction_job_indexes"]
    assert "uq_asset_extraction_jobs_active_profile" in result["asset_extraction_job_indexes"]
    assert "ix_asset_extraction_jobs_running_lease" in result["asset_extraction_job_indexes"]
    assert {
        "lease_owner",
        "lease_expires_at",
        "heartbeat_at",
        "retry_after_at",
        "cancellation_requested_at",
        "retry_disposition",
    }.issubset(result["asset_extraction_job_columns"])
    assert "ix_asset_extraction_artifacts_job" in result["asset_extraction_artifact_indexes"]
    assert "ix_asset_extraction_artifacts_asset" in result["asset_extraction_artifact_indexes"]
    assert "uq_memory_context_link_active" in result["context_link_indexes"]
    assert "ix_memory_context_links_source" in result["context_link_indexes"]
    assert "uq_context_link_suggestion_pending" in result["context_link_suggestion_indexes"]
    assert "ix_context_link_suggestions_source" in result["context_link_suggestion_indexes"]
    assert "ix_context_link_suggestions_status" in result["context_link_suggestion_indexes"]
    assert "uq_memory_anchor_active_key" in result["anchor_indexes"]
    assert "ix_memory_anchors_scope_kind" in result["anchor_indexes"]
    assert {
        "confidence",
        "evidence_refs_json",
        "observed_at",
        "valid_from",
        "valid_to",
    }.issubset(result["anchor_columns"])
    assert "uq_memory_usage_idempotency" in result["usage_indexes"]
    assert "ix_memory_usage_subject_window" in result["usage_indexes"]
    assert "uq_memory_user_external_ref" in result["user_indexes"]
    assert "ix_memory_users_status" in result["user_indexes"]
    assert "uq_memory_space_membership_active_user" in result["space_membership_indexes"]
    assert "ix_memory_space_memberships_space" in result["space_membership_indexes"]
    assert "ix_memory_space_memberships_user" in result["space_membership_indexes"]


def test_create_schema_adds_anchor_evidence_columns_to_existing_table(
    tmp_path: Path,
) -> None:
    async def run() -> dict[str, object]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'anchor-upgrade.db'}")
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_anchors (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            memory_scope_id VARCHAR(80) NOT NULL,
                            kind VARCHAR(40) NOT NULL,
                            normalized_key VARCHAR(160) NOT NULL,
                            label VARCHAR(240) NOT NULL,
                            aliases_json JSON NOT NULL DEFAULT '[]',
                            description VARCHAR(500),
                            status VARCHAR(40) NOT NULL DEFAULT 'active',
                            metadata_json JSON NOT NULL DEFAULT '{}',
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_anchors (
                            id,
                            space_id,
                            memory_scope_id,
                            kind,
                            normalized_key,
                            label,
                            aliases_json,
                            status,
                            metadata_json,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            'anchor_1',
                            'space_1',
                            'scope_1',
                            'person',
                            'alex',
                            'Alex',
                            '[]',
                            'active',
                            '{}',
                            '2026-05-25T10:00:00+00:00',
                            '2026-05-25T10:00:00+00:00'
                        )
                        """
                    )
                )

            await create_schema(engine)

            def inspect_schema(connection) -> dict[str, object]:
                inspector = inspect(connection)
                row = connection.execute(
                    text(
                        """
                        SELECT confidence, evidence_refs_json, observed_at, valid_from, valid_to
                        FROM memory_anchors
                        WHERE id = 'anchor_1'
                        """
                    )
                ).one()
                return {
                    "columns": {
                        column["name"] for column in inspector.get_columns("memory_anchors")
                    },
                    "row": tuple(row),
                }

            async with engine.connect() as connection:
                return await connection.run_sync(inspect_schema)
        finally:
            await engine.dispose()

    result = asyncio.run(run())

    assert {
        "confidence",
        "evidence_refs_json",
        "observed_at",
        "valid_from",
        "valid_to",
    }.issubset(result["columns"])
    assert result["row"][0] == "medium"
    assert result["row"][1] == "[]"
    assert result["row"][2:] == (None, None, None)


def test_create_schema_dedupes_pending_suggestions_before_unique_indexes(
    tmp_path: Path,
) -> None:
    async def run() -> dict[str, object]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'suggestion-unique.db'}")
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_suggestions (
                            id VARCHAR(80) PRIMARY KEY,
                            space_id VARCHAR(80) NOT NULL,
                            memory_scope_id VARCHAR(80) NOT NULL,
                            candidate_text TEXT NOT NULL,
                            kind VARCHAR(80) NOT NULL,
                            operation VARCHAR(40) NOT NULL DEFAULT 'add',
                            status VARCHAR(40) NOT NULL,
                            source_refs_json JSON NOT NULL,
                            confidence VARCHAR(40) NOT NULL,
                            trust_level VARCHAR(40) NOT NULL,
                            safe_reason VARCHAR(320) NOT NULL,
                            target_fact_id VARCHAR(80),
                            target_fact_version INTEGER,
                            candidate_fingerprint VARCHAR(80),
                            review_reason VARCHAR(320),
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            reviewed_at DATETIME
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_suggestions (
                            id,
                            space_id,
                            memory_scope_id,
                            candidate_text,
                            kind,
                            operation,
                            status,
                            source_refs_json,
                            confidence,
                            trust_level,
                            safe_reason,
                            target_fact_id,
                            candidate_fingerprint,
                            created_at,
                            updated_at
                        )
                        VALUES
                            (
                                'sug_old',
                                'space_1',
                                'memory_scope_1',
                                'old duplicate',
                                'note',
                                'add',
                                'pending',
                                '[]',
                                'medium',
                                'medium',
                                'migration',
                                NULL,
                                'same-fingerprint',
                                '2026-05-25T10:00:00+00:00',
                                '2026-05-25T10:00:00+00:00'
                            ),
                            (
                                'sug_new',
                                'space_1',
                                'memory_scope_1',
                                'new duplicate',
                                'note',
                                'add',
                                'pending',
                                '[]',
                                'medium',
                                'medium',
                                'migration',
                                NULL,
                                'same-fingerprint',
                                '2026-05-25T10:01:00+00:00',
                                '2026-05-25T10:01:00+00:00'
                            )
                        """
                    )
                )

            await create_schema(engine)

            async with engine.begin() as connection:
                pending_result = await connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM memory_suggestions
                        WHERE status = 'pending'
                          AND candidate_fingerprint = 'same-fingerprint'
                        """
                    )
                )
                pending_count = pending_result.scalar_one()
                expired_result = await connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM memory_suggestions
                        WHERE status = 'expired'
                          AND review_reason = 'deduped_by_schema_upgrade'
                        """
                    )
                )
                expired_count = expired_result.scalar_one()
                duplicate_insert_ok = True
                try:
                    await connection.execute(
                        text(
                            """
                            INSERT INTO memory_suggestions (
                                id,
                                space_id,
                                memory_scope_id,
                                candidate_text,
                                kind,
                                operation,
                                status,
                                source_refs_json,
                                confidence,
                                trust_level,
                                safe_reason,
                                target_fact_id,
                                candidate_fingerprint,
                                created_at,
                                updated_at
                            )
                            VALUES (
                                'sug_duplicate',
                                'space_1',
                                'memory_scope_1',
                                'duplicate blocked',
                                'note',
                                'add',
                                'pending',
                                '[]',
                                'medium',
                                'medium',
                                'migration',
                                NULL,
                                'same-fingerprint',
                                '2026-05-25T10:02:00+00:00',
                                '2026-05-25T10:02:00+00:00'
                            )
                            """
                        )
                    )
                except IntegrityError:
                    duplicate_insert_ok = False
                return {
                    "pending_count": pending_count,
                    "expired_count": expired_count,
                    "duplicate_insert_ok": duplicate_insert_ok,
                }
        finally:
            await engine.dispose()

    result = asyncio.run(run())

    assert result["pending_count"] == 1
    assert result["expired_count"] == 1
    assert result["duplicate_insert_ok"] is False
