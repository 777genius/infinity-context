CREATE TABLE IF NOT EXISTS code_repositories (
  id VARCHAR(80) PRIMARY KEY,
  space_id VARCHAR(80) NOT NULL REFERENCES memory_spaces(id),
  provider VARCHAR(40) NOT NULL,
  repo_key VARCHAR(160) NOT NULL,
  safe_label VARCHAR(240),
  remote_url_hash VARCHAR(64),
  default_branch VARCHAR(240),
  monorepo_root VARCHAR(500),
  status VARCHAR(40) NOT NULL,
  version INTEGER NOT NULL CHECK (version > 0),
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT uq_code_repository_key UNIQUE (space_id, repo_key)
);

CREATE INDEX IF NOT EXISTS ix_code_repositories_space_status
  ON code_repositories(space_id, status);

CREATE TABLE IF NOT EXISTS code_repository_aliases (
  id BIGSERIAL PRIMARY KEY,
  repository_id VARCHAR(80) NOT NULL REFERENCES code_repositories(id),
  space_id VARCHAR(80) NOT NULL,
  evidence_kind VARCHAR(40) NOT NULL,
  evidence_digest VARCHAR(64) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT uq_code_repository_alias_evidence
    UNIQUE (space_id, evidence_kind, evidence_digest)
);

CREATE INDEX IF NOT EXISTS ix_code_repository_aliases_repository
  ON code_repository_aliases(repository_id);

ALTER TABLE memory_service_tokens
  ADD COLUMN IF NOT EXISTS repository_id VARCHAR(80);

ALTER TABLE memory_service_tokens
  ADD COLUMN IF NOT EXISTS code_scope_id VARCHAR(96);

CREATE INDEX IF NOT EXISTS ix_memory_service_tokens_repository
  ON memory_service_tokens(repository_id)
  WHERE repository_id IS NOT NULL;
