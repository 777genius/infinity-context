SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.memory_outbox
  ALTER COLUMN aggregate_id TYPE VARCHAR(120);
