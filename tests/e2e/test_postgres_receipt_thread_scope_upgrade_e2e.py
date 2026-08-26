"""Focused PostgreSQL E2E for receipt and thread-scope migration hardening."""

from __future__ import annotations

import asyncio
import os

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_postgres_schema_upgrade_e2e import (
    _install_metadata_legacy_schema,
    _install_versioned_schema_through,
)


def test_receipt_and_thread_scope_upgrade_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_receipt_and_thread_scope_upgrade(database_url))


async def _assert_receipt_and_thread_scope_upgrade(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    try:
        database = PostgresTestDatabase.from_url(
            database_url,
            prefix="receipt_thread_scope",
            asyncpg=asyncpg,
        )
    except ValueError:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")

    try:
        await database.recreate()
        await _install_versioned_schema_through(database, "0029_")
        await _seed_legacy_json_null_receipt(database)
        engine = build_async_engine(database.app_url)
        try:
            repaired = await upgrade_schema(engine)
            assert repaired.applied[0] == "0030_suggestion_receipt_tenant_integrity"
            async with engine.connect() as connection:
                assert await connection.scalar(
                    text(
                        "SELECT result_fact_json IS NULL "
                        "FROM suggestion_resolution_receipts "
                        "WHERE id = 'legacy-json-null-upgrade'"
                    )
                )
        finally:
            await engine.dispose()

        await database.recreate()
        await _install_versioned_schema_through(database, "0031_")
        await _seed_typed_malformed_receipt_between_migrations(database)
        engine = build_async_engine(database.app_url)
        try:
            with pytest.raises(
                asyncpg.CheckViolationError,
                match="fact operation receipt snapshot identity preflight failed",
            ):
                await upgrade_schema(engine)
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text(
                            "SELECT migration_id FROM infinity_context_schema_migrations "
                            "ORDER BY migration_id DESC LIMIT 1"
                        )
                    )
                    == "0031_receipt_snapshot_identity"
                )
        finally:
            await engine.dispose()

        await database.recreate()
        await _install_metadata_legacy_schema(database)
        await _seed_same_thread_origin_main_relation(database)
        engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(engine)
            assert result.legacy_baseline is True
            assert result.current == "0049_reconciliation_runtime_generation"
            await _assert_same_thread_relation_and_not_null_keys(engine)
            await _assert_thread_scope_fks_and_append_only_receipts(engine)
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _seed_legacy_json_null_receipt(database: PostgresTestDatabase) -> None:
    raw = await database.connect()
    try:
        await raw.execute(
            """
            INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at)
            VALUES ('space-json', 'space-json', 'Space', 'active', now(), now());
            INSERT INTO memory_scopes (
              id, space_id, external_ref, name, status, created_at, updated_at
            ) VALUES ('scope-json', 'space-json', 'scope', 'Scope', 'active', now(), now());
            INSERT INTO memory_suggestions (
              id, space_id, memory_scope_id, candidate_text, kind, status,
              source_refs_json, confidence, trust_level, safe_reason, created_at, updated_at
            ) VALUES (
              'suggestion-json', 'space-json', 'scope-json', 'Candidate', 'note',
              'rejected', '[]', 'medium', 'medium', 'test', now(), now()
            );
            INSERT INTO suggestion_resolution_receipts (
              id, suggestion_id, operation, idempotency_key, request_fingerprint,
              result_suggestion_json, result_fact_json, affected_fact_ids_json,
              affected_fact_versions_json, outbox_message_ids_json, created_at
            ) VALUES (
              'legacy-json-null-upgrade', 'suggestion-json', 'reject', 'json-key',
              repeat('7', 64), jsonb_build_object(
                'schema_version', 1, 'id', 'suggestion-json',
                'space_id', 'space-json', 'memory_scope_id', 'scope-json'
              ), 'null'::jsonb, '[]', '[]', '[]', now()
            );
            """
        )
    finally:
        await raw.close()


async def _seed_typed_malformed_receipt_between_migrations(
    database: PostgresTestDatabase,
) -> None:
    raw = await database.connect()
    try:
        await raw.execute(
            """
            INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at)
            VALUES ('space-bad', 'space-bad', 'Space', 'active', now(), now());
            INSERT INTO memory_scopes (
              id, space_id, external_ref, name, status, created_at, updated_at
            ) VALUES ('scope-bad', 'space-bad', 'scope', 'Scope', 'active', now(), now());
            INSERT INTO memory_facts (
              id, space_id, memory_scope_id, kind, text, status, confidence,
              trust_level, classification, version, created_at, updated_at
            ) VALUES (
              'fact-bad', 'space-bad', 'scope-bad', 'note', 'Bad', 'active', 'medium',
              'medium', 'internal', 1, now(), now()
            );
            INSERT INTO memory_fact_versions (
              fact_id, version, text, status, source_refs_json, snapshot_json, created_at
            ) VALUES ('fact-bad', 1, 'Bad', 'active', '[]', '{}', now());
            ALTER TABLE memory_fact_operation_receipts
              DISABLE TRIGGER trg_memory_fact_operation_receipt_snapshot_identity;
            INSERT INTO memory_fact_operation_receipts (
              id, space_id, memory_scope_id, thread_scope_key, idempotency_key,
              operation, request_fingerprint, result_fact_id, result_fact_version,
              result_snapshot_json, outbox_message_ids_json, created_at
            ) VALUES (
              'typed-malformed', 'space-bad', 'scope-bad', 'global', 'bad-key',
              'remember', repeat('8', 64), 'fact-bad', 1, jsonb_build_object(
                'schema_version', '1',
                'identity', jsonb_build_object(
                  'fact_id', 'fact-bad', 'space_id', 'space-bad',
                  'memory_scope_id', 'scope-bad', 'thread_id', NULL
                ),
                'visibility', jsonb_build_object('version', 1)
              ), '[]', now()
            );
            ALTER TABLE memory_fact_operation_receipts
              ENABLE TRIGGER trg_memory_fact_operation_receipt_snapshot_identity;
            """
        )
    finally:
        await raw.close()


