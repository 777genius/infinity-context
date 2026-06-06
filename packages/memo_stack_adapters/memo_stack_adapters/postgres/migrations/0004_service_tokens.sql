CREATE TABLE memory_service_tokens (
  id VARCHAR(80) PRIMARY KEY,
  space_id VARCHAR(80),
  profile_ids_json JSONB,
  description VARCHAR(240) NOT NULL,
  token_hash VARCHAR(80) UNIQUE NOT NULL,
  permissions_json JSONB,
  status VARCHAR(40) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL,
  last_used_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ
);

CREATE INDEX ix_memory_service_tokens_status
  ON memory_service_tokens(status, created_at);
