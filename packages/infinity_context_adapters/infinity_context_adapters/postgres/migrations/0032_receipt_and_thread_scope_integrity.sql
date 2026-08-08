LOCK TABLE
  memory_facts,
  memory_fact_versions,
  memory_suggestions,
  memory_fact_temporal_decisions,
  memory_fact_relations,
  memory_fact_operation_receipts,
  suggestion_resolution_receipts
IN SHARE ROW EXCLUSIVE MODE;

ALTER TABLE memory_facts
  ADD COLUMN IF NOT EXISTS thread_scope_key VARCHAR(87)
    GENERATED ALWAYS AS (
      CASE
        WHEN thread_id IS NULL THEN 'global'
        ELSE 'thread:' || thread_id
      END
    ) STORED NOT NULL;

ALTER TABLE memory_fact_relations
  ADD COLUMN IF NOT EXISTS thread_scope_key VARCHAR(87)
    GENERATED ALWAYS AS (
      CASE
        WHEN thread_id IS NULL THEN 'global'
        ELSE 'thread:' || thread_id
      END
    ) STORED NOT NULL;

-- Origin-main relations predate relation thread ownership. Recover it only for
-- unaudited rows whose exact source and target facts prove the same scope.
UPDATE memory_fact_relations relation
SET thread_id = source.thread_id
FROM memory_facts source, memory_facts target
WHERE relation.temporal_decision_id IS NULL
  AND relation.thread_id IS NULL
  AND source.id = relation.source_fact_id
  AND source.space_id = relation.space_id
  AND source.memory_scope_id = relation.memory_scope_id
  AND target.id = relation.target_fact_id
  AND target.space_id = relation.space_id
  AND target.memory_scope_id = relation.memory_scope_id
  AND source.thread_id IS NOT DISTINCT FROM target.thread_id;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM memory_fact_operation_receipts receipt
    LEFT JOIN memory_facts fact
      ON fact.id = receipt.result_fact_id
     AND fact.space_id = receipt.space_id
     AND fact.memory_scope_id = receipt.memory_scope_id
     AND fact.thread_scope_key = receipt.thread_scope_key
    WHERE fact.id IS NULL
  ) OR EXISTS (
    SELECT 1
    FROM memory_fact_temporal_decisions decision
    LEFT JOIN memory_facts source
      ON source.id = decision.source_fact_id
     AND source.space_id = decision.space_id
     AND source.memory_scope_id = decision.memory_scope_id
     AND source.thread_scope_key = decision.thread_scope_key
    LEFT JOIN memory_facts target
      ON target.id = decision.target_fact_id
     AND target.space_id = decision.space_id
     AND target.memory_scope_id = decision.memory_scope_id
     AND target.thread_scope_key = decision.thread_scope_key
    WHERE source.id IS NULL
       OR (decision.target_fact_id IS NOT NULL AND target.id IS NULL)
  ) OR EXISTS (
    SELECT 1
    FROM memory_fact_temporal_decisions decision
    LEFT JOIN memory_fact_temporal_decisions compensated
      ON compensated.id = decision.compensates_decision_id
     AND compensated.space_id = decision.space_id
     AND compensated.memory_scope_id = decision.memory_scope_id
     AND compensated.thread_scope_key = decision.thread_scope_key
    WHERE decision.compensates_decision_id IS NOT NULL
      AND compensated.id IS NULL
  ) OR EXISTS (
    SELECT 1
    FROM memory_fact_relations relation
    LEFT JOIN memory_facts source
      ON source.id = relation.source_fact_id
     AND source.space_id = relation.space_id
     AND source.memory_scope_id = relation.memory_scope_id
     AND source.thread_scope_key = relation.thread_scope_key
    LEFT JOIN memory_facts target
      ON target.id = relation.target_fact_id
     AND target.space_id = relation.space_id
     AND target.memory_scope_id = relation.memory_scope_id
     AND target.thread_scope_key = relation.thread_scope_key
    LEFT JOIN memory_fact_temporal_decisions decision
      ON decision.id = relation.temporal_decision_id
     AND decision.space_id = relation.space_id
     AND decision.memory_scope_id = relation.memory_scope_id
     AND decision.thread_scope_key = relation.thread_scope_key
    WHERE source.id IS NULL
       OR target.id IS NULL
       OR (relation.temporal_decision_id IS NOT NULL AND decision.id IS NULL)
  ) THEN
    RAISE EXCEPTION 'fact thread scope integrity preflight failed'
      USING ERRCODE = '23503';
  END IF;
