"""Real PostgreSQL proof for clean and legacy versioned schema upgrades."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from sqlalchemy import text
from sqlalchemy.engine import make_url
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


async def _assert_clean_and_legacy_upgrade(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("postgresql"):
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")
    database_name = f"schema_upgrade_{uuid.uuid4().hex}"
    admin_dsn = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    app_url = parsed.set(
        drivername="postgresql+asyncpg",
        database=database_name,
    ).render_as_string(hide_password=False)

    async def recreate_database() -> None:
        admin = await asyncpg.connect(admin_dsn)
        try:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                database_name,
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
            await admin.execute(f'CREATE DATABASE "{database_name}"')
        finally:
            await admin.close()

    async def drop_database() -> None:
        admin = await asyncpg.connect(admin_dsn)
        try:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                database_name,
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        finally:
            await admin.close()

    async def install_legacy_schema() -> None:
        raw = await asyncpg.connect(
            parsed.set(drivername="postgresql", database=database_name).render_as_string(
                hide_password=False
            )
        )
        try:
            for path in sorted(_MIGRATIONS.glob("*.sql")):
                if path.name.startswith("0023_"):
                    break
                await raw.execute(path.read_text(encoding="utf-8"))
        finally:
            await raw.close()

    async def install_metadata_legacy_schema() -> None:
        await install_legacy_schema()
        raw = await asyncpg.connect(
            parsed.set(drivername="postgresql", database=database_name).render_as_string(
                hide_password=False
            )
        )
        try:
            await raw.execute(_METADATA_BASELINE_DELTA.read_text(encoding="utf-8"))
        finally:
            await raw.close()

    try:
        await recreate_database()
        engine = build_async_engine(app_url)
        try:
            clean_results = await asyncio.gather(upgrade_schema(engine), upgrade_schema(engine))
            clean = next(result for result in clean_results if result.applied)
            assert clean.legacy_baseline is False
            assert clean.current == "0029_schema_parity_and_fact_tenant_integrity"
            assert clean.applied[0] == "0001_core_facts"
            assert sorted(len(result.applied) for result in clean_results) == [0, 30]
            assert (await upgrade_schema(engine)).applied == ()
            await _assert_head_schema(engine)
        finally:
            await engine.dispose()

        await recreate_database()
        await install_metadata_legacy_schema()
        engine = build_async_engine(app_url)
        try:
            metadata_legacy = await upgrade_schema(engine)
            assert metadata_legacy.legacy_baseline is True
            assert metadata_legacy.applied[0].startswith("0023_")
            await _assert_head_schema(engine)
        finally:
            await engine.dispose()

        await recreate_database()
        await install_legacy_schema()

        engine = build_async_engine(app_url)
        try:
            legacy = await upgrade_schema(engine)
            assert legacy.legacy_baseline is True
            assert legacy.applied[0].startswith("0023_")
            assert legacy.current == "0029_schema_parity_and_fact_tenant_integrity"
            await _assert_head_schema(engine)
            await _assert_cross_scope_audit_reference_rejected(engine)
        finally:
            await engine.dispose()

        await recreate_database()
        await install_legacy_schema()
        raw = await asyncpg.connect(
            parsed.set(drivername="postgresql", database=database_name).render_as_string(
                hide_password=False
            )
        )
        try:
            await raw.execute("DROP TABLE memory_threads CASCADE")
        finally:
            await raw.close()
        engine = build_async_engine(app_url)
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

        await recreate_database()
        raw = await asyncpg.connect(
            parsed.set(drivername="postgresql", database=database_name).render_as_string(
                hide_password=False
            )
        )
        try:
            await raw.execute("CREATE TABLE memory_spaces (id VARCHAR(80) PRIMARY KEY)")
        finally:
            await raw.close()
        engine = build_async_engine(app_url)
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
        await drop_database()


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
                      'remember', repeat('a', 64), 'fact-a', 1, '{}', '[]', now()
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
