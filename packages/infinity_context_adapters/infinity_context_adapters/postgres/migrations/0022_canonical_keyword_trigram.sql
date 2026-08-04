CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS ix_memory_chunks_canonical_keyword_trgm
    ON memory_chunks USING GIN (normalized_text gin_trgm_ops)
    WHERE status = 'active' AND classification <> 'restricted';
