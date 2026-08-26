-- Separately operated Retrieval V2 maintenance phase.
-- Preconditions: migration 0039 is committed, rollout remains inactive, and the
-- operator holds the maintenance advisory lock used by the companion runner.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_memory_chunks_retrieval_locator_owner
ON memory_chunks (space_id, memory_scope_id, retrieval_locator)
WHERE retrieval_locator IS NOT NULL;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_memory_chunks_retrieval_active_ordinal_owner
ON memory_chunks (
    space_id, memory_scope_id, COALESCE(thread_id, ''),
    retrieval_source_key, retrieval_projection_generation,
    retrieval_sequence_ordinal
)
WHERE retrieval_locator IS NOT NULL
  AND status = 'active'
  AND classification IN ('public', 'internal');

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_memory_chunks_locator_retrieval
ON memory_chunks (
    space_id, memory_scope_id, status, retrieval_source_key,
    retrieval_projection_generation, retrieval_sequence_ordinal
)
WHERE retrieval_locator IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_locator_projection_tombstones_pending
ON memory_locator_projection_tombstones (updated_at, chunk_id)
WHERE legacy_deleted_at IS NULL OR locator_deleted_at IS NULL;
