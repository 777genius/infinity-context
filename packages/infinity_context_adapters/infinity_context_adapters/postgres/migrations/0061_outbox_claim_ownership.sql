SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.memory_outbox
  ADD COLUMN IF NOT EXISTS claim_token VARCHAR(32);
