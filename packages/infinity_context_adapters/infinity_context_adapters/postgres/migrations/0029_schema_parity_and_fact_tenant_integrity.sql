-- Close historical drift between metadata bootstrap and the SQL migration chain.
ALTER TABLE memory_source_refs
  ADD COLUMN IF NOT EXISTS page_number INTEGER,
  ADD COLUMN IF NOT EXISTS time_start_ms INTEGER,
  ADD COLUMN IF NOT EXISTS time_end_ms INTEGER,
  ADD COLUMN IF NOT EXISTS bbox_json JSONB;

ALTER TABLE memory_suggestions
  ADD COLUMN IF NOT EXISTS operation VARCHAR(40) NOT NULL DEFAULT 'add',
  ADD COLUMN IF NOT EXISTS category VARCHAR(80),
  ADD COLUMN IF NOT EXISTS tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS ttl_policy VARCHAR(80),
  ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS expiry_reason VARCHAR(160),
  ADD COLUMN IF NOT EXISTS created_from_capture_id VARCHAR(80),
  ADD COLUMN IF NOT EXISTS candidate_fingerprint VARCHAR(80),
  ADD COLUMN IF NOT EXISTS review_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb;

-- The former metadata bootstrap used JSONB while early SQL migrations used JSON.
-- Converge both recognized baselines on the ORM's canonical PostgreSQL type.
DO $$
DECLARE
  target RECORD;
