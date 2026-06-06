ALTER TABLE memory_facts
    ADD COLUMN IF NOT EXISTS classification VARCHAR(40) NOT NULL DEFAULT 'internal';

ALTER TABLE memory_documents
    ADD COLUMN IF NOT EXISTS classification VARCHAR(40) NOT NULL DEFAULT 'unknown';

ALTER TABLE memory_chunks
    ADD COLUMN IF NOT EXISTS classification VARCHAR(40) NOT NULL DEFAULT 'unknown';
