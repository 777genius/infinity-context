ALTER TABLE memory_suggestions ADD COLUMN IF NOT EXISTS thread_id VARCHAR(80);
UPDATE memory_suggestions s
SET thread_id = f.thread_id
FROM memory_facts f
WHERE s.thread_id IS NULL
  AND s.target_fact_id = f.id
  AND s.space_id = f.space_id
  AND s.memory_scope_id = f.memory_scope_id
  AND f.thread_id IS NOT NULL
  AND s.status = 'pending';
UPDATE memory_suggestions s
SET thread_id = c.thread_id
FROM memory_captures c
WHERE s.thread_id IS NULL
  AND s.created_from_capture_id = c.id
  AND s.space_id = c.space_id
  AND s.memory_scope_id = c.memory_scope_id
  AND c.thread_id IS NOT NULL
  AND s.status = 'pending';
CREATE INDEX IF NOT EXISTS ix_memory_suggestions_thread_status
  ON memory_suggestions(space_id, memory_scope_id, thread_id, status);
