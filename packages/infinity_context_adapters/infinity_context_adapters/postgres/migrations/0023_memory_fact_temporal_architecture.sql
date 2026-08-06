ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS temporal_kind VARCHAR(20) NOT NULL DEFAULT 'state';

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ;

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS occurred_from TIMESTAMPTZ;

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS occurred_to TIMESTAMPTZ;

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS temporal_basis VARCHAR(80) NOT NULL DEFAULT 'migrated_legacy';

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS temporal_precision VARCHAR(40) NOT NULL DEFAULT 'unknown';

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS last_confirmed_at TIMESTAMPTZ;

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS confirmation_basis VARCHAR(120);

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS purge_after TIMESTAMPTZ;

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS epistemic_mode VARCHAR(40) NOT NULL DEFAULT 'world_claim';

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS asserted_by VARCHAR(160);

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS perspective_subject VARCHAR(160);

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS repository_id VARCHAR(80);

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS code_scope_id VARCHAR(96);

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS evidence_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_confidence_values;

ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_confidence_values
  CHECK (confidence IN ('low', 'medium', 'high'));

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_trust_level_values;

ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_trust_level_values
  CHECK (trust_level IN ('low', 'medium', 'high'));

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_classification_values;

ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_classification_values
  CHECK (classification IN ('public', 'internal', 'restricted', 'unknown'));

UPDATE memory_facts
SET observed_at = created_at
WHERE observed_at IS NULL;

UPDATE memory_facts
SET valid_from = created_at
WHERE temporal_kind = 'state'
  AND status = 'active'
  AND temporal_basis = 'migrated_legacy'
  AND valid_from IS NULL;

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_temporal_kind;
ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_temporal_kind
  CHECK (temporal_kind IN ('state', 'event', 'timeless'));

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_temporal_shape;
ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_temporal_shape
  CHECK (
    (temporal_kind = 'state' AND occurred_from IS NULL AND occurred_to IS NULL) OR
    (
      temporal_kind = 'event' AND valid_from IS NULL AND valid_to IS NULL AND
      occurred_from IS NOT NULL
    ) OR
    (
      temporal_kind = 'timeless' AND valid_from IS NULL AND valid_to IS NULL AND
      occurred_from IS NULL AND occurred_to IS NULL
    )
  );

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_validity_order;
ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_validity_order
  CHECK (valid_to IS NULL OR (valid_from IS NOT NULL AND valid_to > valid_from));

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_occurrence_order;
ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_occurrence_order
  CHECK (
    occurred_to IS NULL OR
    (occurred_from IS NOT NULL AND occurred_to > occurred_from)
  );

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_confirmation_pair;
ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_confirmation_pair
  CHECK ((last_confirmed_at IS NULL) = (confirmation_basis IS NULL));

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_retention_order;
ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_retention_order
  CHECK (purge_after IS NULL OR expires_at IS NULL OR purge_after >= expires_at);

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_code_scope_pair;
ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_code_scope_pair
  CHECK (code_scope_id IS NULL OR repository_id IS NOT NULL);

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_epistemic_mode;
ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_epistemic_mode
  CHECK (epistemic_mode IN ('world_claim', 'perspective', 'hypothesis'));

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS ck_memory_facts_perspective_subject;
ALTER TABLE memory_facts
  ADD CONSTRAINT ck_memory_facts_perspective_subject
  CHECK (
    (epistemic_mode = 'perspective' AND perspective_subject IS NOT NULL) OR
    (epistemic_mode <> 'perspective' AND perspective_subject IS NULL)
  );

ALTER TABLE memory_fact_versions
  ADD COLUMN IF NOT EXISTS snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE memory_outbox
  ADD COLUMN IF NOT EXISTS message_key VARCHAR(160);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_outbox_message_key
  ON memory_outbox(message_key)
  WHERE message_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_memory_facts_temporal_selection
  ON memory_facts (
    space_id,
    memory_scope_id,
    status,
    temporal_kind,
    valid_from,
    valid_to
  );

CREATE INDEX IF NOT EXISTS ix_memory_facts_code_scope
  ON memory_facts (
    space_id,
    memory_scope_id,
    repository_id,
    code_scope_id,
    status
  );

CREATE TABLE IF NOT EXISTS memory_fact_operation_receipts (
  id VARCHAR(64) PRIMARY KEY,
  space_id VARCHAR(80) NOT NULL,
  memory_scope_id VARCHAR(80) NOT NULL,
  thread_id VARCHAR(80),
  thread_scope_key VARCHAR(87) NOT NULL,
  idempotency_key VARCHAR(160) NOT NULL,
  operation VARCHAR(40) NOT NULL,
  request_fingerprint VARCHAR(64) NOT NULL,
  result_fact_id VARCHAR(80) NOT NULL,
  result_fact_version INTEGER NOT NULL CHECK (result_fact_version > 0),
  result_snapshot_json JSONB NOT NULL,
  outbox_message_ids_json JSONB NOT NULL,
  tombstone_id VARCHAR(80),
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT ck_memory_fact_operation_receipt_thread_scope_key
    CHECK (
      (thread_id IS NULL AND thread_scope_key = 'global') OR
      (thread_id IS NOT NULL AND thread_scope_key = 'thread:' || thread_id)
    ),
  CONSTRAINT uq_memory_fact_operation_receipt_idempotency
    UNIQUE (
      space_id,
      memory_scope_id,
      thread_scope_key,
      operation,
      idempotency_key
    )
);

CREATE INDEX IF NOT EXISTS ix_memory_fact_operation_receipts_fact
  ON memory_fact_operation_receipts(result_fact_id, created_at);

