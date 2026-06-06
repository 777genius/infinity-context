ALTER TABLE memory_service_tokens
    ADD COLUMN IF NOT EXISTS profile_ids_json JSONB;
