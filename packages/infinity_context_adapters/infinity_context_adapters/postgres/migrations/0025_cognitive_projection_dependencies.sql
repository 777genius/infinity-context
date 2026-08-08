CREATE TABLE IF NOT EXISTS memory_cognitive_projections (
  id VARCHAR(80) PRIMARY KEY,
  space_id VARCHAR(80) NOT NULL,
  memory_scope_id VARCHAR(80) NOT NULL,
  thread_id VARCHAR(80),
  kind VARCHAR(40) NOT NULL,
  derivation_origin VARCHAR(40) NOT NULL,
  content TEXT NOT NULL,
  content_hash VARCHAR(80) NOT NULL,
  projection_version VARCHAR(80) NOT NULL,
  confidence DOUBLE PRECISION NOT NULL,
  valid_from TIMESTAMPTZ,
  valid_to TIMESTAMPTZ,
  state VARCHAR(40) NOT NULL DEFAULT 'active',
  invalidated_at TIMESTAMPTZ,
  invalidation_reason VARCHAR(120),
  invalidation_event_id VARCHAR(160),
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_memory_cognitive_projections_scope_state
  ON memory_cognitive_projections(space_id, memory_scope_id, state, created_at);

CREATE TABLE IF NOT EXISTS memory_cognitive_dependencies (
  id BIGSERIAL PRIMARY KEY,
  projection_id VARCHAR(80) NOT NULL REFERENCES memory_cognitive_projections(id),
  space_id VARCHAR(80) NOT NULL,
  memory_scope_id VARCHAR(80) NOT NULL,
  thread_id VARCHAR(80),
  evidence_type VARCHAR(80) NOT NULL,
  evidence_id VARCHAR(160) NOT NULL,
  evidence_version INTEGER NOT NULL CHECK (evidence_version > 0),
  citation VARCHAR(500) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT uq_memory_cognitive_dependency
    UNIQUE (projection_id, evidence_type, evidence_id, evidence_version)
);

CREATE INDEX IF NOT EXISTS ix_memory_cognitive_dependencies_source
  ON memory_cognitive_dependencies(
    space_id,
    memory_scope_id,
    evidence_type,
    evidence_id
  );
