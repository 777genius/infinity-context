CREATE TABLE IF NOT EXISTS code_scope_authorizations (
  id VARCHAR(80) PRIMARY KEY,
  repository_id VARCHAR(80) NOT NULL,
  space_id VARCHAR(80) NOT NULL,
  code_scope_id VARCHAR(96) NOT NULL,
  scope_level VARCHAR(40) NOT NULL,
  evidence_digest VARCHAR(64) NOT NULL,
  status VARCHAR(40) NOT NULL,
  version INTEGER NOT NULL CHECK (version > 0),
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT fk_code_scope_authorizations_repository_space
    FOREIGN KEY (repository_id, space_id)
    REFERENCES code_repositories(id, space_id),
  CONSTRAINT uq_code_scope_authorization_repository_scope
    UNIQUE (repository_id, code_scope_id),
  CONSTRAINT ck_code_scope_authorizations_id
    CHECK (code_scope_id ~ '^code-scope-v1-[0-9a-f]{64}$'),
  CONSTRAINT ck_code_scope_authorizations_digest
    CHECK (evidence_digest ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_code_scope_authorizations_level
    CHECK (
      scope_level IN (
        'global',
        'repository',
        'branch',
        'pull_request',
        'commit',
        'package',
        'file',
        'symbol'
      )
    ),
  CONSTRAINT ck_code_scope_authorizations_status
    CHECK (status IN ('active', 'revoked'))
);

CREATE INDEX IF NOT EXISTS ix_code_scope_authorizations_lookup
  ON code_scope_authorizations(repository_id, space_id, code_scope_id, status);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_code_scope_authorizations_id'
  ) THEN
    ALTER TABLE code_scope_authorizations
      ADD CONSTRAINT ck_code_scope_authorizations_id
      CHECK (code_scope_id ~ '^code-scope-v1-[0-9a-f]{64}$');
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_code_scope_authorizations_digest'
  ) THEN
    ALTER TABLE code_scope_authorizations
      ADD CONSTRAINT ck_code_scope_authorizations_digest
      CHECK (evidence_digest ~ '^[0-9a-f]{64}$');
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_code_scope_authorizations_level'
  ) THEN
    ALTER TABLE code_scope_authorizations
      ADD CONSTRAINT ck_code_scope_authorizations_level
      CHECK (
        scope_level IN (
          'global',
          'repository',
          'branch',
          'pull_request',
          'commit',
          'package',
          'file',
          'symbol'
        )
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_code_scope_authorizations_status'
  ) THEN
    ALTER TABLE code_scope_authorizations
      ADD CONSTRAINT ck_code_scope_authorizations_status
      CHECK (status IN ('active', 'revoked'));
  END IF;
END
$$;