async def _seed_same_thread_origin_main_relation(database: PostgresTestDatabase) -> None:
    raw = await database.connect()
    try:
        await raw.execute(
            """
            INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at)
            VALUES ('space-thread', 'space-thread', 'Space', 'active', now(), now());
            INSERT INTO memory_scopes (
              id, space_id, external_ref, name, status, created_at, updated_at
            ) VALUES (
              'scope-thread', 'space-thread', 'scope', 'Scope', 'active', now(), now()
            );
            INSERT INTO memory_threads (
              id, space_id, memory_scope_id, external_ref, status, created_at, updated_at
            ) VALUES (
              'thread-a', 'space-thread', 'scope-thread', 'thread-a', 'active', now(), now()
            );
            INSERT INTO memory_facts (
              id, space_id, memory_scope_id, thread_id, kind, text, status, confidence,
              trust_level, version, created_at, updated_at
            ) VALUES
              ('legacy-source', 'space-thread', 'scope-thread', 'thread-a', 'note',
               'Source', 'active', 'medium', 'medium', 1, now(), now()),
              ('legacy-target', 'space-thread', 'scope-thread', 'thread-a', 'note',
               'Target', 'active', 'medium', 'medium', 1, now(), now());
            INSERT INTO memory_fact_relations (
              id, space_id, memory_scope_id, source_fact_id, target_fact_id,
              relation_type, reason, status, observed_at, created_at, updated_at
            ) VALUES (
              'legacy-relation', 'space-thread', 'scope-thread', 'legacy-source',
              'legacy-target', 'related_to', 'legacy', 'active', now(), now(), now()
            );
            """
        )
    finally:
        await raw.close()


async def _assert_same_thread_relation_and_not_null_keys(engine) -> None:
    async with engine.connect() as connection:
        relation = (
            await connection.execute(
                text(
                    "SELECT thread_id, thread_scope_key FROM memory_fact_relations "
                    "WHERE id = 'legacy-relation'"
                )
            )
        ).one()
        nullability = {
            (table_name, column_name): is_nullable
            for table_name, column_name, is_nullable in (
                await connection.execute(
                    text(
                        """
                        SELECT table_name, column_name, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND column_name = 'thread_scope_key'
                          AND table_name IN ('memory_facts', 'memory_fact_relations')
                        """
                    )
                )
            ).all()
        }
    assert tuple(relation) == ("thread-a", "thread:thread-a")
    assert nullability == {
        ("memory_facts", "thread_scope_key"): "NO",
        ("memory_fact_relations", "thread_scope_key"): "NO",
    }


async def _assert_thread_scope_fks_and_append_only_receipts(engine) -> None:
    async with engine.begin() as connection:
        for statement in (
            """
                INSERT INTO memory_threads (
                  id, space_id, memory_scope_id, external_ref, status, created_at, updated_at
                ) VALUES (
                  'thread-b', 'space-thread', 'scope-thread', 'thread-b', 'active', now(), now()
                )
            """,
            """
                INSERT INTO memory_facts (
                  id, space_id, memory_scope_id, thread_id, kind, text, status, confidence,
                  trust_level, classification, version, created_at, updated_at
                ) VALUES (
                  'fact-thread-b', 'space-thread', 'scope-thread', 'thread-b', 'note',
                  'B', 'active', 'medium', 'medium', 'internal', 1, now(), now()
                )
            """,
            """
                INSERT INTO memory_fact_versions (
                  fact_id, version, text, status, source_refs_json, snapshot_json, created_at
                ) VALUES
                  ('legacy-source', 1, 'Source', 'active', '[]', '{}', now()),
                  ('legacy-target', 1, 'Target', 'active', '[]', '{}', now()),
                  ('fact-thread-b', 1, 'B', 'active', '[]', '{}', now())
            """,
        ):
            await connection.execute(text(statement))
    await _assert_cross_thread_inserts_rejected(engine)
    await _insert_valid_receipts(engine)
    for table_name, row_id in (
        ("memory_fact_operation_receipts", "receipt-valid"),
        ("suggestion_resolution_receipts", "suggestion-receipt-valid"),
    ):
        for operation in ("UPDATE", "DELETE"):
            statement = (
                f"UPDATE {table_name} SET created_at = now() WHERE id = :row_id"
                if operation == "UPDATE"
                else f"DELETE FROM {table_name} WHERE id = :row_id"
            )
            async with engine.begin() as connection:
                with pytest.raises(DBAPIError, match="exact-result receipt is append-only"):
                    await connection.execute(text(statement), {"row_id": row_id})


