CREATE TABLE IF NOT EXISTS memory_threads (
    id VARCHAR(80) PRIMARY KEY,
    space_id VARCHAR(80) NOT NULL,
    profile_id VARCHAR(80) NOT NULL,
    external_ref VARCHAR(240) NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_thread_external_ref UNIQUE (space_id, profile_id, external_ref)
);

CREATE INDEX IF NOT EXISTS ix_memory_threads_scope_status
    ON memory_threads (space_id, profile_id, status);

CREATE TABLE IF NOT EXISTS memory_episodes (
    id VARCHAR(80) PRIMARY KEY,
    space_id VARCHAR(80) NOT NULL,
    profile_id VARCHAR(80) NOT NULL,
    thread_id VARCHAR(80) NOT NULL,
    source_type VARCHAR(80) NOT NULL,
    source_external_id VARCHAR(240) NOT NULL,
    text TEXT NOT NULL,
    speaker VARCHAR(40) NOT NULL,
    trust_level VARCHAR(40) NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    metadata_json JSONB NOT NULL,
    CONSTRAINT uq_episode_source UNIQUE (space_id, profile_id, thread_id, source_external_id)
);

CREATE INDEX IF NOT EXISTS ix_memory_episodes_thread_status
    ON memory_episodes (thread_id, status);

CREATE TABLE IF NOT EXISTS memory_documents (
    id VARCHAR(80) PRIMARY KEY,
    space_id VARCHAR(80) NOT NULL,
    profile_id VARCHAR(80) NOT NULL,
    thread_id VARCHAR(80),
    title VARCHAR(300) NOT NULL,
    source_type VARCHAR(80) NOT NULL,
    source_external_id VARCHAR(240) NOT NULL,
    content_hash VARCHAR(80) NOT NULL,
    classification VARCHAR(40) NOT NULL DEFAULT 'unknown',
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_document_content_hash_profile_wide
    ON memory_documents (space_id, profile_id, content_hash)
    WHERE thread_id IS NULL AND status != 'deleted';

CREATE UNIQUE INDEX IF NOT EXISTS uq_document_content_hash_thread
    ON memory_documents (space_id, profile_id, thread_id, content_hash)
    WHERE thread_id IS NOT NULL AND status != 'deleted';

CREATE INDEX IF NOT EXISTS ix_memory_documents_scope_status
    ON memory_documents (space_id, profile_id, status);

CREATE TABLE IF NOT EXISTS memory_chunks (
    id VARCHAR(80) PRIMARY KEY,
    space_id VARCHAR(80) NOT NULL,
    profile_id VARCHAR(80) NOT NULL,
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
    classification VARCHAR(40) NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata_json JSONB NOT NULL,
    CONSTRAINT uq_chunk_source_hash UNIQUE (space_id, profile_id, source_hash),
    CONSTRAINT ck_chunk_owner CHECK (
        (document_id IS NOT NULL AND episode_id IS NULL)
        OR (document_id IS NULL AND episode_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_memory_chunks_scope_status
    ON memory_chunks (space_id, profile_id, status);

CREATE INDEX IF NOT EXISTS ix_memory_chunks_thread_status
    ON memory_chunks (thread_id, status);

CREATE INDEX IF NOT EXISTS ix_memory_chunks_document
    ON memory_chunks (document_id, status, sequence);
