ALTER TABLE memory_service_tokens
    ADD COLUMN IF NOT EXISTS permissions_json JSONB;