END $$;

-- Revalidate the immutable snapshots while concurrent writers are excluded.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM memory_fact_operation_receipts receipt
    WHERE jsonb_typeof(receipt.result_snapshot_json) IS DISTINCT FROM 'object'
       OR jsonb_typeof(receipt.result_snapshot_json -> 'schema_version')
            IS DISTINCT FROM 'number'
       OR receipt.result_snapshot_json #>> '{schema_version}' IS DISTINCT FROM '1'
       OR jsonb_typeof(receipt.result_snapshot_json #> '{identity,fact_id}')
            IS DISTINCT FROM 'string'
       OR jsonb_typeof(receipt.result_snapshot_json #> '{identity,space_id}')
            IS DISTINCT FROM 'string'
       OR jsonb_typeof(receipt.result_snapshot_json #> '{identity,memory_scope_id}')
            IS DISTINCT FROM 'string'
       OR COALESCE(
            jsonb_typeof(receipt.result_snapshot_json #> '{identity,thread_id}'),
            'missing'
          ) NOT IN ('string', 'null')
       OR jsonb_typeof(receipt.result_snapshot_json #> '{visibility,version}')
            IS DISTINCT FROM 'number'
       OR receipt.result_snapshot_json #>> '{identity,fact_id}'
            IS DISTINCT FROM receipt.result_fact_id
       OR receipt.result_snapshot_json #>> '{identity,space_id}'
            IS DISTINCT FROM receipt.space_id
       OR receipt.result_snapshot_json #>> '{identity,memory_scope_id}'
            IS DISTINCT FROM receipt.memory_scope_id
       OR receipt.result_snapshot_json #>> '{identity,thread_id}'
            IS DISTINCT FROM receipt.thread_id
       OR receipt.result_snapshot_json #>> '{visibility,version}'
            IS DISTINCT FROM receipt.result_fact_version::TEXT
  ) THEN
    RAISE EXCEPTION 'fact operation receipt snapshot identity preflight failed'
      USING ERRCODE = '23514';
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM suggestion_resolution_receipts receipt
    WHERE jsonb_typeof(receipt.result_suggestion_json) IS DISTINCT FROM 'object'
       OR jsonb_typeof(receipt.result_suggestion_json -> 'schema_version')
            IS DISTINCT FROM 'number'
       OR receipt.result_suggestion_json #>> '{schema_version}' IS DISTINCT FROM '1'
       OR jsonb_typeof(receipt.result_suggestion_json -> 'id')
            IS DISTINCT FROM 'string'
       OR jsonb_typeof(receipt.result_suggestion_json -> 'space_id')
            IS DISTINCT FROM 'string'
       OR jsonb_typeof(receipt.result_suggestion_json -> 'memory_scope_id')
            IS DISTINCT FROM 'string'
       OR receipt.result_suggestion_json #>> '{id}'
            IS DISTINCT FROM receipt.suggestion_id
       OR receipt.result_suggestion_json #>> '{space_id}'
            IS DISTINCT FROM receipt.space_id
       OR receipt.result_suggestion_json #>> '{memory_scope_id}'
            IS DISTINCT FROM receipt.memory_scope_id
  ) OR EXISTS (
    SELECT 1
    FROM suggestion_resolution_receipts receipt
    LEFT JOIN memory_facts result_fact
      ON result_fact.id = receipt.result_fact_id
     AND result_fact.space_id = receipt.space_id
     AND result_fact.memory_scope_id = receipt.memory_scope_id
    WHERE receipt.result_fact_json IS NOT NULL
      AND (
        jsonb_typeof(receipt.result_fact_json) IS DISTINCT FROM 'object'
        OR jsonb_typeof(receipt.result_fact_json -> 'schema_version')
             IS DISTINCT FROM 'number'
        OR receipt.result_fact_json #>> '{schema_version}' IS DISTINCT FROM '1'
        OR jsonb_typeof(receipt.result_fact_json #> '{identity,fact_id}')
             IS DISTINCT FROM 'string'
        OR jsonb_typeof(receipt.result_fact_json #> '{identity,space_id}')
             IS DISTINCT FROM 'string'
        OR jsonb_typeof(receipt.result_fact_json #> '{identity,memory_scope_id}')
             IS DISTINCT FROM 'string'
        OR COALESCE(
             jsonb_typeof(receipt.result_fact_json #> '{identity,thread_id}'),
             'missing'
           ) NOT IN ('string', 'null')
        OR jsonb_typeof(receipt.result_fact_json #> '{visibility,version}')
             IS DISTINCT FROM 'number'
        OR receipt.result_fact_json #>> '{identity,fact_id}'
             IS DISTINCT FROM receipt.result_fact_id
        OR receipt.result_fact_json #>> '{identity,space_id}'
             IS DISTINCT FROM receipt.space_id
        OR receipt.result_fact_json #>> '{identity,memory_scope_id}'
             IS DISTINCT FROM receipt.memory_scope_id
        OR receipt.result_fact_json #>> '{identity,thread_id}'
             IS DISTINCT FROM result_fact.thread_id
        OR receipt.result_fact_json #>> '{visibility,version}'
             IS DISTINCT FROM receipt.result_fact_version::TEXT
      )
  ) THEN
    RAISE EXCEPTION 'suggestion receipt snapshot identity preflight failed'
      USING ERRCODE = '23514';
  END IF;
END $$;

ALTER TABLE memory_facts
  DROP CONSTRAINT IF EXISTS uq_memory_facts_id_scope_thread,
  ADD CONSTRAINT uq_memory_facts_id_scope_thread
    UNIQUE (id, space_id, memory_scope_id, thread_scope_key);

-- The legacy relation FK depends on the decision identity unique index. Remove
-- that dependency before replacing the unique with its thread-scoped identity.
ALTER TABLE memory_fact_relations
  DROP CONSTRAINT IF EXISTS fk_memory_fact_relation_temporal_decision_identity;

ALTER TABLE memory_fact_temporal_decisions
  DROP CONSTRAINT IF EXISTS uq_memory_fact_temporal_decisions_id_scope_thread,
  ADD CONSTRAINT uq_memory_fact_temporal_decisions_id_scope_thread
    UNIQUE (id, space_id, memory_scope_id, thread_scope_key),
  DROP CONSTRAINT IF EXISTS uq_memory_fact_temporal_decision_relation_identity,
  ADD CONSTRAINT uq_memory_fact_temporal_decision_relation_identity
    UNIQUE (
      id,
      space_id,
      memory_scope_id,
      thread_scope_key,
      source_fact_id,
      source_fact_version,
      target_fact_id,
      target_fact_version,
      effective_at
    );

ALTER TABLE memory_fact_operation_receipts
  DROP CONSTRAINT IF EXISTS fk_memory_fact_operation_receipt_fact_scope,
  ADD CONSTRAINT fk_memory_fact_operation_receipt_fact_scope
    FOREIGN KEY (result_fact_id, space_id, memory_scope_id, thread_scope_key)
    REFERENCES memory_facts(id, space_id, memory_scope_id, thread_scope_key);

ALTER TABLE memory_fact_temporal_decisions
  DROP CONSTRAINT IF EXISTS fk_memory_fact_temporal_decision_source_scope,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_temporal_decision_target_scope,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_temporal_decision_compensation_scope,
  ADD CONSTRAINT fk_memory_fact_temporal_decision_source_scope
    FOREIGN KEY (source_fact_id, space_id, memory_scope_id, thread_scope_key)
    REFERENCES memory_facts(id, space_id, memory_scope_id, thread_scope_key),
  ADD CONSTRAINT fk_memory_fact_temporal_decision_target_scope
    FOREIGN KEY (target_fact_id, space_id, memory_scope_id, thread_scope_key)
    REFERENCES memory_facts(id, space_id, memory_scope_id, thread_scope_key),
  ADD CONSTRAINT fk_memory_fact_temporal_decision_compensation_scope
    FOREIGN KEY (compensates_decision_id, space_id, memory_scope_id, thread_scope_key)
    REFERENCES memory_fact_temporal_decisions(
      id,
      space_id,
      memory_scope_id,
      thread_scope_key
    );

ALTER TABLE memory_fact_relations
  DROP CONSTRAINT IF EXISTS fk_memory_fact_relation_source_scope,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_relation_target_scope,
  DROP CONSTRAINT IF EXISTS fk_memory_fact_relation_temporal_decision_identity,
  ADD CONSTRAINT fk_memory_fact_relation_source_scope
    FOREIGN KEY (source_fact_id, space_id, memory_scope_id, thread_scope_key)
    REFERENCES memory_facts(id, space_id, memory_scope_id, thread_scope_key),
  ADD CONSTRAINT fk_memory_fact_relation_target_scope
    FOREIGN KEY (target_fact_id, space_id, memory_scope_id, thread_scope_key)
    REFERENCES memory_facts(id, space_id, memory_scope_id, thread_scope_key),
  ADD CONSTRAINT fk_memory_fact_relation_temporal_decision_identity
    FOREIGN KEY (
      temporal_decision_id,
      space_id,
      memory_scope_id,
      thread_scope_key,
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
      thread_scope_key,
      source_fact_id,
      source_fact_version,
      target_fact_id,
      target_fact_version,
      effective_at
    );

DROP TRIGGER IF EXISTS trg_memory_fact_operation_receipt_snapshot_identity
  ON memory_fact_operation_receipts;
CREATE TRIGGER trg_memory_fact_operation_receipt_snapshot_identity
BEFORE INSERT ON memory_fact_operation_receipts
FOR EACH ROW
EXECUTE FUNCTION memory_fact_operation_receipt_snapshot_identity();

DROP TRIGGER IF EXISTS trg_suggestion_resolution_receipt_compatibility_fields
  ON suggestion_resolution_receipts;
CREATE TRIGGER trg_suggestion_resolution_receipt_compatibility_fields
BEFORE INSERT ON suggestion_resolution_receipts
FOR EACH ROW
EXECUTE FUNCTION suggestion_resolution_receipt_compatibility_fields();

CREATE OR REPLACE FUNCTION reject_exact_result_receipt_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'exact-result receipt is append-only'
    USING ERRCODE = '55000';
END $$;

DROP TRIGGER IF EXISTS trg_memory_fact_operation_receipt_append_only
  ON memory_fact_operation_receipts;
CREATE TRIGGER trg_memory_fact_operation_receipt_append_only
BEFORE UPDATE OR DELETE ON memory_fact_operation_receipts
FOR EACH ROW
EXECUTE FUNCTION reject_exact_result_receipt_mutation();

DROP TRIGGER IF EXISTS trg_suggestion_resolution_receipt_append_only
  ON suggestion_resolution_receipts;
CREATE TRIGGER trg_suggestion_resolution_receipt_append_only
BEFORE UPDATE OR DELETE ON suggestion_resolution_receipts
FOR EACH ROW
EXECUTE FUNCTION reject_exact_result_receipt_mutation();
