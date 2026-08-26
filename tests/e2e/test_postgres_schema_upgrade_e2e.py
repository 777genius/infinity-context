"""Real PostgreSQL proof for clean and legacy versioned schema upgrades."""

from __future__ import annotations

import asyncio
import os
from hashlib import sha256
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.migration_runner import _load_migrations
from locator_retrieval_schema_assertions import assert_locator_retrieval_schema
from postgres_schema_upgrade_receipt_fixtures import (
    seed_mismatched_operation_receipt_snapshot,
    seed_mismatched_suggestion_receipt_snapshot,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

_MIGRATIONS = (
    Path(__file__).resolve().parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
)
_METADATA_BASELINE_DELTA = (
    Path(__file__).resolve().parents[1] / "fixtures/postgres_origin_main_metadata_baseline.sql"
)


def test_clean_and_unversioned_legacy_postgres_upgrades_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_clean_and_legacy_upgrade(database_url))


async def _run_concurrent_schema_upgrades(engine: object) -> list[object]:
    upgrade_tasks: list[asyncio.Task[object]] = []
    try:
        upgrade_tasks.append(asyncio.create_task(upgrade_schema(engine)))
        upgrade_tasks.append(asyncio.create_task(upgrade_schema(engine)))
        return await asyncio.wait_for(asyncio.gather(*upgrade_tasks), timeout=20)
    finally:
        for task in (task for task in upgrade_tasks if not task.done()):
            task.cancel()
        await asyncio.gather(*upgrade_tasks, return_exceptions=True)


