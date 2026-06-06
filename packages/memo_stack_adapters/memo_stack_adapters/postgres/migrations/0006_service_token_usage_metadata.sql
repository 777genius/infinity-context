ALTER TABLE memory_service_tokens
    ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ;

ALTER TABLE memory_service_tokens
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
