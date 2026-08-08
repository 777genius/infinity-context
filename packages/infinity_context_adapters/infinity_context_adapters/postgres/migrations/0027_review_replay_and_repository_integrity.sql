CREATE TABLE IF NOT EXISTS suggestion_resolution_receipts (
  id VARCHAR(64) PRIMARY KEY,
  suggestion_id VARCHAR(80) NOT NULL REFERENCES memory_suggestions(id),
  operation VARCHAR(80) NOT NULL,
  idempotency_key VARCHAR(160) NOT NULL,
  request_fingerprint VARCHAR(64) NOT NULL,
  result_suggestion_json JSONB NOT NULL,
  result_fact_json JSONB,
  indexing_status VARCHAR(40),
  affected_fact_ids_json JSONB NOT NULL,
  affected_fact_versions_json JSONB NOT NULL,
  temporal_decision_id VARCHAR(80) REFERENCES memory_fact_temporal_decisions(id),
  relation_id VARCHAR(80) REFERENCES memory_fact_relations(id),
  outbox_message_ids_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT uq_suggestion_resolution_receipt_idempotency
    UNIQUE (suggestion_id, operation, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_suggestion_resolution_receipts_created
  ON suggestion_resolution_receipts(created_at);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM memory_facts fact
    LEFT JOIN code_repositories repository
      ON repository.id = fact.repository_id
     AND repository.space_id = fact.space_id
    WHERE fact.repository_id IS NOT NULL
      AND repository.id IS NULL
  ) THEN
    RAISE EXCEPTION
      USING ERRCODE = '23503',
            MESSAGE = 'repository integrity preflight failed: memory_facts contains an unknown or cross-space repository_id';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM memory_service_tokens token
    LEFT JOIN code_repositories repository
      ON repository.id = token.repository_id
     AND repository.space_id = token.space_id
    WHERE token.repository_id IS NOT NULL
      AND repository.id IS NULL
  ) THEN
    RAISE EXCEPTION
      USING ERRCODE = '23503',
            MESSAGE = 'repository integrity preflight failed: memory_service_tokens contains an unknown or cross-space repository_id';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM code_repository_aliases alias
    LEFT JOIN code_repositories repository
      ON repository.id = alias.repository_id
     AND repository.space_id = alias.space_id
    WHERE repository.id IS NULL
  ) THEN
    RAISE EXCEPTION
      USING ERRCODE = '23503',
            MESSAGE = 'repository integrity preflight failed: code_repository_aliases contains a cross-space repository_id';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM code_repository_bindings binding
    LEFT JOIN code_repositories repository
      ON repository.id = binding.repository_id
     AND repository.space_id = binding.space_id
    WHERE repository.id IS NULL
  ) THEN
    RAISE EXCEPTION
      USING ERRCODE = '23503',
            MESSAGE = 'repository integrity preflight failed: code_repository_bindings contains a cross-space repository_id';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM memory_fact_operation_receipts receipt
    LEFT JOIN memory_facts fact ON fact.id = receipt.result_fact_id
    WHERE fact.id IS NULL
  ) THEN
    RAISE EXCEPTION
      USING ERRCODE = '23503',
            MESSAGE = 'fact integrity preflight failed: memory_fact_operation_receipts contains an unknown result_fact_id';
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_code_repository_id_space'
  ) THEN
    ALTER TABLE code_repositories
      ADD CONSTRAINT uq_code_repository_id_space UNIQUE (id, space_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_memory_facts_repository_space'
  ) THEN
    ALTER TABLE memory_facts
      ADD CONSTRAINT fk_memory_facts_repository_space
      FOREIGN KEY (repository_id, space_id)
      REFERENCES code_repositories(id, space_id)
      NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_memory_service_tokens_repository_space'
  ) THEN
    ALTER TABLE memory_service_tokens
      ADD CONSTRAINT fk_memory_service_tokens_repository_space
      FOREIGN KEY (repository_id, space_id)
      REFERENCES code_repositories(id, space_id)
      NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_code_repository_aliases_repository_space'
  ) THEN
    ALTER TABLE code_repository_aliases
      ADD CONSTRAINT fk_code_repository_aliases_repository_space
      FOREIGN KEY (repository_id, space_id)
      REFERENCES code_repositories(id, space_id)
      NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_code_repository_bindings_repository_space'
  ) THEN
    ALTER TABLE code_repository_bindings
      ADD CONSTRAINT fk_code_repository_bindings_repository_space
      FOREIGN KEY (repository_id, space_id)
      REFERENCES code_repositories(id, space_id)
      NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_memory_fact_operation_receipts_fact'
  ) THEN
    ALTER TABLE memory_fact_operation_receipts
      ADD CONSTRAINT fk_memory_fact_operation_receipts_fact
      FOREIGN KEY (result_fact_id)
      REFERENCES memory_facts(id)
      NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_memory_service_tokens_repository_space_pair'
  ) THEN
    ALTER TABLE memory_service_tokens
      ADD CONSTRAINT ck_memory_service_tokens_repository_space_pair
      CHECK (repository_id IS NULL OR space_id IS NOT NULL)
      NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_memory_service_tokens_code_scope_pair'
  ) THEN
    ALTER TABLE memory_service_tokens
      ADD CONSTRAINT ck_memory_service_tokens_code_scope_pair
      CHECK (code_scope_id IS NULL OR repository_id IS NOT NULL)
      NOT VALID;
  END IF;
END
$$;

ALTER TABLE memory_facts
  VALIDATE CONSTRAINT fk_memory_facts_repository_space;
ALTER TABLE memory_service_tokens
  VALIDATE CONSTRAINT fk_memory_service_tokens_repository_space;
ALTER TABLE code_repository_aliases
  VALIDATE CONSTRAINT fk_code_repository_aliases_repository_space;
ALTER TABLE code_repository_bindings
  VALIDATE CONSTRAINT fk_code_repository_bindings_repository_space;
ALTER TABLE memory_fact_operation_receipts
  VALIDATE CONSTRAINT fk_memory_fact_operation_receipts_fact;
ALTER TABLE memory_service_tokens
  VALIDATE CONSTRAINT ck_memory_service_tokens_repository_space_pair;
ALTER TABLE memory_service_tokens
  VALIDATE CONSTRAINT ck_memory_service_tokens_code_scope_pair;
