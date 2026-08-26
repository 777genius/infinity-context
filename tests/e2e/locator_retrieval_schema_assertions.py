"""Schema assertions owned by the Retrieval PostgreSQL upgrade."""

from __future__ import annotations

from sqlalchemy import text


async def assert_locator_retrieval_schema(connection, tables: set[str]) -> None:
    assert "memory_locator_projection_tombstones" in tables
    assert "memory_document_projection_receipts" in tables
    assert {
        "memory_locator_profiles",
        "memory_locator_profile_projection_receipts",
        "memory_locator_profile_lanes",
        "memory_locator_profile_attestation_checkpoints",
        "memory_locator_profile_attestation_pages",
        "memory_locator_profile_tombstones",
        "memory_locator_profile_cleanups",
        "memory_locator_profile_transition_audit",
        "memory_locator_profile_operator_operations",
        "memory_locator_profile_operator_rebuilds",
        "memory_locator_profile_operator_receipts",
        "memory_locator_profile_provider_mutations",
        "memory_locator_profile_queries",
        "memory_locator_profile_reconciliation_operations",
    } <= tables
    chunk_columns = set(
        (
            await connection.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'memory_chunks'
                    """
                )
            )
        ).scalars()
    )
    assert {
        "retrieval_locator",
        "retrieval_source_key",
        "retrieval_projection_generation",
        "retrieval_sequence_ordinal",
        "retrieval_kind",
        "retrieval_version",
        "retrieval_actor_keys_json",
        "retrieval_start_at",
        "retrieval_end_at",
        "retrieval_relative_start_ms",
        "retrieval_relative_end_ms",
        "retrieval_category",
        "retrieval_tags_json",
    } <= chunk_columns
    retrieval_objects = set(
        (
            await connection.execute(
                text(
                    """
                    SELECT trigger_name FROM information_schema.triggers
                    WHERE event_object_schema = current_schema()
                      AND event_object_table = 'memory_chunks'
                    """
                )
            )
        ).scalars()
    )
    assert {
        "trg_memory_chunk_retrieval_fence_v2",
        "trg_memory_chunk_locator_projection_events_v2",
    } <= retrieval_objects
    document_columns = set(
        (
            await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'memory_documents'"
                )
            )
        ).scalars()
    )
    assert "retrieval_projected" in document_columns
    outbox_indexes = set(
        (
            await connection.execute(
                text(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename = 'memory_outbox'
                    """
                )
            )
        ).scalars()
    )
    assert "ix_memory_outbox_active_reconciliation_binding" in outbox_indexes


__all__ = ("assert_locator_retrieval_schema",)