BEGIN
  FOR target IN
    SELECT *
    FROM (
      VALUES
        ('memory_anchors', 'aliases_json', '''[]''::jsonb'),
        ('memory_anchors', 'evidence_refs_json', '''[]''::jsonb'),
        ('memory_anchors', 'metadata_json', '''{}''::jsonb'),
        ('memory_asset_extraction_artifacts', 'metadata_json', '''{}''::jsonb'),
        ('memory_asset_extraction_jobs', 'metadata_json', '''{}''::jsonb'),
        ('memory_asset_extraction_jobs', 'result_document_ids_json', '''[]''::jsonb'),
        ('memory_comparison_benchmark_runs', 'cleanup_receipt_json', NULL),
        ('memory_context_link_suggestions', 'metadata_json', '''{}''::jsonb'),
        ('memory_facts', 'tags_json', '''[]''::jsonb'),
        ('memory_usage_records', 'metadata_json', '''{}''::jsonb'),
        ('memory_users', 'metadata_json', NULL)
    ) AS required_jsonb(table_name, column_name, default_sql)
  LOOP
    EXECUTE format(
      'ALTER TABLE %I ALTER COLUMN %I DROP DEFAULT',
      target.table_name,
      target.column_name
    );
    EXECUTE format(
      'ALTER TABLE %I ALTER COLUMN %I TYPE JSONB USING %I::jsonb',
      target.table_name,
      target.column_name,
      target.column_name
    );
    IF target.default_sql IS NOT NULL THEN
      EXECUTE format(
        'ALTER TABLE %I ALTER COLUMN %I SET DEFAULT %s',
        target.table_name,
        target.column_name,
        target.default_sql
      );
    END IF;
  END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS ix_memory_suggestions_expiry
  ON memory_suggestions(space_id, memory_scope_id, status, expires_at);

UPDATE memory_suggestions
SET status = 'expired',
    updated_at = CURRENT_TIMESTAMP,
    reviewed_at = COALESCE(reviewed_at, CURRENT_TIMESTAMP),
    review_reason = COALESCE(review_reason, 'deduped_by_schema_upgrade')
WHERE id IN (
  SELECT id
  FROM (
    SELECT id,
           ROW_NUMBER() OVER (
             PARTITION BY space_id, memory_scope_id, operation,
                          target_fact_id, candidate_fingerprint
             ORDER BY updated_at DESC, created_at DESC, id DESC
           ) AS duplicate_rank
    FROM memory_suggestions
    WHERE status = 'pending' AND candidate_fingerprint IS NOT NULL
  ) ranked
  WHERE duplicate_rank > 1
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_suggestion_fingerprint_no_target
  ON memory_suggestions(space_id, memory_scope_id, operation, candidate_fingerprint)
  WHERE status = 'pending'
    AND candidate_fingerprint IS NOT NULL
    AND target_fact_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_suggestion_fingerprint_target
  ON memory_suggestions(
    space_id, memory_scope_id, operation, target_fact_id, candidate_fingerprint
  )
  WHERE status = 'pending'
    AND candidate_fingerprint IS NOT NULL
    AND target_fact_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS memory_assets (
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

CREATE INDEX IF NOT EXISTS ix_memory_assets_scope_status
  ON memory_assets(space_id, memory_scope_id, status, created_at);
CREATE INDEX IF NOT EXISTS ix_memory_assets_hash_scope
  ON memory_assets(space_id, memory_scope_id, sha256_hex, status);
CREATE INDEX IF NOT EXISTS ix_memory_assets_thread_status
  ON memory_assets(thread_id, status, created_at);

CREATE TABLE IF NOT EXISTS memory_captures (
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

CREATE INDEX IF NOT EXISTS ix_memory_captures_scope_status
  ON memory_captures(space_id, memory_scope_id, status, created_at);
CREATE INDEX IF NOT EXISTS ix_memory_captures_consolidation
  ON memory_captures(space_id, memory_scope_id, consolidation_status, created_at);
CREATE INDEX IF NOT EXISTS ix_memory_captures_source
  ON memory_captures(space_id, memory_scope_id, source_agent, event_type, created_at);

CREATE TABLE IF NOT EXISTS memory_context_links (
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

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_context_link_active
  ON memory_context_links(
    space_id, memory_scope_id, source_type, source_id,
    target_type, target_id, relation_type
  ) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS ix_memory_context_links_source
  ON memory_context_links(space_id, memory_scope_id, source_type, source_id, status);
CREATE INDEX IF NOT EXISTS ix_memory_context_links_target
  ON memory_context_links(space_id, memory_scope_id, target_type, target_id, status);

-- Metadata-created tables omitted server defaults that the SQL chain guarantees.
DO $$
DECLARE
  target RECORD;
BEGIN
  FOR target IN
    SELECT *
    FROM (
      VALUES
        ('memory_anchors', 'confidence', '''medium''::character varying'),
        ('memory_anchors', 'status', '''active''::character varying'),
        ('memory_asset_extraction_jobs', 'attempt_count', '0'),
        ('memory_asset_extraction_jobs', 'status', '''pending''::character varying'),
        ('memory_captures', 'schema_version', '1'),
        ('memory_chunks', 'classification', '''unknown''::character varying'),
        ('memory_chunks', 'status', '''active''::character varying'),
        ('memory_context_link_suggestions', 'confidence', '''medium''::character varying'),
        ('memory_context_link_suggestions', 'score', '0'),
        ('memory_context_link_suggestions', 'status', '''pending''::character varying'),
        ('memory_documents', 'classification', '''unknown''::character varying'),
        ('memory_documents', 'status', '''active''::character varying'),
        ('memory_episodes', 'status', '''active''::character varying'),
        ('memory_facts', 'classification', '''internal''::character varying'),
        ('memory_outbox', 'attempt_count', '0'),
        ('memory_outbox', 'status', '''pending''::character varying'),
        ('memory_outbox', 'workload_class', '''projection''::character varying'),
        ('memory_service_tokens', 'status', '''active''::character varying'),
        ('memory_space_memberships', 'status', '''active''::character varying'),
        ('memory_suggestions', 'operation', '''add''::character varying'),
        ('memory_suggestions', 'review_payload_json', '''{}''::jsonb'),
        ('memory_suggestions', 'tags_json', '''[]''::jsonb'),
        ('memory_threads', 'status', '''active''::character varying'),
        ('memory_users', 'status', '''active''::character varying')
    ) AS required_default(table_name, column_name, default_sql)
  LOOP
    EXECUTE format(
      'ALTER TABLE %I ALTER COLUMN %I SET DEFAULT %s',
      target.table_name,
      target.column_name,
      target.default_sql
    );
  END LOOP;
END $$;

-- Restore the canonical cleanup semantics before attaching drifted/new triggers.
CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_writer_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    registry_state VARCHAR(40);
    registry_projection_cleanup_state VARCHAR(40);
    old_space_id VARCHAR(80);
    new_space_id VARCHAR(80);
    target_space_id VARCHAR(80);
BEGIN
    IF TG_OP <> 'DELETE' THEN
        IF TG_TABLE_NAME = 'memory_spaces' THEN
            new_space_id := NEW.id;
        ELSE
            new_space_id := NEW.space_id;
        END IF;
    END IF;

    IF TG_OP <> 'INSERT' THEN
        IF TG_TABLE_NAME = 'memory_spaces' THEN
            old_space_id := OLD.id;
        ELSE
            old_space_id := OLD.space_id;
        END IF;
    END IF;

    IF TG_OP = 'UPDATE' AND old_space_id IS DISTINCT FROM new_space_id THEN
        IF EXISTS (
            SELECT 1
            FROM memory_comparison_benchmark_runs AS benchmark_run
            WHERE benchmark_run.space_id IN (old_space_id, new_space_id)
        ) THEN
            RAISE EXCEPTION 'benchmark canonical space identity is immutable'
                USING
                    ERRCODE = '23514',
                    CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
        END IF;
    END IF;

    target_space_id := COALESCE(new_space_id, old_space_id);
    BEGIN
        SELECT benchmark_run.state, benchmark_run.projection_cleanup_state
        INTO registry_state, registry_projection_cleanup_state
        FROM memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = target_space_id
        FOR SHARE NOWAIT;
    EXCEPTION
        WHEN lock_not_available THEN
            RAISE EXCEPTION 'benchmark canonical writer fence rejected data mutation'
                USING
                    ERRCODE = '23514',
                    CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END;

    IF registry_state IS NULL THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    IF registry_state = 'active'
        AND registry_projection_cleanup_state = 'unsealed'
    THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE'
        AND TG_TABLE_NAME IN (
            'memory_spaces', 'memory_scopes', 'memory_threads', 'memory_facts',
            'memory_episodes', 'memory_documents', 'memory_chunks'
        )
    THEN
        IF registry_state = 'cleanup_pending'
            AND registry_projection_cleanup_state IN ('pending', 'blocked')
            AND OLD.status = 'active'
            AND NEW.status = 'deleted'
            AND (to_jsonb(OLD) - 'status' - 'updated_at')
                = (to_jsonb(NEW) - 'status' - 'updated_at')
        THEN
            RETURN NEW;
        END IF;
    END IF;

    RAISE EXCEPTION 'benchmark canonical writer fence rejected data mutation'
        USING
            ERRCODE = '23514',
            CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
END;
$$;

-- Restore metadata-bootstrap trigger drift and fence tables absent during migration 0020.
DO $$
DECLARE
  table_name TEXT;
  schema_name TEXT := current_schema();
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'memory_anchors',
    'memory_asset_extraction_jobs',
    'memory_assets',
    'memory_captures',
    'memory_context_link_suggestions',
    'memory_context_links',
    'memory_suggestions'
  ]
  LOOP
    EXECUTE format(
      'DROP TRIGGER IF EXISTS %I ON %I.%I',
      'trg_' || table_name || '_benchmark_writer_fence', schema_name, table_name
    );
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE INSERT OR UPDATE OR DELETE ON %I.%I '
      || 'FOR EACH ROW EXECUTE FUNCTION memory_comparison_enforce_benchmark_writer_fence()',
      'trg_' || table_name || '_benchmark_writer_fence', schema_name, table_name
    );
  END LOOP;
END $$;

ALTER TABLE memory_chunks
  DROP CONSTRAINT IF EXISTS ck_chunk_owner,
  ADD CONSTRAINT ck_chunk_owner CHECK (
    (document_id IS NOT NULL AND episode_id IS NULL)
    OR (document_id IS NULL AND episode_id IS NOT NULL)
  );

-- Validate tenant ownership before installing composite audit references.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM memory_fact_operation_receipts receipt
    LEFT JOIN memory_facts fact
      ON fact.id = receipt.result_fact_id
     AND fact.space_id = receipt.space_id
     AND fact.memory_scope_id = receipt.memory_scope_id
    WHERE fact.id IS NULL
  ) OR EXISTS (
    SELECT 1
    FROM memory_fact_temporal_decisions decision
    LEFT JOIN memory_facts source
      ON source.id = decision.source_fact_id
     AND source.space_id = decision.space_id
     AND source.memory_scope_id = decision.memory_scope_id
    LEFT JOIN memory_facts target
      ON target.id = decision.target_fact_id
     AND target.space_id = decision.space_id
     AND target.memory_scope_id = decision.memory_scope_id
    WHERE source.id IS NULL
       OR (decision.target_fact_id IS NOT NULL AND target.id IS NULL)
  ) OR EXISTS (
    SELECT 1
    FROM memory_fact_temporal_decisions decision
    LEFT JOIN memory_fact_temporal_decisions compensated
      ON compensated.id = decision.compensates_decision_id
     AND compensated.space_id = decision.space_id
     AND compensated.memory_scope_id = decision.memory_scope_id
    WHERE decision.compensates_decision_id IS NOT NULL
      AND compensated.id IS NULL
  ) OR EXISTS (
    SELECT 1
    FROM memory_fact_relations relation
    LEFT JOIN memory_fact_temporal_decisions decision
      ON decision.id = relation.temporal_decision_id
    LEFT JOIN memory_facts source
      ON source.id = relation.source_fact_id
     AND source.space_id = relation.space_id
     AND source.memory_scope_id = relation.memory_scope_id
    LEFT JOIN memory_facts target
      ON target.id = relation.target_fact_id
     AND target.space_id = relation.space_id
     AND target.memory_scope_id = relation.memory_scope_id
    WHERE source.id IS NULL
       OR target.id IS NULL
       OR (
         relation.temporal_decision_id IS NOT NULL
         AND (
           decision.id IS NULL
           OR decision.decision_type <> 'supersede'
           OR decision.space_id <> relation.space_id
           OR decision.memory_scope_id <> relation.memory_scope_id
           OR decision.thread_id IS DISTINCT FROM relation.thread_id
           OR decision.source_fact_id <> relation.source_fact_id
           OR decision.source_fact_version <> relation.source_fact_version
           OR decision.target_fact_id IS DISTINCT FROM relation.target_fact_id
           OR decision.target_fact_version IS DISTINCT FROM relation.target_fact_version
           OR decision.effective_at IS DISTINCT FROM relation.valid_from
           OR relation.relation_type <> 'supersedes'
           OR relation.source_fact_version IS NULL
           OR relation.target_fact_version IS NULL
           OR relation.valid_from IS NULL
         )
       )
  ) THEN
    RAISE EXCEPTION 'fact tenant integrity preflight failed: cross-scope audit reference'
      USING ERRCODE = '23503';
  END IF;
END $$;

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS uq_memory_facts_id_scope,
  ADD CONSTRAINT uq_memory_facts_id_scope
    UNIQUE (id, space_id, memory_scope_id);

ALTER TABLE memory_fact_temporal_decisions
  DROP CONSTRAINT IF EXISTS uq_memory_fact_temporal_decisions_id_scope,
  ADD CONSTRAINT uq_memory_fact_temporal_decisions_id_scope
    UNIQUE (id, space_id, memory_scope_id),
  DROP CONSTRAINT IF EXISTS uq_memory_fact_temporal_decision_relation_identity,
  ADD CONSTRAINT uq_memory_fact_temporal_decision_relation_identity
    UNIQUE (
      id,
      space_id,
      memory_scope_id,
      source_fact_id,
      source_fact_version,
      target_fact_id,
      target_fact_version,
      effective_at
    );

ALTER TABLE memory_fact_operation_receipts
  DROP CONSTRAINT IF EXISTS fk_memory_fact_operation_receipt_fact_scope,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_operation_receipt_fact_version,
  ADD CONSTRAINT fk_memory_fact_operation_receipt_fact_scope
    FOREIGN KEY (result_fact_id, space_id, memory_scope_id)
    REFERENCES memory_facts(id, space_id, memory_scope_id),
  ADD CONSTRAINT fk_memory_fact_operation_receipt_fact_version
    FOREIGN KEY (result_fact_id, result_fact_version)
    REFERENCES memory_fact_versions(fact_id, version);

ALTER TABLE memory_fact_temporal_decisions
  DROP CONSTRAINT IF EXISTS memory_fact_temporal_decisions_compensates_decision_id_fkey,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_temporal_decision_source_scope,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_temporal_decision_target_scope,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_temporal_decision_source_version,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_temporal_decision_target_version,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_temporal_decision_compensation_scope,
  ADD CONSTRAINT fk_memory_fact_temporal_decision_source_scope
    FOREIGN KEY (source_fact_id, space_id, memory_scope_id)
    REFERENCES memory_facts(id, space_id, memory_scope_id),
  ADD CONSTRAINT fk_memory_fact_temporal_decision_target_scope
    FOREIGN KEY (target_fact_id, space_id, memory_scope_id)
    REFERENCES memory_facts(id, space_id, memory_scope_id),
  ADD CONSTRAINT fk_memory_fact_temporal_decision_source_version
    FOREIGN KEY (source_fact_id, source_fact_version)
    REFERENCES memory_fact_versions(fact_id, version),
  ADD CONSTRAINT fk_memory_fact_temporal_decision_target_version
    FOREIGN KEY (target_fact_id, target_fact_version)
    REFERENCES memory_fact_versions(fact_id, version),
  ADD CONSTRAINT fk_memory_fact_temporal_decision_compensation_scope
    FOREIGN KEY (compensates_decision_id, space_id, memory_scope_id)
    REFERENCES memory_fact_temporal_decisions(id, space_id, memory_scope_id);

ALTER TABLE memory_fact_relations
  DROP CONSTRAINT IF EXISTS memory_fact_relations_temporal_decision_id_fkey,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_relation_source_scope,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_relation_target_scope,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_relation_decision_scope,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_relation_source_version,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_relation_target_version,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_relation_temporal_decision_identity,
  ADD CONSTRAINT fk_memory_fact_relation_source_scope
    FOREIGN KEY (source_fact_id, space_id, memory_scope_id)
    REFERENCES memory_facts(id, space_id, memory_scope_id),
  ADD CONSTRAINT fk_memory_fact_relation_target_scope
    FOREIGN KEY (target_fact_id, space_id, memory_scope_id)
    REFERENCES memory_facts(id, space_id, memory_scope_id),
  ADD CONSTRAINT fk_memory_fact_relation_source_version
    FOREIGN KEY (source_fact_id, source_fact_version)
    REFERENCES memory_fact_versions(fact_id, version),
  ADD CONSTRAINT fk_memory_fact_relation_target_version
    FOREIGN KEY (target_fact_id, target_fact_version)
    REFERENCES memory_fact_versions(fact_id, version),
  ADD CONSTRAINT fk_memory_fact_relation_temporal_decision_identity
    FOREIGN KEY (
      temporal_decision_id,
      space_id,
      memory_scope_id,
      source_fact_id,
      source_fact_version,
      target_fact_id,
      target_fact_version,
      valid_from
    )
    REFERENCES memory_fact_temporal_decisions(
      id,
      space_id,
      memory_scope_id,
      source_fact_id,
      source_fact_version,
      target_fact_id,
      target_fact_version,
      effective_at
    );

ALTER TABLE memory_fact_relations
  DROP CONSTRAINT IF EXISTS ck_memory_fact_relation_decision_versions,
  ADD CONSTRAINT ck_memory_fact_relation_decision_versions
    CHECK (
      temporal_decision_id IS NULL
      OR (
        relation_type = 'supersedes'
        AND valid_from IS NOT NULL
        AND source_fact_version IS NOT NULL
        AND target_fact_version IS NOT NULL
      )
    );

DROP INDEX IF EXISTS uq_memory_fact_single_active_predecessor;
CREATE UNIQUE INDEX uq_memory_fact_single_active_predecessor
  ON memory_fact_relations(source_fact_id)
  WHERE relation_type = 'supersedes'
    AND status = 'active'
    AND temporal_decision_id IS NOT NULL;

-- CREATE TABLE IF NOT EXISTS does not retrofit checks on metadata-created tables.
ALTER TABLE memory_fact_operation_receipts
  DROP CONSTRAINT IF EXISTS ck_memory_fact_operation_receipt_result_version,
  ADD CONSTRAINT ck_memory_fact_operation_receipt_result_version
    CHECK (result_fact_version > 0);
ALTER TABLE code_repositories
  DROP CONSTRAINT IF EXISTS ck_code_repository_version_positive,
  ADD CONSTRAINT ck_code_repository_version_positive CHECK (version > 0);
ALTER TABLE code_repository_bindings
  DROP CONSTRAINT IF EXISTS ck_code_repository_binding_version_positive,
  ADD CONSTRAINT ck_code_repository_binding_version_positive CHECK (version > 0);
ALTER TABLE code_scope_authorizations
  DROP CONSTRAINT IF EXISTS ck_code_scope_authorization_version_positive,
  ADD CONSTRAINT ck_code_scope_authorization_version_positive CHECK (version > 0);
