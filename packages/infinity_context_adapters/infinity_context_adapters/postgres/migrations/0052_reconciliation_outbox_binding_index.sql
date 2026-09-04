-- Bound exact-document reconciliation to active canonical outbox work without
-- scanning unrelated historical or terminal projection rows.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';

CREATE INDEX IF NOT EXISTS ix_memory_outbox_active_reconciliation_binding
ON memory_outbox (aggregate_id, event_type, aggregate_type, aggregate_version)
WHERE status IN ('pending', 'running', 'retry_pending');