async def _assert_clean_and_legacy_upgrade(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    try:
        database = PostgresTestDatabase.from_url(
            database_url,
            prefix="schema_upgrade",
            asyncpg=asyncpg,
        )
    except ValueError:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")

    try:
        await database.recreate()
        engine = build_async_engine(database.app_url)
        try:
            clean_results = await _run_concurrent_schema_upgrades(engine)
            clean = next(result for result in clean_results if result.applied)
            assert clean.legacy_baseline is False
            assert clean.current == "0052_reconciliation_outbox_binding_index"
            assert clean.applied[0] == "0001_core_facts"
            canonical_migration_count = len(_load_migrations())
            assert sorted(len(result.applied) for result in clean_results) == [
                0,
                canonical_migration_count,
            ]
            assert (await upgrade_schema(engine)).applied == ()
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM pg_catalog.pg_locks "
                            "WHERE locktype = 'advisory' AND database = "
                            "(SELECT oid FROM pg_catalog.pg_database "
                            "WHERE datname = current_database())"
                        )
                    )
                    == 0
                )
            await _assert_head_schema(engine)
        finally:
            await engine.dispose()
        await database.recreate()
        await _install_metadata_legacy_schema(database)
        engine = build_async_engine(database.app_url)
        try:
            metadata_legacy = await upgrade_schema(engine)
            assert metadata_legacy.legacy_baseline is True
            assert metadata_legacy.applied[0].startswith("0023_")
            await _assert_head_schema(engine)
        finally:
            await engine.dispose()

        await database.recreate()
        await _install_legacy_schema(database)

        engine = build_async_engine(database.app_url)
        try:
            legacy = await upgrade_schema(engine)
            assert legacy.legacy_baseline is True
            assert legacy.applied[0].startswith("0023_")
            assert legacy.current == "0052_reconciliation_outbox_binding_index"
            await _assert_head_schema(engine)
            await _assert_cross_scope_audit_reference_rejected(engine)
        finally:
            await engine.dispose()

        await database.recreate()
        await _install_versioned_schema_through(database, "0028_")
        await _seed_cross_scope_operation_receipt(database)
        engine = build_async_engine(database.app_url)
        try:
            with pytest.raises(
                asyncpg.ForeignKeyViolationError,
                match="fact tenant integrity preflight failed",
            ):
                await upgrade_schema(engine)
            await _assert_failed_upgrade_rolled_back(
                engine,
                current_migration="0028_code_scope_authorizations",
                absent_constraint="fk_memory_fact_operation_receipt_fact_scope",
                absent_columns=(("memory_suggestions", "operation"),),
            )
        finally:
            await engine.dispose()

        await database.recreate()
        await _install_versioned_schema_through(database, "0030_")
        await seed_mismatched_operation_receipt_snapshot(database)
        engine = build_async_engine(database.app_url)
        try:
            with pytest.raises(
                asyncpg.CheckViolationError,
                match="fact operation receipt snapshot identity preflight failed",
            ):
                await upgrade_schema(engine)
            await _assert_failed_upgrade_rolled_back(
                engine,
                current_migration="0030_suggestion_receipt_tenant_integrity",
                absent_constraint=None,
                absent_columns=(),
                absent_trigger="trg_memory_fact_operation_receipt_snapshot_identity",
            )
        finally:
            await engine.dispose()

        await database.recreate()
        await _install_versioned_schema_through(database, "0029_")
        await _seed_cross_scope_suggestion_receipt(database)
        engine = build_async_engine(database.app_url)
        try:
            with pytest.raises(
                asyncpg.ForeignKeyViolationError,
                match="suggestion receipt tenant integrity preflight failed",
            ):
                await upgrade_schema(engine)
            await _assert_failed_upgrade_rolled_back(
                engine,
                current_migration="0029_schema_parity_and_fact_tenant_integrity",
                absent_constraint="fk_suggestion_resolution_receipt_suggestion_scope",
                absent_columns=(
                    ("suggestion_resolution_receipts", "space_id"),
                    ("suggestion_resolution_receipts", "memory_scope_id"),
                    ("suggestion_resolution_receipts", "result_fact_id"),
                    ("suggestion_resolution_receipts", "result_fact_version"),
                ),
            )
            await _assert_legacy_suggestion_receipt_unchanged(engine)
        finally:
            await engine.dispose()

        await database.recreate()
        await _install_versioned_schema_through(database, "0030_")
        await seed_mismatched_suggestion_receipt_snapshot(database)
        engine = build_async_engine(database.app_url)
        try:
            with pytest.raises(
                asyncpg.CheckViolationError,
                match="suggestion receipt snapshot identity preflight failed",
            ):
                await upgrade_schema(engine)
            await _assert_failed_upgrade_rolled_back(
                engine,
                current_migration="0030_suggestion_receipt_tenant_integrity",
                absent_constraint=None,
                absent_columns=(),
            )
        finally:
            await engine.dispose()

        await database.recreate()
        await _install_legacy_schema(database)
        raw = await database.connect()
        try:
            await raw.execute("DROP TABLE memory_threads CASCADE")
        finally:
            await raw.close()
        engine = build_async_engine(database.app_url)
        try:
            with pytest.raises(RuntimeError, match="memory_threads"):
                await upgrade_schema(engine)
            async with engine.connect() as connection:
                history_exists = await connection.scalar(
                    text("SELECT to_regclass('infinity_context_schema_migrations')")
                )
            assert history_exists is None
        finally:
            await engine.dispose()

        await database.recreate()
        raw = await database.connect()
        try:
            await raw.execute("CREATE TABLE memory_spaces (id VARCHAR(80) PRIMARY KEY)")
        finally:
            await raw.close()
        engine = build_async_engine(database.app_url)
        try:
            with pytest.raises(RuntimeError, match="Unrecognized legacy PostgreSQL"):
                await upgrade_schema(engine)
            async with engine.connect() as connection:
                history_exists = await connection.scalar(
                    text("SELECT to_regclass('infinity_context_schema_migrations')")
                )
            assert history_exists is None
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _install_versioned_schema_through(
    database: PostgresTestDatabase,
    migration_prefix: str,
) -> None:
    paths = tuple(
        path for path in sorted(_MIGRATIONS.glob("*.sql")) if path.name[:5] <= migration_prefix
    )
    raw = await database.connect()
    try:
        for path in paths:
            for statement in _raw_migration_statements(path):
                await raw.execute(statement)
        await raw.execute(
            """
            CREATE TABLE infinity_context_schema_migrations (
              migration_id VARCHAR(160) PRIMARY KEY,
              checksum VARCHAR(64) NOT NULL,
              execution_kind VARCHAR(32) NOT NULL,
              applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
              CONSTRAINT ck_infinity_context_schema_migration_kind
                CHECK (execution_kind IN ('applied', 'legacy_baseline'))
            )
            """
        )
        await raw.executemany(
            """
            INSERT INTO infinity_context_schema_migrations (
              migration_id, checksum, execution_kind
            ) VALUES ($1, $2, 'applied')
            """,
            [(path.stem, sha256(path.read_bytes()).hexdigest()) for path in paths],
        )
    finally:
        await raw.close()