CREATE TABLE IF NOT EXISTS memory_fact_temporal_decisions (
  id VARCHAR(80) PRIMARY KEY,
  decision_type VARCHAR(40) NOT NULL,
  space_id VARCHAR(80) NOT NULL,
  memory_scope_id VARCHAR(80) NOT NULL,
  thread_id VARCHAR(80),
  thread_scope_key VARCHAR(87) NOT NULL,
  source_fact_id VARCHAR(80) NOT NULL REFERENCES memory_facts(id),
  source_fact_version INTEGER NOT NULL CHECK (source_fact_version > 0),
  target_fact_id VARCHAR(80) REFERENCES memory_facts(id),
  target_fact_version INTEGER CHECK (target_fact_version > 0),
  effective_at TIMESTAMPTZ NOT NULL,
  evidence_refs_json JSONB NOT NULL,
  actor_id VARCHAR(160) NOT NULL,
  policy_version VARCHAR(80) NOT NULL,
  reason_code VARCHAR(120) NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL,
  idempotency_key VARCHAR(160) NOT NULL,
  compensates_decision_id VARCHAR(80) REFERENCES memory_fact_temporal_decisions(id),
  outbox_message_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  CONSTRAINT ck_memory_fact_temporal_decision_target_pair
    CHECK ((target_fact_id IS NULL) = (target_fact_version IS NULL)),
  CONSTRAINT ck_memory_fact_temporal_decision_distinct_facts
    CHECK (target_fact_id IS NULL OR source_fact_id <> target_fact_id),
  CONSTRAINT ck_memory_fact_temporal_decision_thread_scope_key
    CHECK (
      (thread_id IS NULL AND thread_scope_key = 'global') OR
      (thread_id IS NOT NULL AND thread_scope_key = 'thread:' || thread_id)
    ),
  CONSTRAINT uq_memory_fact_temporal_decision_idempotency
    UNIQUE (
      space_id,
      memory_scope_id,
      thread_scope_key,
      decision_type,
      idempotency_key
    )
);

CREATE INDEX IF NOT EXISTS ix_memory_fact_temporal_decisions_source
  ON memory_fact_temporal_decisions(source_fact_id, applied_at);

CREATE INDEX IF NOT EXISTS ix_memory_fact_temporal_decisions_target
  ON memory_fact_temporal_decisions(target_fact_id, applied_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_fact_temporal_decision_compensation
  ON memory_fact_temporal_decisions(compensates_decision_id)
  WHERE compensates_decision_id IS NOT NULL;

-- Older deployments created this table through SQLAlchemy metadata rather than
-- the SQL migration chain. Keep 0023 deployable for both installation paths.
CREATE TABLE IF NOT EXISTS memory_fact_relations (
  id VARCHAR(80) PRIMARY KEY,
  space_id VARCHAR(80) NOT NULL,
  memory_scope_id VARCHAR(80) NOT NULL,
  thread_id VARCHAR(80),
  source_fact_id VARCHAR(80) NOT NULL REFERENCES memory_facts(id),
  target_fact_id VARCHAR(80) NOT NULL REFERENCES memory_facts(id),
  relation_type VARCHAR(80) NOT NULL,
  reason VARCHAR(320) NOT NULL,
  status VARCHAR(40) NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  valid_from TIMESTAMPTZ,
  valid_to TIMESTAMPTZ,
  source_fact_version INTEGER,
  target_fact_version INTEGER,
  temporal_decision_id VARCHAR(80),
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE memory_fact_relations
  ADD COLUMN IF NOT EXISTS thread_id VARCHAR(80);

ALTER TABLE memory_fact_relations
  ADD COLUMN IF NOT EXISTS source_fact_version INTEGER;

ALTER TABLE memory_fact_relations
  ADD COLUMN IF NOT EXISTS target_fact_version INTEGER;

ALTER TABLE memory_fact_relations
  ADD COLUMN IF NOT EXISTS temporal_decision_id VARCHAR(80);

-- Legacy generic supersession edges have no atomic fact/decision audit. Preserve
-- them for history, but never let them participate in the canonical active graph.
UPDATE memory_fact_relations
SET status = 'deleted',
    updated_at = GREATEST(updated_at, created_at)
WHERE relation_type = 'supersedes'
  AND status = 'active'
  AND temporal_decision_id IS NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_memory_fact_relation_temporal_decision'
  ) THEN
    ALTER TABLE memory_fact_relations
      ADD CONSTRAINT fk_memory_fact_relation_temporal_decision
      FOREIGN KEY (temporal_decision_id)
      REFERENCES memory_fact_temporal_decisions(id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_fact_relation_active
  ON memory_fact_relations(source_fact_id, target_fact_id, relation_type)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ix_memory_fact_relations_source
  ON memory_fact_relations(source_fact_id, status);

CREATE INDEX IF NOT EXISTS ix_memory_fact_relations_target
  ON memory_fact_relations(target_fact_id, status);

CREATE INDEX IF NOT EXISTS ix_memory_fact_relations_scope
  ON memory_fact_relations(space_id, memory_scope_id, status);

DROP INDEX IF EXISTS uq_memory_fact_single_active_supersession;

CREATE UNIQUE INDEX uq_memory_fact_single_active_supersession
  ON memory_fact_relations(target_fact_id)
  WHERE relation_type = 'supersedes'
    AND status = 'active'
    AND temporal_decision_id IS NOT NULL;

CREATE UNIQUE INDEX uq_memory_fact_single_active_predecessor
  ON memory_fact_relations(source_fact_id)
  WHERE relation_type = 'supersedes'
    AND status = 'active'
    AND temporal_decision_id IS NOT NULL;
