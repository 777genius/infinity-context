-- Retire the pre-profile Retrieval projection lane.  This is a forward-only
-- cutover: published migrations and their event identifiers remain immutable,
-- while current writes are owned exclusively by Retrieval profiles.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';

DROP TRIGGER IF EXISTS trg_memory_chunk_locator_projection_events_v2 ON memory_chunks;

-- Exclude concurrent claim/status transitions while the retired queue is
-- inspected and terminalized.  A committed running row means a provider call
-- may already be in flight, so the upgrade must fail closed until that worker
-- generation has drained.
LOCK TABLE memory_outbox IN SHARE ROW EXCLUSIVE MODE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM memory_outbox
         WHERE aggregate_type = 'locator_chunk'
           AND event_type IN ('vector.upsert_chunk', 'vector.delete_chunks')
           AND status = 'running'
    ) THEN
        RAISE EXCEPTION
            'retrieval legacy projection cutover requires running events to drain';
    END IF;
END;
$$;

UPDATE memory_outbox
   SET status = 'done',
       last_safe_error = 'retired Retrieval projection event was not dispatched',
       last_safe_diagnostic_code = 'retrieval.legacy_projection_retired',
       updated_at = CURRENT_TIMESTAMP
 WHERE aggregate_type = 'locator_chunk'
   AND event_type IN ('vector.upsert_chunk', 'vector.delete_chunks')
   AND status IN ('pending', 'retry_pending', 'dead');

DROP FUNCTION IF EXISTS memory_chunk_locator_projection_events_v2();
DROP TABLE IF EXISTS memory_locator_projection_tombstones;