async def _install_legacy_schema(database: PostgresTestDatabase) -> None:
    raw = await database.connect()
    try:
        for path in sorted(_MIGRATIONS.glob("*.sql")):
            if path.name.startswith("0023_"):
                break
            for statement in _raw_migration_statements(path):
                await raw.execute(statement)
    finally:
        await raw.close()


def _raw_migration_statements(path: Path) -> tuple[str, ...]:
    sql = path.read_text(encoding="utf-8")
    marker = "-- infinity-context: no-transaction"
    separator = "-- infinity-context: statement-break"
    if not sql.lstrip().startswith(marker):
        return (sql,)
    statements = tuple(statement.strip() for statement in sql.split(separator) if statement.strip())
    assert len(statements) > 1, f"{path.name} declares no-transaction without separators"
    return statements


async def _install_metadata_legacy_schema(database: PostgresTestDatabase) -> None:
    await _install_legacy_schema(database)
    raw = await database.connect()
    try:
        await raw.execute(_METADATA_BASELINE_DELTA.read_text(encoding="utf-8"))
    finally:
        await raw.close()


async def _seed_cross_scope_operation_receipt(database: PostgresTestDatabase) -> None:
    raw = await database.connect()
    try:
        await raw.execute(
            """
            INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at)
            VALUES
              ('space-a', 'space-a', 'Space A', 'active', now(), now()),
              ('space-b', 'space-b', 'Space B', 'active', now(), now());
            INSERT INTO memory_scopes (
              id, space_id, external_ref, name, status, created_at, updated_at
            ) VALUES
              ('scope-a', 'space-a', 'a', 'A', 'active', now(), now()),
              ('scope-b', 'space-b', 'b', 'B', 'active', now(), now());
            INSERT INTO memory_facts (
              id, space_id, memory_scope_id, kind, text, status, confidence,
              trust_level, classification, version, created_at, updated_at
            ) VALUES (
              'fact-a', 'space-a', 'scope-a', 'note', 'A', 'active', 'medium',
              'medium', 'internal', 1, now(), now()
            );
            INSERT INTO memory_fact_versions (
              fact_id, version, text, status, source_refs_json, snapshot_json, created_at
            ) VALUES ('fact-a', 1, 'A', 'active', '[]', '{}', now());
            INSERT INTO memory_fact_operation_receipts (
              id, space_id, memory_scope_id, thread_scope_key, idempotency_key,
              operation, request_fingerprint, result_fact_id, result_fact_version,
              result_snapshot_json, outbox_message_ids_json, created_at
            ) VALUES (
              'receipt-cross-scope', 'space-b', 'scope-b', 'global', 'key',
              'remember', repeat('a', 64), 'fact-a', 1, jsonb_build_object(
                'schema_version', 1,
                'identity', jsonb_build_object(
                  'fact_id', 'fact-a',
                  'space_id', 'space-b',
                  'memory_scope_id', 'scope-b',
                  'thread_id', NULL
                ),
                'visibility', jsonb_build_object('version', 1)
              ), '[]', now()
            );
            """
        )
    finally:
        await raw.close()


