-- Catalog delta produced by origin/main Base.metadata/create_schema over raw 0022.
ALTER TABLE memory_chunks DROP CONSTRAINT ck_chunk_owner;

DROP TRIGGER trg_memory_anchors_benchmark_writer_fence ON memory_anchors;
DROP TRIGGER trg_memory_asset_extraction_jobs_benchmark_writer_fence
  ON memory_asset_extraction_jobs;
DROP TRIGGER trg_memory_context_link_suggestions_benchmark_writer_fence
  ON memory_context_link_suggestions;
DROP TRIGGER trg_memory_suggestions_benchmark_writer_fence ON memory_suggestions;

CREATE TABLE memory_assets (
  id VARCHAR(80) PRIMARY KEY,
  space_id VARCHAR(80) NOT NULL,
  memory_scope_id VARCHAR(80) NOT NULL,
  thread_id VARCHAR(80),
  filename VARCHAR(240) NOT NULL,
  content_type VARCHAR(120) NOT NULL,
  byte_size INTEGER NOT NULL,
  sha256_hex VARCHAR(80) NOT NULL,
  storage_backend VARCHAR(80) NOT NULL,
  storage_key VARCHAR(500) NOT NULL,
  status VARCHAR(40) NOT NULL,
  classification VARCHAR(40) NOT NULL,
  metadata_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_memory_assets_scope_status
  ON memory_assets(space_id, memory_scope_id, status, created_at);
CREATE INDEX ix_memory_assets_hash_scope
  ON memory_assets(space_id, memory_scope_id, sha256_hex, status);
CREATE INDEX ix_memory_assets_thread_status
  ON memory_assets(thread_id, status, created_at);

CREATE TABLE memory_captures (
  id VARCHAR(80) PRIMARY KEY,
  space_id VARCHAR(80) NOT NULL,
  memory_scope_id VARCHAR(80) NOT NULL,
  thread_id VARCHAR(80),
  source_agent VARCHAR(80) NOT NULL,
  source_kind VARCHAR(80) NOT NULL,
  event_type VARCHAR(120) NOT NULL,
  actor_role VARCHAR(40) NOT NULL,
  text_redacted TEXT NOT NULL,
  evidence_refs_json JSONB NOT NULL,
  payload_hash VARCHAR(80) NOT NULL,
  idempotency_key VARCHAR(120) NOT NULL,
  status VARCHAR(40) NOT NULL,
  consolidation_status VARCHAR(40) NOT NULL,
  trust_level VARCHAR(40) NOT NULL,
  source_authority VARCHAR(80) NOT NULL,
  sensitivity VARCHAR(40) NOT NULL,
  data_classification VARCHAR(40) NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  received_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  metadata_json JSONB NOT NULL,
  source_event_id VARCHAR(240),
  source_actor_external_ref VARCHAR(240),
  client_instance_id VARCHAR(160),
  agent_session_external_ref VARCHAR(240),
  turn_external_ref VARCHAR(240),
  parent_capture_id VARCHAR(80),
  sequence_index INTEGER,
  trace_id VARCHAR(120),
  schema_version INTEGER NOT NULL DEFAULT 1,
  parser_version VARCHAR(80) NOT NULL,
  redaction_version VARCHAR(80) NOT NULL,
  admission_version VARCHAR(80) NOT NULL,
  normalization_version VARCHAR(80) NOT NULL,
  policy_version VARCHAR(80) NOT NULL,
  extractor_version VARCHAR(80),
  extractor_prompt_version VARCHAR(80),
  resolver_version VARCHAR(80),
  last_error_code VARCHAR(120),
  last_error_message VARCHAR(400),
  CONSTRAINT uq_capture_idempotency UNIQUE (space_id, idempotency_key)
);
CREATE INDEX ix_memory_captures_scope_status
  ON memory_captures(space_id, memory_scope_id, status, created_at);
CREATE INDEX ix_memory_captures_consolidation
  ON memory_captures(space_id, memory_scope_id, consolidation_status, created_at);
CREATE INDEX ix_memory_captures_source
  ON memory_captures(space_id, memory_scope_id, source_agent, event_type, created_at);

CREATE TABLE memory_context_links (
  id VARCHAR(80) PRIMARY KEY,
  space_id VARCHAR(80) NOT NULL,
  memory_scope_id VARCHAR(80) NOT NULL,
  source_type VARCHAR(80) NOT NULL,
  source_id VARCHAR(160) NOT NULL,
  target_type VARCHAR(80) NOT NULL,
  target_id VARCHAR(160) NOT NULL,
  relation_type VARCHAR(80) NOT NULL,
  confidence VARCHAR(40) NOT NULL,
  reason VARCHAR(320) NOT NULL,
  status VARCHAR(40) NOT NULL,
  metadata_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX uq_memory_context_link_active
  ON memory_context_links(
    space_id, memory_scope_id, source_type, source_id,
    target_type, target_id, relation_type
  ) WHERE status = 'active';
CREATE INDEX ix_memory_context_links_source
  ON memory_context_links(space_id, memory_scope_id, source_type, source_id, status);
CREATE INDEX ix_memory_context_links_target
  ON memory_context_links(space_id, memory_scope_id, target_type, target_id, status);

CREATE TABLE memory_fact_relations (
  id VARCHAR(80) PRIMARY KEY,
  space_id VARCHAR(80) NOT NULL,
  memory_scope_id VARCHAR(80) NOT NULL,
  source_fact_id VARCHAR(80) NOT NULL REFERENCES memory_facts(id),
  target_fact_id VARCHAR(80) NOT NULL REFERENCES memory_facts(id),
  relation_type VARCHAR(80) NOT NULL,
  reason VARCHAR(320) NOT NULL,
  status VARCHAR(40) NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  valid_from TIMESTAMPTZ,
  valid_to TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX uq_memory_fact_relation_active
  ON memory_fact_relations(source_fact_id, target_fact_id, relation_type)
  WHERE status = 'active';
CREATE INDEX ix_memory_fact_relations_source
  ON memory_fact_relations(source_fact_id, status);
CREATE INDEX ix_memory_fact_relations_target
  ON memory_fact_relations(target_fact_id, status);
CREATE INDEX ix_memory_fact_relations_scope
  ON memory_fact_relations(space_id, memory_scope_id, status);
