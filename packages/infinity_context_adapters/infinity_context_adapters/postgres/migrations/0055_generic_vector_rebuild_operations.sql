-- Durable, globally idempotent progress for bounded generic vector rebuilds.
-- Numbered after the unpublished 0054 locator-profile generation migration so
-- both forward-only changes can be integrated without rewriting either file.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';

CREATE TABLE public.memory_vector_rebuild_operations (
    operation_id VARCHAR(80) PRIMARY KEY,
    space_id VARCHAR(80) NOT NULL,
    memory_scope_id VARCHAR(80) NOT NULL,
    status VARCHAR(20) NOT NULL,
    canonical_watermark BIGINT NOT NULL,
    dead_event_watermark BIGINT NOT NULL,
    cursor_watermark BIGINT NOT NULL DEFAULT 0,
    cursor_chunk_id VARCHAR(80),
    processed_count BIGINT NOT NULL DEFAULT 0,
    failed_count BIGINT NOT NULL DEFAULT 0,
    batch_size INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CONSTRAINT ck_vector_rebuild_operation_status
        CHECK (status IN ('running', 'complete')),
    CONSTRAINT ck_vector_rebuild_operation_watermarks
        CHECK (
            canonical_watermark >= 0
            AND dead_event_watermark >= 0
            AND cursor_watermark >= 0
            AND cursor_watermark <= canonical_watermark
        ),
    CONSTRAINT ck_vector_rebuild_operation_counts
        CHECK (processed_count >= 0 AND failed_count >= 0),
    CONSTRAINT ck_vector_rebuild_operation_batch_size
        CHECK (batch_size BETWEEN 1 AND 256)
);

CREATE INDEX ix_vector_rebuild_operation_scope_state
    ON public.memory_vector_rebuild_operations (
        space_id,
        memory_scope_id,
        status,
        updated_at
    );
