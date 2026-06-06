ALTER TABLE memory_outbox
    ADD COLUMN IF NOT EXISTS workload_class VARCHAR(80) NOT NULL DEFAULT 'projection';

ALTER TABLE memory_outbox
    ADD COLUMN IF NOT EXISTS fairness_key VARCHAR(160);

UPDATE memory_outbox
SET fairness_key = aggregate_type || ':' || aggregate_id
WHERE fairness_key IS NULL;

ALTER TABLE memory_outbox
    ADD COLUMN IF NOT EXISTS last_safe_diagnostic_code VARCHAR(120);

CREATE INDEX IF NOT EXISTS ix_memory_outbox_workload_fairness
    ON memory_outbox(status, workload_class, fairness_key, next_attempt_at);
