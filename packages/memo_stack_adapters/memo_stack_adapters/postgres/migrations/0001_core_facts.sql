CREATE TABLE memory_spaces (
  id VARCHAR(80) PRIMARY KEY,
  slug VARCHAR(160) NOT NULL UNIQUE,
  name VARCHAR(240) NOT NULL,
  status VARCHAR(40) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE memory_profiles (
  id VARCHAR(80) PRIMARY KEY,
  space_id VARCHAR(80) NOT NULL REFERENCES memory_spaces(id),
  external_ref VARCHAR(200) NOT NULL,
  name VARCHAR(240) NOT NULL,
  status VARCHAR(40) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT uq_profile_external_ref UNIQUE (space_id, external_ref)
);

CREATE TABLE memory_facts (
  id VARCHAR(80) PRIMARY KEY,
  space_id VARCHAR(80) NOT NULL,
  profile_id VARCHAR(80) NOT NULL,
  thread_id VARCHAR(80),
  kind VARCHAR(80) NOT NULL,
  text TEXT NOT NULL,
  status VARCHAR(40) NOT NULL,
  confidence VARCHAR(40) NOT NULL,
  trust_level VARCHAR(40) NOT NULL,
  classification VARCHAR(40) NOT NULL DEFAULT 'internal',
  version INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT ck_fact_version_positive CHECK (version > 0)
);

CREATE INDEX ix_memory_facts_scope_status
  ON memory_facts(space_id, profile_id, status, updated_at);

CREATE TABLE memory_source_refs (
  id SERIAL PRIMARY KEY,
  fact_id VARCHAR(80) NOT NULL REFERENCES memory_facts(id),
  fact_version INTEGER NOT NULL,
  source_type VARCHAR(80) NOT NULL,
  source_id VARCHAR(160) NOT NULL,
  chunk_id VARCHAR(160),
  char_start INTEGER,
  char_end INTEGER,
  quote_preview VARCHAR(240)
);

CREATE INDEX ix_memory_source_refs_fact
  ON memory_source_refs(fact_id, fact_version);

CREATE TABLE memory_fact_versions (
  id SERIAL PRIMARY KEY,
  fact_id VARCHAR(80) NOT NULL REFERENCES memory_facts(id),
  version INTEGER NOT NULL,
  text TEXT NOT NULL,
  status VARCHAR(40) NOT NULL,
  source_refs_json JSONB NOT NULL,
  reason VARCHAR(240),
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT uq_fact_version UNIQUE (fact_id, version)
);

CREATE TABLE memory_outbox (
  id SERIAL PRIMARY KEY,
  event_type VARCHAR(120) NOT NULL,
  aggregate_type VARCHAR(80) NOT NULL,
  aggregate_id VARCHAR(80) NOT NULL,
  aggregate_version INTEGER,
  payload_json JSONB NOT NULL,
  status VARCHAR(40) NOT NULL DEFAULT 'pending',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMPTZ NOT NULL,
  last_safe_error VARCHAR(400),
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_memory_outbox_status_next
  ON memory_outbox(status, next_attempt_at);

CREATE TABLE memory_idempotency_records (
  id SERIAL PRIMARY KEY,
  space_id VARCHAR(80) NOT NULL,
  key VARCHAR(240) NOT NULL,
  fingerprint VARCHAR(80) NOT NULL,
  result_type VARCHAR(80) NOT NULL,
  result_id VARCHAR(80) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT uq_idempotency_space_key UNIQUE (space_id, key)
);
