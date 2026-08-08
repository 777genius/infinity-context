CREATE TABLE IF NOT EXISTS code_repository_bindings (
  id VARCHAR(80) PRIMARY KEY,
  repository_id VARCHAR(80) NOT NULL REFERENCES code_repositories(id),
  space_id VARCHAR(80) NOT NULL,
  version INTEGER NOT NULL CHECK (version > 0),
  grant_hash VARCHAR(64) NOT NULL,
  evidence_json JSONB NOT NULL,
  status VARCHAR(40) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT uq_code_repository_binding_grant UNIQUE (grant_hash)
);

CREATE INDEX IF NOT EXISTS ix_code_repository_bindings_repository_status
  ON code_repository_bindings(repository_id, status);