async def _seed_cross_scope_suggestion_receipt(database: PostgresTestDatabase) -> None:
    raw = await database.connect()
    try:
        await raw.execute(
            """
            INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at)
            VALUES
              ('space-a', 'space-a', 'Space A', 'active', now(), now()),
              ('space-b', 'space-b', 'Space B', 'active', now(), now());
            INSERT INTO memory_scopes (
              id, space_id, external_ref, name, status, created_at, updated_at
            ) VALUES
              ('scope-a', 'space-a', 'a', 'A', 'active', now(), now()),
              ('scope-b', 'space-b', 'b', 'B', 'active', now(), now());
            INSERT INTO memory_facts (
              id, space_id, memory_scope_id, kind, text, status, confidence,
              trust_level, classification, version, created_at, updated_at
            ) VALUES (
              'fact-b', 'space-b', 'scope-b', 'note', 'B', 'active', 'medium',
              'medium', 'internal', 1, now(), now()
            );
            INSERT INTO memory_fact_versions (
              fact_id, version, text, status, source_refs_json, snapshot_json, created_at
            ) VALUES ('fact-b', 1, 'B', 'active', '[]', '{}', now());
            INSERT INTO memory_suggestions (
              id, space_id, memory_scope_id, candidate_text, kind, status,
              source_refs_json, confidence, trust_level, safe_reason, created_at, updated_at
            ) VALUES (
              'suggestion-a', 'space-a', 'scope-a', 'A', 'note', 'approved',
              '[]', 'medium', 'medium', 'test', now(), now()
            );
            INSERT INTO suggestion_resolution_receipts (
              id, suggestion_id, operation, idempotency_key, request_fingerprint,
              result_suggestion_json, result_fact_json, affected_fact_ids_json,
              affected_fact_versions_json, outbox_message_ids_json, created_at
            ) VALUES (
              'receipt-cross-scope', 'suggestion-a', 'approve', 'approve-key',
              repeat('b', 64), jsonb_build_object(
                'schema_version', 1,
                'id', 'suggestion-a',
                'space_id', 'space-a',
                'memory_scope_id', 'scope-a'
              ), jsonb_build_object(
                'schema_version', 1,
                'identity', jsonb_build_object(
                  'fact_id', 'fact-b',
                  'space_id', 'space-a',
                  'memory_scope_id', 'scope-a',
                  'thread_id', NULL
                ),
                'visibility', jsonb_build_object('version', 1)
              ), '[]', '[]', '[]', now()
            );
            """
        )
    finally:
        await raw.close()


async def _assert_failed_upgrade_rolled_back(
    engine,
    *,
    current_migration: str,
    absent_constraint: str | None,
    absent_columns: tuple[tuple[str, str], ...],
    absent_trigger: str | None = None,
) -> None:
    async with engine.connect() as connection:
        latest = await connection.scalar(
            text(
                """
                SELECT migration_id FROM infinity_context_schema_migrations
                ORDER BY migration_id DESC LIMIT 1
                """
            )
        )
        constraint_count = (
            await connection.scalar(
                text("SELECT count(*) FROM pg_constraint WHERE conname = :constraint_name"),
                {"constraint_name": absent_constraint},
            )
            if absent_constraint is not None
            else 0
        )
        trigger_count = (
            await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM information_schema.triggers
                    WHERE trigger_schema = current_schema()
                      AND trigger_name = :trigger_name
                    """
                ),
                {"trigger_name": absent_trigger},
            )
            if absent_trigger is not None
            else 0
        )
        column_count = 0
        for table_name, column_name in absent_columns:
            column_count += int(
                await connection.scalar(
                    text(
                        """
                        SELECT count(*) FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = :table_name
                          AND column_name = :column_name
                        """
                    ),
                    {"table_name": table_name, "column_name": column_name},
                )
                or 0
            )
    assert latest == current_migration
    assert constraint_count == 0
    assert trigger_count == 0
    assert column_count == 0


async def _assert_legacy_suggestion_receipt_unchanged(engine) -> None:
    async with engine.connect() as connection:
        receipt = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT suggestion_id, operation, idempotency_key,
                               result_suggestion_json, result_fact_json,
                               temporal_decision_id, relation_id
                        FROM suggestion_resolution_receipts
                        WHERE id = 'receipt-cross-scope'
                        """
                    )
                )
            )
            .mappings()
            .one()
        )
    assert dict(receipt) == {
        "suggestion_id": "suggestion-a",
        "operation": "approve",
        "idempotency_key": "approve-key",
        "result_suggestion_json": {
            "schema_version": 1,
            "id": "suggestion-a",
            "space_id": "space-a",
            "memory_scope_id": "scope-a",
        },
        "result_fact_json": {
            "schema_version": 1,
            "identity": {
                "fact_id": "fact-b",
                "space_id": "space-a",
                "memory_scope_id": "scope-a",
                "thread_id": None,
            },
            "visibility": {"version": 1},
        },
        "temporal_decision_id": None,
        "relation_id": None,
    }