async def _assert_cross_thread_inserts_rejected(engine) -> None:
    statements = (
        (
            "fk_memory_fact_operation_receipt_fact_scope",
            """
            INSERT INTO memory_fact_operation_receipts (
              id, space_id, memory_scope_id, thread_id, thread_scope_key, idempotency_key,
              operation, request_fingerprint, result_fact_id, result_fact_version,
              result_snapshot_json, outbox_message_ids_json, created_at
            ) VALUES (
              'receipt-cross-thread', 'space-thread', 'scope-thread', 'thread-b',
              'thread:thread-b', 'cross-key', 'remember', repeat('1', 64),
              'legacy-source', 1, jsonb_build_object(
                'schema_version', 1, 'identity', jsonb_build_object(
                  'fact_id', 'legacy-source', 'space_id', 'space-thread',
                  'memory_scope_id', 'scope-thread', 'thread_id', 'thread-b'
                ), 'visibility', jsonb_build_object('version', 1)
              ), '[]', now()
            )
            """,
        ),
        (
            "fk_memory_fact_temporal_decision_source_scope",
            """
            INSERT INTO memory_fact_temporal_decisions (
              id, decision_type, space_id, memory_scope_id, thread_id, thread_scope_key,
              source_fact_id, source_fact_version, effective_at, evidence_refs_json,
              actor_id, policy_version, reason_code, applied_at, idempotency_key,
              outbox_message_ids_json
            ) VALUES (
              'decision-cross-thread', 'reinstate', 'space-thread', 'scope-thread',
              'thread-b', 'thread:thread-b', 'legacy-source', 1, now(), '[]',
              'reviewer', 'v1', 'test', now(), 'decision-cross-key', '[]'
            )
            """,
        ),
        (
            "fk_memory_fact_relation_source_scope",
            """
            INSERT INTO memory_fact_relations (
              id, space_id, memory_scope_id, thread_id, source_fact_id, target_fact_id,
              relation_type, reason, status, observed_at, created_at, updated_at
            ) VALUES (
              'relation-cross-thread', 'space-thread', 'scope-thread', 'thread-b',
              'legacy-source', 'fact-thread-b', 'related_to', 'test', 'active',
              now(), now(), now()
            )
            """,
        ),
    )
    for constraint, statement in statements:
        async with engine.begin() as connection:
            with pytest.raises(IntegrityError, match=constraint):
                await connection.execute(text(statement))


async def _insert_valid_receipts(engine) -> None:
    async with engine.begin() as connection:
        for statement in (
            """
                INSERT INTO memory_fact_operation_receipts (
                  id, space_id, memory_scope_id, thread_id, thread_scope_key,
                  idempotency_key, operation, request_fingerprint, result_fact_id,
                  result_fact_version, result_snapshot_json, outbox_message_ids_json, created_at
                ) VALUES (
                  'receipt-valid', 'space-thread', 'scope-thread', 'thread-a',
                  'thread:thread-a', 'receipt-key', 'remember', repeat('2', 64),
                  'legacy-source', 1, jsonb_build_object(
                    'schema_version', 1, 'identity', jsonb_build_object(
                      'fact_id', 'legacy-source', 'space_id', 'space-thread',
                      'memory_scope_id', 'scope-thread', 'thread_id', 'thread-a'
                    ), 'visibility', jsonb_build_object('version', 1)
                  ), '[]', now()
                )
            """,
            """
                INSERT INTO memory_suggestions (
                  id, space_id, memory_scope_id, candidate_text, kind, status,
                  source_refs_json, confidence, trust_level, safe_reason, created_at, updated_at
                ) VALUES (
                  'suggestion-valid', 'space-thread', 'scope-thread', 'Candidate', 'note',
                  'rejected', '[]', 'medium', 'medium', 'test', now(), now()
                )
            """,
            """
                INSERT INTO suggestion_resolution_receipts (
                  id, suggestion_id, space_id, memory_scope_id, operation, idempotency_key,
                  request_fingerprint, result_suggestion_json, affected_fact_ids_json,
                  affected_fact_versions_json, outbox_message_ids_json, created_at
                ) VALUES (
                  'suggestion-receipt-valid', 'suggestion-valid', 'space-thread',
                  'scope-thread', 'reject', 'suggestion-key', repeat('3', 64),
                  jsonb_build_object(
                    'schema_version', 1, 'id', 'suggestion-valid',
                    'space_id', 'space-thread', 'memory_scope_id', 'scope-thread'
                  ), '[]', '[]', '[]', now()
                )
            """,
        ):
            await connection.execute(text(statement))
