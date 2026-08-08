"""PostgreSQL seed helpers for receipt snapshot migration failures."""

from postgres_test_database import PostgresTestDatabase


async def seed_mismatched_operation_receipt_snapshot(
    database: PostgresTestDatabase,
) -> None:
    raw = await database.connect()
    try:
        await raw.execute(
            """
            INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at)
            VALUES ('space-a', 'space-a', 'Space A', 'active', now(), now());
            INSERT INTO memory_scopes (
              id, space_id, external_ref, name, status, created_at, updated_at
            ) VALUES ('scope-a', 'space-a', 'a', 'A', 'active', now(), now());
            INSERT INTO memory_facts (
              id, space_id, memory_scope_id, kind, text, status, confidence,
              trust_level, classification, version, created_at, updated_at
            ) VALUES
              ('fact-a', 'space-a', 'scope-a', 'note', 'A', 'active', 'medium',
               'medium', 'internal', 1, now(), now()),
              ('fact-b', 'space-a', 'scope-a', 'note', 'B', 'active', 'medium',
               'medium', 'internal', 2, now(), now());
            INSERT INTO memory_fact_versions (
              fact_id, version, text, status, source_refs_json, snapshot_json, created_at
            ) VALUES
              ('fact-a', 1, 'A', 'active', '[]', '{}', now()),
              ('fact-b', 2, 'B', 'active', '[]', '{}', now());
            INSERT INTO memory_fact_operation_receipts (
              id, space_id, memory_scope_id, thread_scope_key, idempotency_key,
              operation, request_fingerprint, result_fact_id, result_fact_version,
              result_snapshot_json, outbox_message_ids_json, created_at
            ) VALUES (
              'receipt-snapshot-mismatch', 'space-a', 'scope-a', 'global', 'key',
              'remember', repeat('a', 64), 'fact-a', 1,
              jsonb_build_object(
                'schema_version', 1,
                'identity', jsonb_build_object(
                  'fact_id', 'fact-b',
                  'space_id', 'space-a',
                  'memory_scope_id', 'scope-a',
                  'thread_id', NULL
                ),
                'visibility', jsonb_build_object('version', 2)
              ),
              '[]', now()
            );
            """
        )
    finally:
        await raw.close()


async def seed_mismatched_suggestion_receipt_snapshot(
    database: PostgresTestDatabase,
) -> None:
    raw = await database.connect()
    try:
        await raw.execute(
            """
            INSERT INTO memory_spaces (id, slug, name, status, created_at, updated_at)
            VALUES ('space-a', 'space-a', 'Space A', 'active', now(), now());
            INSERT INTO memory_scopes (
              id, space_id, external_ref, name, status, created_at, updated_at
            ) VALUES ('scope-a', 'space-a', 'a', 'A', 'active', now(), now());
            INSERT INTO memory_suggestions (
              id, space_id, memory_scope_id, candidate_text, kind, status,
              source_refs_json, confidence, trust_level, safe_reason, created_at, updated_at
            ) VALUES (
              'suggestion-a', 'space-a', 'scope-a', 'A', 'note', 'rejected',
              '[]', 'medium', 'medium', 'test', now(), now()
            );
            INSERT INTO suggestion_resolution_receipts (
              id, suggestion_id, operation, idempotency_key, request_fingerprint,
              result_suggestion_json, affected_fact_ids_json,
              affected_fact_versions_json, outbox_message_ids_json, created_at
            ) VALUES (
              'receipt-suggestion-mismatch', 'suggestion-a', 'reject', 'reject-key',
              repeat('c', 64), jsonb_build_object(
                'schema_version', 1,
                'id', 'suggestion-other',
                'space_id', 'space-a',
                'memory_scope_id', 'scope-a'
              ), '[]', '[]', '[]', now()
            );
            """
        )
    finally:
        await raw.close()


__all__ = (
    "seed_mismatched_operation_receipt_snapshot",
    "seed_mismatched_suggestion_receipt_snapshot",
)
