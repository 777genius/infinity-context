ALTER TABLE suggestion_resolution_receipts
  ADD COLUMN IF NOT EXISTS space_id VARCHAR(80),
  ADD COLUMN IF NOT EXISTS memory_scope_id VARCHAR(80),
  ADD COLUMN IF NOT EXISTS result_fact_id VARCHAR(80),
  ADD COLUMN IF NOT EXISTS result_fact_version INTEGER;

UPDATE suggestion_resolution_receipts
SET result_fact_json = NULL
WHERE jsonb_typeof(result_fact_json) = 'null';

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM suggestion_resolution_receipts
    WHERE result_fact_json IS NOT NULL
      AND (
        jsonb_typeof(result_fact_json #> '{identity,fact_id}') <> 'string'
        OR jsonb_typeof(result_fact_json #> '{visibility,version}') <> 'number'
      )
  ) THEN
    RAISE EXCEPTION
      'suggestion receipt tenant integrity preflight failed: invalid result fact snapshot'
      USING ERRCODE = '23514';
  END IF;
END $$;

UPDATE suggestion_resolution_receipts receipt
SET space_id = suggestion.space_id,
    memory_scope_id = suggestion.memory_scope_id,
    result_fact_id = CASE
      WHEN receipt.result_fact_json IS NULL THEN NULL
      ELSE receipt.result_fact_json #>> '{identity,fact_id}'
    END,
    result_fact_version = CASE
      WHEN receipt.result_fact_json IS NULL THEN NULL
      ELSE (receipt.result_fact_json #>> '{visibility,version}')::INTEGER
    END
FROM memory_suggestions suggestion
WHERE suggestion.id = receipt.suggestion_id;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM suggestion_resolution_receipts receipt
    LEFT JOIN memory_suggestions suggestion
      ON suggestion.id = receipt.suggestion_id
     AND suggestion.space_id = receipt.space_id
     AND suggestion.memory_scope_id = receipt.memory_scope_id
    LEFT JOIN memory_fact_temporal_decisions decision
      ON decision.id = receipt.temporal_decision_id
     AND decision.space_id = receipt.space_id
     AND decision.memory_scope_id = receipt.memory_scope_id
    LEFT JOIN memory_facts result_fact
      ON result_fact.id = receipt.result_fact_id
     AND result_fact.space_id = receipt.space_id
     AND result_fact.memory_scope_id = receipt.memory_scope_id
    LEFT JOIN memory_fact_versions result_version
      ON result_version.fact_id = receipt.result_fact_id
     AND result_version.version = receipt.result_fact_version
    LEFT JOIN memory_fact_relations relation
      ON relation.id = receipt.relation_id
     AND relation.space_id = receipt.space_id
     AND relation.memory_scope_id = receipt.memory_scope_id
     AND relation.temporal_decision_id = receipt.temporal_decision_id
    WHERE suggestion.id IS NULL
       OR (receipt.result_fact_json IS NULL) <> (receipt.result_fact_id IS NULL)
       OR (receipt.result_fact_id IS NULL) <> (receipt.result_fact_version IS NULL)
       OR (
         receipt.result_fact_id IS NOT NULL
         AND (result_fact.id IS NULL OR result_version.fact_id IS NULL)
       )
       OR (
         receipt.temporal_decision_id IS NOT NULL
         AND decision.id IS NULL
       )
       OR (
         receipt.relation_id IS NOT NULL
         AND relation.id IS NULL
       )
  ) THEN
    RAISE EXCEPTION
      'suggestion receipt tenant integrity preflight failed: cross-scope audit reference'
      USING ERRCODE = '23503';
  END IF;
END $$;

ALTER TABLE suggestion_resolution_receipts
  ALTER COLUMN space_id SET NOT NULL,
  ALTER COLUMN memory_scope_id SET NOT NULL;

ALTER TABLE memory_suggestions
  DROP CONSTRAINT IF EXISTS uq_memory_suggestions_id_scope,
  ADD CONSTRAINT uq_memory_suggestions_id_scope
    UNIQUE (id, space_id, memory_scope_id);

ALTER TABLE memory_fact_relations
  DROP CONSTRAINT IF EXISTS uq_memory_fact_relations_receipt_identity,
  ADD CONSTRAINT uq_memory_fact_relations_receipt_identity
    UNIQUE (id, space_id, memory_scope_id, temporal_decision_id);

ALTER TABLE suggestion_resolution_receipts
  DROP CONSTRAINT IF EXISTS suggestion_resolution_receipts_suggestion_id_fkey,
  DROP CONSTRAINT IF EXISTS suggestion_resolution_receipts_temporal_decision_id_fkey,
  DROP CONSTRAINT IF EXISTS suggestion_resolution_receipts_relation_id_fkey,
  DROP CONSTRAINT IF EXISTS fk_suggestion_resolution_receipt_suggestion_scope,
  DROP CONSTRAINT IF EXISTS fk_suggestion_resolution_receipt_fact_scope,
  DROP CONSTRAINT IF EXISTS fk_suggestion_resolution_receipt_fact_version,
  DROP CONSTRAINT IF EXISTS fk_suggestion_resolution_receipt_decision_scope,
  DROP CONSTRAINT IF EXISTS fk_suggestion_resolution_receipt_relation_decision,
  DROP CONSTRAINT IF EXISTS ck_suggestion_resolution_receipt_relation_decision,
  DROP CONSTRAINT IF EXISTS ck_suggestion_resolution_receipt_fact_pair,
  DROP CONSTRAINT IF EXISTS ck_suggestion_resolution_receipt_fact_snapshot,
  ADD CONSTRAINT fk_suggestion_resolution_receipt_suggestion_scope
    FOREIGN KEY (suggestion_id, space_id, memory_scope_id)
    REFERENCES memory_suggestions(id, space_id, memory_scope_id),
  ADD CONSTRAINT fk_suggestion_resolution_receipt_fact_scope
    FOREIGN KEY (result_fact_id, space_id, memory_scope_id)
    REFERENCES memory_facts(id, space_id, memory_scope_id),
  ADD CONSTRAINT fk_suggestion_resolution_receipt_fact_version
    FOREIGN KEY (result_fact_id, result_fact_version)
    REFERENCES memory_fact_versions(fact_id, version),
  ADD CONSTRAINT fk_suggestion_resolution_receipt_decision_scope
    FOREIGN KEY (temporal_decision_id, space_id, memory_scope_id)
    REFERENCES memory_fact_temporal_decisions(id, space_id, memory_scope_id),
  ADD CONSTRAINT fk_suggestion_resolution_receipt_relation_decision
    FOREIGN KEY (relation_id, space_id, memory_scope_id, temporal_decision_id)
    REFERENCES memory_fact_relations(
      id,
      space_id,
      memory_scope_id,
      temporal_decision_id
    ),
  ADD CONSTRAINT ck_suggestion_resolution_receipt_relation_decision
    CHECK (relation_id IS NULL OR temporal_decision_id IS NOT NULL),
  ADD CONSTRAINT ck_suggestion_resolution_receipt_fact_pair
    CHECK ((result_fact_id IS NULL) = (result_fact_version IS NULL)),
  ADD CONSTRAINT ck_suggestion_resolution_receipt_fact_snapshot
    CHECK ((result_fact_id IS NULL) = (result_fact_json IS NULL));

CREATE OR REPLACE FUNCTION suggestion_resolution_receipt_compatibility_fields()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  SELECT suggestion.space_id, suggestion.memory_scope_id
  INTO NEW.space_id, NEW.memory_scope_id
  FROM memory_suggestions suggestion
  WHERE suggestion.id = NEW.suggestion_id;

  IF NEW.result_fact_json IS NULL THEN
    NEW.result_fact_id := NULL;
    NEW.result_fact_version := NULL;
  ELSE
    NEW.result_fact_id := NEW.result_fact_json #>> '{identity,fact_id}';
    NEW.result_fact_version :=
      (NEW.result_fact_json #>> '{visibility,version}')::INTEGER;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_suggestion_resolution_receipt_compatibility_fields
  ON suggestion_resolution_receipts;

CREATE TRIGGER trg_suggestion_resolution_receipt_compatibility_fields
BEFORE INSERT OR UPDATE ON suggestion_resolution_receipts
FOR EACH ROW
EXECUTE FUNCTION suggestion_resolution_receipt_compatibility_fields();