async def _assert_head_schema(engine) -> None:
    async with engine.connect() as connection:
        tables = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT table_name FROM information_schema.tables
                        WHERE table_schema = current_schema()
                        """
                    )
                )
            ).scalars()
        )
        assert {"memory_assets", "memory_captures", "memory_context_links"} <= tables
        await assert_locator_retrieval_schema(connection, tables)
        fact_columns = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'memory_facts'
                        """
                    )
                )
            ).scalars()
        )
        assert "evidence_refs_json" in fact_columns
        receipt_columns = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'suggestion_resolution_receipts'
                        """
                    )
                )
            ).scalars()
        )
        assert {
            "space_id",
            "memory_scope_id",
            "result_fact_id",
            "result_fact_version",
        } <= receipt_columns
        jsonb_columns = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT table_name || '.' || column_name
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND data_type = 'jsonb'
                        """
                    )
                )
            ).scalars()
        )
        assert {
            "memory_anchors.aliases_json",
            "memory_anchors.evidence_refs_json",
            "memory_anchors.metadata_json",
            "memory_asset_extraction_artifacts.metadata_json",
            "memory_asset_extraction_jobs.metadata_json",
            "memory_asset_extraction_jobs.result_document_ids_json",
            "memory_comparison_benchmark_runs.cleanup_receipt_json",
            "memory_context_link_suggestions.metadata_json",
            "memory_facts.tags_json",
            "memory_usage_records.metadata_json",
            "memory_users.metadata_json",
        } <= jsonb_columns
        defaulted_columns = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT table_name || '.' || column_name
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND column_default IS NOT NULL
                        """
                    )
                )
            ).scalars()
        )
        assert {
            "memory_anchors.confidence",
            "memory_anchors.status",
            "memory_asset_extraction_jobs.attempt_count",
            "memory_asset_extraction_jobs.status",
            "memory_captures.schema_version",
            "memory_chunks.classification",
            "memory_chunks.status",
            "memory_context_link_suggestions.confidence",
            "memory_context_link_suggestions.score",
            "memory_context_link_suggestions.status",
            "memory_documents.classification",
            "memory_documents.status",
            "memory_episodes.status",
            "memory_facts.classification",
            "memory_outbox.attempt_count",
            "memory_outbox.status",
            "memory_outbox.workload_class",
            "memory_service_tokens.status",
            "memory_space_memberships.status",
            "memory_suggestions.operation",
            "memory_suggestions.review_payload_json",
            "memory_suggestions.tags_json",
            "memory_threads.status",
            "memory_users.status",
        } <= defaulted_columns
        constraints = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT conname FROM pg_constraint
                        WHERE conname LIKE 'fk_memory_fact_%_scope'
                           OR conname LIKE 'fk_memory_fact_%_version'
                           OR conname = 'fk_memory_fact_relation_temporal_decision_identity'
                           OR conname = 'ck_memory_fact_relation_decision_versions'
                           OR conname LIKE 'fk_suggestion_resolution_receipt_%'
                           OR conname = 'ck_suggestion_resolution_receipt_relation_decision'
                           OR conname LIKE 'ck_suggestion_resolution_receipt_fact_%'
                           OR conname = 'ck_chunk_owner'
                        """
                    )
                )
            ).scalars()
        )
        assert "fk_memory_fact_operation_receipt_fact_scope" in constraints
        assert "fk_memory_fact_temporal_decision_source_version" in constraints
        assert "fk_memory_fact_temporal_decision_compensation_scope" in constraints
        assert "fk_memory_fact_relation_temporal_decision_identity" in constraints
        assert "ck_memory_fact_relation_decision_versions" in constraints
        assert "fk_suggestion_resolution_receipt_suggestion_scope" in constraints
        assert "fk_suggestion_resolution_receipt_fact_scope" in constraints
        assert "fk_suggestion_resolution_receipt_fact_version" in constraints
        assert "fk_suggestion_resolution_receipt_decision_scope" in constraints
        assert "fk_suggestion_resolution_receipt_relation_decision" in constraints
        assert "ck_suggestion_resolution_receipt_relation_decision" in constraints
        assert "ck_suggestion_resolution_receipt_fact_pair" in constraints
        assert "ck_suggestion_resolution_receipt_fact_snapshot" in constraints
        assert "ck_chunk_owner" in constraints
        triggers = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT DISTINCT trigger_name
                        FROM information_schema.triggers
                        WHERE trigger_schema = current_schema()
                          AND trigger_name LIKE 'trg_%_benchmark_writer_fence'
                        """
                    )
                )
            ).scalars()
        )
        assert {
            "trg_memory_anchors_benchmark_writer_fence",
            "trg_memory_asset_extraction_jobs_benchmark_writer_fence",
            "trg_memory_assets_benchmark_writer_fence",
            "trg_memory_captures_benchmark_writer_fence",
            "trg_memory_context_link_suggestions_benchmark_writer_fence",
            "trg_memory_context_links_benchmark_writer_fence",
            "trg_memory_suggestions_benchmark_writer_fence",
        } <= triggers
        receipt_triggers = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT DISTINCT trigger_name
                        FROM information_schema.triggers
                        WHERE trigger_schema = current_schema()
                          AND trigger_name IN (
                            'trg_memory_fact_operation_receipt_snapshot_identity',
                            'trg_suggestion_resolution_receipt_compatibility_fields'
                          )
                        """
                    )
                )
            ).scalars()
        )
        assert receipt_triggers == {
            "trg_memory_fact_operation_receipt_snapshot_identity",
            "trg_suggestion_resolution_receipt_compatibility_fields",
        }
        suggestion_indexes = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND tablename = 'memory_suggestions'
                        """
                    )
                )
            ).scalars()
        )
        assert {
            "uq_pending_suggestion_fingerprint_no_target",
            "uq_pending_suggestion_fingerprint_target",
        } <= suggestion_indexes
        writer_fence_definition = str(
            await connection.scalar(
                text(
                    """
                    SELECT pg_get_functiondef(
                      'memory_comparison_enforce_benchmark_writer_fence()'::regprocedure
                    )
                    """
                )
            )
        )
        assert "AND TG_TABLE_NAME IN (" in writer_fence_definition
        assert "'memory_documents', 'memory_chunks'" in writer_fence_definition
        assert "'memory_anchors'" not in writer_fence_definition


async def _assert_cross_scope_audit_reference_rejected(engine) -> None:
    async with engine.begin() as connection:
        statements = (
            """
                INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at)
                VALUES
                  ('space-a', 'space-a', 'Space A', 'active', now(), now()),
                  ('space-b', 'space-b', 'Space B', 'active', now(), now())
            """,
            """
                INSERT INTO memory_scopes (
                  id, space_id, external_ref, name, status, created_at, updated_at
                ) VALUES
                  ('scope-a', 'space-a', 'a', 'A', 'active', now(), now()),
                  ('scope-b', 'space-b', 'b', 'B', 'active', now(), now())
            """,
            """
                INSERT INTO memory_facts (
                  id, space_id, memory_scope_id, kind, text, status, confidence,
                  trust_level, classification, version, created_at, updated_at
                ) VALUES
                  ('fact-a', 'space-a', 'scope-a', 'note', 'A', 'active', 'medium',
                   'medium', 'internal', 1, now(), now()),
                  ('fact-a2', 'space-a', 'scope-a', 'note', 'A2', 'active', 'medium',
                   'medium', 'internal', 1, now(), now()),
                  ('fact-b', 'space-b', 'scope-b', 'note', 'B', 'active', 'medium',
                   'medium', 'internal', 1, now(), now())
            """,
            """
                INSERT INTO memory_fact_versions (
                  fact_id, version, text, status, source_refs_json, snapshot_json, created_at
                ) VALUES
                  ('fact-a', 1, 'A', 'active', '[]', '{}', now()),
                  ('fact-a2', 1, 'A2', 'active', '[]', '{}', now()),
                  ('fact-b', 1, 'B', 'active', '[]', '{}', now())
            """,
            """
                INSERT INTO memory_suggestions (
                  id, space_id, memory_scope_id, candidate_text, kind, status,
                  source_refs_json, confidence, trust_level, safe_reason, created_at, updated_at
                ) VALUES (
                  'suggestion-b', 'space-b', 'scope-b', 'B suggestion', 'note', 'approved',
                  '[]', 'medium', 'medium', 'test', now(), now()
                )
            """,
            """
                INSERT INTO memory_fact_temporal_decisions (
                  id, decision_type, space_id, memory_scope_id, thread_scope_key,
                  source_fact_id, source_fact_version, target_fact_id, target_fact_version,
                  effective_at, evidence_refs_json, actor_id, policy_version, reason_code,
                  applied_at, idempotency_key, outbox_message_ids_json
                ) VALUES (
                  'decision-a', 'supersede', 'space-a', 'scope-a', 'global',
                  'fact-a', 1, 'fact-a2', 1, now(), '[]', 'reviewer', 'v1', 'test',
                  now(), 'decision-a-key', '[]'
                )
            """,
        )
        for statement in statements:
            await connection.execute(text(statement))
    async with engine.begin() as connection:
        with pytest.raises(
            IntegrityError,
            match="fk_suggestion_resolution_receipt_decision_scope",
        ):
            await connection.execute(
                text(
                    """
                    INSERT INTO suggestion_resolution_receipts (
                      id, suggestion_id, space_id, memory_scope_id, operation,
                      idempotency_key, request_fingerprint, result_suggestion_json,
                      affected_fact_ids_json, affected_fact_versions_json,
                      temporal_decision_id, outbox_message_ids_json, created_at
                    ) VALUES (
                      'suggestion-receipt-cross-scope', 'suggestion-b', 'space-b', 'scope-b',
                      'approve', 'approve-key', repeat('c', 64), jsonb_build_object(
                        'schema_version', 1,
                        'id', 'suggestion-b',
                        'space_id', 'space-b',
                        'memory_scope_id', 'scope-b'
                      ), '[]', '[]',
                      'decision-a', '[]', now()
                    )
                    """
                )
            )
    async with engine.begin() as connection:
        with pytest.raises(
            IntegrityError,
            match="fk_suggestion_resolution_receipt_fact_scope",
        ):
            await connection.execute(
                text(
                    """
                    INSERT INTO suggestion_resolution_receipts (
                      id, suggestion_id, space_id, memory_scope_id, operation,
                      idempotency_key, request_fingerprint, result_suggestion_json,
                      result_fact_json, result_fact_id, result_fact_version,
                      affected_fact_ids_json, affected_fact_versions_json,
                      outbox_message_ids_json, created_at
                    ) VALUES (
                      'suggestion-receipt-cross-scope-fact', 'suggestion-b',
                      'space-b', 'scope-b', 'approve', 'approve-fact-key', repeat('d', 64),
                      jsonb_build_object(
                        'schema_version', 1,
                        'id', 'suggestion-b',
                        'space_id', 'space-b',
                        'memory_scope_id', 'scope-b'
                      ), jsonb_build_object(
                        'schema_version', 1,
                        'identity', jsonb_build_object(
                          'fact_id', 'fact-a',
                          'space_id', 'space-b',
                          'memory_scope_id', 'scope-b',
                          'thread_id', NULL
                        ),
                        'visibility', jsonb_build_object('version', 1)
                      ), 'fact-b', 1, '[]', '[]', '[]', now()
                    )
                    """
                )
            )
    async with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="fk_memory_fact_operation_receipt_fact_scope"):
            await connection.execute(
                text(
                    """
                    INSERT INTO memory_fact_operation_receipts (
                      id, space_id, memory_scope_id, thread_scope_key, idempotency_key,
                      operation, request_fingerprint, result_fact_id, result_fact_version,
                      result_snapshot_json, outbox_message_ids_json, created_at
                    ) VALUES (
                      'receipt-cross-scope', 'space-b', 'scope-b', 'global', 'key',
                      'remember', repeat('a', 64), 'fact-a', 1, jsonb_build_object(
                        'schema_version', 1,
                        'identity', jsonb_build_object(
                          'fact_id', 'fact-a',
                          'space_id', 'space-b',
                          'memory_scope_id', 'scope-b',
                          'thread_id', NULL
                        ),
                        'visibility', jsonb_build_object('version', 1)
                      ), '[]', now()
                    )
                    """
                )
            )
    async with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="ck_memory_fact_relation_decision_versions"):
            await connection.execute(
                text(
                    """
                    INSERT INTO memory_fact_relations (
                      id, space_id, memory_scope_id, source_fact_id, target_fact_id,
                      relation_type, reason, status, observed_at, temporal_decision_id,
                      created_at, updated_at
                    ) VALUES (
                      'relation-missing-versions', 'space-a', 'scope-a', 'fact-a2', 'fact-a',
                      'supersedes', 'test', 'active', now(), 'decision-a', now(), now()
                    )
                    """
                )
            )
    async with engine.begin() as connection:
        with pytest.raises(
            IntegrityError,
            match="fk_memory_fact_temporal_decision_compensation_scope",
        ):
            await connection.execute(
                text(
                    """
                    INSERT INTO memory_fact_temporal_decisions (
                      id, decision_type, space_id, memory_scope_id, thread_scope_key,
                      source_fact_id, source_fact_version, effective_at, evidence_refs_json,
                      actor_id, policy_version, reason_code, applied_at, idempotency_key,
                      compensates_decision_id, outbox_message_ids_json
                    ) VALUES (
                      'decision-b', 'reinstate', 'space-b', 'scope-b', 'global',
                      'fact-b', 1, now(), '[]', 'reviewer', 'v1', 'test', now(),
                      'decision-b-key', 'decision-a', '[]'
                    )
                    """
                )
            )
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO suggestion_resolution_receipts (
                  id, suggestion_id, operation, idempotency_key, request_fingerprint,
                  result_suggestion_json, result_fact_json, affected_fact_ids_json,
                  affected_fact_versions_json, outbox_message_ids_json, created_at
                ) VALUES (
                  'legacy-writer-compatible', 'suggestion-b', 'approve',
                  'legacy-writer-key', repeat('e', 64), jsonb_build_object(
                    'schema_version', 1,
                    'id', 'suggestion-b',
                    'space_id', 'space-b',
                    'memory_scope_id', 'scope-b'
                  ), jsonb_build_object(
                    'schema_version', 1,
                    'identity', jsonb_build_object(
                      'fact_id', 'fact-b',
                      'space_id', 'space-b',
                      'memory_scope_id', 'scope-b',
                      'thread_id', NULL
                    ),
                    'visibility', jsonb_build_object('version', 1)
                  ), '[]', '[]', '[]', now()
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO suggestion_resolution_receipts (
                  id, suggestion_id, operation, idempotency_key, request_fingerprint,
                  result_suggestion_json, result_fact_json, affected_fact_ids_json,
                  affected_fact_versions_json, outbox_message_ids_json, created_at
                ) VALUES (
                  'legacy-json-null-compatible', 'suggestion-b', 'reject',
                  'legacy-json-null-key', repeat('f', 64), jsonb_build_object(
                    'schema_version', 1,
                    'id', 'suggestion-b',
                    'space_id', 'space-b',
                    'memory_scope_id', 'scope-b'
                  ), 'null'::jsonb, '[]', '[]', '[]', now()
                )
                """
            )
        )
    async with engine.connect() as connection:
        compatibility_fields = (
            await connection.execute(
                text(
                    """
                    SELECT space_id, memory_scope_id, result_fact_id, result_fact_version
                    FROM suggestion_resolution_receipts
                    WHERE id = 'legacy-writer-compatible'
                    """
                )
            )
        ).one()
    assert tuple(compatibility_fields) == ("space-b", "scope-b", "fact-b", 1)
    async with engine.connect() as connection:
        normalized_json_null = await connection.scalar(
            text(
                """
                SELECT result_fact_json IS NULL
                FROM suggestion_resolution_receipts
                WHERE id = 'legacy-json-null-compatible'
                """
            )
        )
    assert normalized_json_null is True
