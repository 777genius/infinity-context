-- Append-only hardening for exact-result receipt snapshots.
--
-- Earlier writers encoded an absent suggestion result fact as JSONB literal
-- null. Normalize only the representation whose normalized identity is also
-- absent; any contradictory identity remains a fail-closed migration error.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM suggestion_resolution_receipts
    WHERE jsonb_typeof(result_fact_json) = 'null'
      AND (result_fact_id IS NOT NULL OR result_fact_version IS NOT NULL)
  ) THEN
    RAISE EXCEPTION 'suggestion receipt JSON null identity preflight failed'
      USING ERRCODE = '23514';
  END IF;
END $$;

UPDATE suggestion_resolution_receipts
SET result_fact_json = NULL
WHERE jsonb_typeof(result_fact_json) = 'null';

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
  ) THEN
    RAISE EXCEPTION 'suggestion receipt snapshot identity preflight failed'
      USING ERRCODE = '23514';
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM suggestion_resolution_receipts receipt
    LEFT JOIN memory_facts result_fact
      ON result_fact.id = receipt.result_fact_id
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
        OR (
          result_fact.id IS NOT NULL
          AND receipt.result_fact_json #>> '{identity,thread_id}'
            IS DISTINCT FROM result_fact.thread_id
        )
        OR receipt.result_fact_json #>> '{visibility,version}'
          IS DISTINCT FROM receipt.result_fact_version::TEXT
      )
  ) THEN
    RAISE EXCEPTION 'suggestion receipt fact snapshot identity preflight failed'
      USING ERRCODE = '23514';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION memory_fact_operation_receipt_snapshot_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF jsonb_typeof(NEW.result_snapshot_json) IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.result_snapshot_json -> 'schema_version')
          IS DISTINCT FROM 'number'
     OR NEW.result_snapshot_json #>> '{schema_version}' IS DISTINCT FROM '1'
     OR jsonb_typeof(NEW.result_snapshot_json #> '{identity,fact_id}')
          IS DISTINCT FROM 'string'
     OR jsonb_typeof(NEW.result_snapshot_json #> '{identity,space_id}')
          IS DISTINCT FROM 'string'
     OR jsonb_typeof(NEW.result_snapshot_json #> '{identity,memory_scope_id}')
          IS DISTINCT FROM 'string'
     OR COALESCE(
          jsonb_typeof(NEW.result_snapshot_json #> '{identity,thread_id}'),
          'missing'
        ) NOT IN ('string', 'null')
     OR jsonb_typeof(NEW.result_snapshot_json #> '{visibility,version}')
          IS DISTINCT FROM 'number'
     OR NEW.result_snapshot_json #>> '{identity,fact_id}'
          IS DISTINCT FROM NEW.result_fact_id
     OR NEW.result_snapshot_json #>> '{identity,space_id}'
          IS DISTINCT FROM NEW.space_id
     OR NEW.result_snapshot_json #>> '{identity,memory_scope_id}'
          IS DISTINCT FROM NEW.memory_scope_id
     OR NEW.result_snapshot_json #>> '{identity,thread_id}'
          IS DISTINCT FROM NEW.thread_id
     OR NEW.result_snapshot_json #>> '{visibility,version}'
          IS DISTINCT FROM NEW.result_fact_version::TEXT
  THEN
    RAISE EXCEPTION 'fact operation receipt snapshot identity mismatch'
      USING ERRCODE = '23514',
            CONSTRAINT = 'ck_memory_fact_operation_receipt_snapshot_identity';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_memory_fact_operation_receipt_snapshot_identity
  ON memory_fact_operation_receipts;

CREATE TRIGGER trg_memory_fact_operation_receipt_snapshot_identity
BEFORE INSERT OR UPDATE ON memory_fact_operation_receipts
FOR EACH ROW
EXECUTE FUNCTION memory_fact_operation_receipt_snapshot_identity();

CREATE OR REPLACE FUNCTION suggestion_resolution_receipt_compatibility_fields()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  result_fact_thread_id VARCHAR(80);
BEGIN
  SELECT suggestion.space_id, suggestion.memory_scope_id
  INTO NEW.space_id, NEW.memory_scope_id
  FROM memory_suggestions suggestion
  WHERE suggestion.id = NEW.suggestion_id;

  IF jsonb_typeof(NEW.result_suggestion_json) IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.result_suggestion_json -> 'schema_version')
          IS DISTINCT FROM 'number'
     OR NEW.result_suggestion_json #>> '{schema_version}' IS DISTINCT FROM '1'
     OR jsonb_typeof(NEW.result_suggestion_json -> 'id') IS DISTINCT FROM 'string'
     OR jsonb_typeof(NEW.result_suggestion_json -> 'space_id')
          IS DISTINCT FROM 'string'
     OR jsonb_typeof(NEW.result_suggestion_json -> 'memory_scope_id')
          IS DISTINCT FROM 'string'
     OR NEW.result_suggestion_json #>> '{id}' IS DISTINCT FROM NEW.suggestion_id
     OR NEW.result_suggestion_json #>> '{space_id}' IS DISTINCT FROM NEW.space_id
     OR NEW.result_suggestion_json #>> '{memory_scope_id}'
          IS DISTINCT FROM NEW.memory_scope_id
  THEN
    RAISE EXCEPTION 'suggestion resolution receipt snapshot identity mismatch'
      USING ERRCODE = '23514',
            CONSTRAINT = 'ck_suggestion_resolution_receipt_suggestion_snapshot_identity';
  END IF;

  IF NEW.result_fact_json IS NULL
     OR jsonb_typeof(NEW.result_fact_json) = 'null'
  THEN
    NEW.result_fact_json := NULL;
    NEW.result_fact_id := NULL;
    NEW.result_fact_version := NULL;
  ELSE
    IF jsonb_typeof(NEW.result_fact_json) IS DISTINCT FROM 'object'
       OR jsonb_typeof(NEW.result_fact_json -> 'schema_version')
            IS DISTINCT FROM 'number'
       OR NEW.result_fact_json #>> '{schema_version}' IS DISTINCT FROM '1'
       OR jsonb_typeof(NEW.result_fact_json #> '{identity,fact_id}')
            IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.result_fact_json #> '{identity,space_id}')
            IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.result_fact_json #> '{identity,memory_scope_id}')
            IS DISTINCT FROM 'string'
       OR COALESCE(
            jsonb_typeof(NEW.result_fact_json #> '{identity,thread_id}'),
            'missing'
          ) NOT IN ('string', 'null')
       OR jsonb_typeof(NEW.result_fact_json #> '{visibility,version}')
            IS DISTINCT FROM 'number'
       OR NEW.result_fact_json #>> '{identity,space_id}' IS DISTINCT FROM NEW.space_id
       OR NEW.result_fact_json #>> '{identity,memory_scope_id}'
            IS DISTINCT FROM NEW.memory_scope_id
    THEN
      RAISE EXCEPTION 'suggestion resolution receipt fact snapshot identity mismatch'
        USING ERRCODE = '23514',
              CONSTRAINT = 'ck_suggestion_resolution_receipt_fact_snapshot_identity';
    END IF;

    NEW.result_fact_id := NEW.result_fact_json #>> '{identity,fact_id}';
    NEW.result_fact_version :=
      (NEW.result_fact_json #>> '{visibility,version}')::INTEGER;
    SELECT fact.thread_id
    INTO result_fact_thread_id
    FROM memory_facts fact
    WHERE fact.id = NEW.result_fact_id
      AND fact.space_id = NEW.space_id
      AND fact.memory_scope_id = NEW.memory_scope_id;
    IF FOUND AND NEW.result_fact_json #>> '{identity,thread_id}'
          IS DISTINCT FROM result_fact_thread_id
    THEN
      RAISE EXCEPTION 'suggestion resolution receipt fact thread identity mismatch'
        USING ERRCODE = '23514',
              CONSTRAINT = 'ck_suggestion_resolution_receipt_fact_snapshot_identity';
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_suggestion_resolution_receipt_compatibility_fields
  ON suggestion_resolution_receipts;

CREATE TRIGGER trg_suggestion_resolution_receipt_compatibility_fields
BEFORE INSERT OR UPDATE ON suggestion_resolution_receipts
FOR EACH ROW
EXECUTE FUNCTION suggestion_resolution_receipt_compatibility_fields();
