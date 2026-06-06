CREATE TABLE IF NOT EXISTS memory_suggestions (
    id VARCHAR(80) PRIMARY KEY,
    space_id VARCHAR(80) NOT NULL,
    profile_id VARCHAR(80) NOT NULL,
    candidate_text TEXT NOT NULL,
    kind VARCHAR(80) NOT NULL,
    status VARCHAR(40) NOT NULL,
    source_refs_json JSONB NOT NULL,
    confidence VARCHAR(40) NOT NULL,
    trust_level VARCHAR(40) NOT NULL,
    safe_reason VARCHAR(320) NOT NULL,
    target_fact_id VARCHAR(80),
    target_fact_version INTEGER,
    review_reason VARCHAR(320),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    reviewed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_memory_suggestions_scope_status
    ON memory_suggestions (space_id, profile_id, status);

CREATE INDEX IF NOT EXISTS ix_memory_suggestions_target
    ON memory_suggestions (target_fact_id, status);
