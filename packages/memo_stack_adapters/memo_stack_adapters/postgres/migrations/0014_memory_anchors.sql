CREATE TABLE IF NOT EXISTS memory_anchors (
    id VARCHAR(80) PRIMARY KEY,
    space_id VARCHAR(80) NOT NULL,
    memory_scope_id VARCHAR(80) NOT NULL,
    kind VARCHAR(40) NOT NULL,
    normalized_key VARCHAR(160) NOT NULL,
    label VARCHAR(240) NOT NULL,
    aliases_json JSON NOT NULL DEFAULT '[]',
    description VARCHAR(500),
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    confidence VARCHAR(40) NOT NULL DEFAULT 'medium',
    evidence_refs_json JSON NOT NULL DEFAULT '[]',
    observed_at TIMESTAMPTZ,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    metadata_json JSON NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_anchor_active_key
ON memory_anchors(space_id, memory_scope_id, kind, normalized_key)
WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ix_memory_anchors_scope_kind
ON memory_anchors(space_id, memory_scope_id, kind, status, updated_at);
