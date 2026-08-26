-- Retrieval V2 expand phase. Existing rows deliberately remain NULL/ineligible;
-- no coordinate is fabricated. Long-running index builds and any legacy-index
-- contract transition are fenced outside the transactional migration runner.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5min';

-- aggregate_version columns are converted online by the staged migration runner.

ALTER TABLE memory_chunks
    ADD COLUMN IF NOT EXISTS retrieval_locator VARCHAR(256),
    ADD COLUMN IF NOT EXISTS retrieval_source_key VARCHAR(256),
    ADD COLUMN IF NOT EXISTS retrieval_projection_generation VARCHAR(256),
    ADD COLUMN IF NOT EXISTS retrieval_sequence_ordinal INTEGER,
    ADD COLUMN IF NOT EXISTS retrieval_kind VARCHAR(256),
    ADD COLUMN IF NOT EXISTS retrieval_version BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS retrieval_actor_keys_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS retrieval_start_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS retrieval_end_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS retrieval_relative_start_ms BIGINT,
    ADD COLUMN IF NOT EXISTS retrieval_relative_end_ms BIGINT,
    ADD COLUMN IF NOT EXISTS retrieval_category VARCHAR(256),
    ADD COLUMN IF NOT EXISTS retrieval_tags_json JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE memory_documents
    ADD COLUMN IF NOT EXISTS retrieval_projected BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE memory_chunks
    ADD CONSTRAINT ck_memory_chunks_retrieval_version_positive
        CHECK (retrieval_version BETWEEN 1 AND 9007199254740991) NOT VALID,
    ADD CONSTRAINT ck_memory_chunks_retrieval_coordinates_complete CHECK (
        (retrieval_locator IS NULL
         AND retrieval_source_key IS NULL
         AND retrieval_projection_generation IS NULL
         AND retrieval_sequence_ordinal IS NULL
         AND retrieval_kind IS NULL
         AND retrieval_category IS NULL)
        OR
        (retrieval_locator IS NOT NULL
         AND retrieval_source_key IS NOT NULL
         AND retrieval_projection_generation IS NOT NULL
         AND retrieval_sequence_ordinal IS NOT NULL
         AND retrieval_kind IS NOT NULL
         AND retrieval_category IS NOT NULL)
    ) NOT VALID,
    ADD CONSTRAINT ck_memory_chunks_retrieval_ordinal_range
        CHECK (retrieval_sequence_ordinal IS NULL OR
               retrieval_sequence_ordinal BETWEEN 0 AND 2147483647) NOT VALID,
    ADD CONSTRAINT ck_memory_chunks_retrieval_time_complete
        CHECK ((retrieval_start_at IS NULL) = (retrieval_end_at IS NULL)) NOT VALID,
    ADD CONSTRAINT ck_memory_chunks_retrieval_time_ordered
        CHECK (retrieval_start_at IS NULL OR retrieval_start_at <= retrieval_end_at) NOT VALID,
    ADD CONSTRAINT ck_memory_chunks_retrieval_relative_time_complete
        CHECK ((retrieval_relative_start_ms IS NULL) =
               (retrieval_relative_end_ms IS NULL)) NOT VALID,
    ADD CONSTRAINT ck_memory_chunks_retrieval_relative_time_range CHECK (
        retrieval_relative_start_ms IS NULL OR
        (retrieval_relative_start_ms BETWEEN 0 AND 9007199254740991 AND
         retrieval_relative_end_ms BETWEEN retrieval_relative_start_ms
                                         AND 9007199254740991)
    ) NOT VALID;

CREATE TABLE memory_document_projection_receipts (
    space_id VARCHAR(80) NOT NULL,
    idempotency_key VARCHAR(240) NOT NULL,
    request_fingerprint_sha256 CHAR(64) NOT NULL,
    document_id VARCHAR(80) NOT NULL,
    locator VARCHAR(256) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (space_id, idempotency_key),
    CONSTRAINT fk_document_projection_receipt_document
        FOREIGN KEY (document_id) REFERENCES memory_documents(id),
    CONSTRAINT ck_document_projection_receipt_fingerprint
        CHECK (request_fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE memory_locator_projection_tombstones (
    chunk_id VARCHAR(80) PRIMARY KEY,
    canonical_version BIGINT NOT NULL,
    legacy_deleted_at TIMESTAMPTZ,
    locator_deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_locator_tombstone_version_positive CHECK (canonical_version > 0)
);

CREATE FUNCTION memory_chunk_retrieval_fence_v2()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE retrieval_changed BOOLEAN;
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.retrieval_version := 1;
        RETURN NEW;
    END IF;
    retrieval_changed := ROW(
        OLD.text, OLD.normalized_text, OLD.status, OLD.classification,
        OLD.space_id, OLD.memory_scope_id, OLD.thread_id, OLD.document_id,
        OLD.retrieval_locator, OLD.retrieval_source_key,
        OLD.retrieval_projection_generation, OLD.retrieval_sequence_ordinal,
        OLD.retrieval_kind, OLD.retrieval_actor_keys_json,
        OLD.retrieval_start_at, OLD.retrieval_end_at,
        OLD.retrieval_relative_start_ms, OLD.retrieval_relative_end_ms,
        OLD.retrieval_category, OLD.retrieval_tags_json
    ) IS DISTINCT FROM ROW(
        NEW.text, NEW.normalized_text, NEW.status, NEW.classification,
        NEW.space_id, NEW.memory_scope_id, NEW.thread_id, NEW.document_id,
        NEW.retrieval_locator, NEW.retrieval_source_key,
        NEW.retrieval_projection_generation, NEW.retrieval_sequence_ordinal,
        NEW.retrieval_kind, NEW.retrieval_actor_keys_json,
        NEW.retrieval_start_at, NEW.retrieval_end_at,
        NEW.retrieval_relative_start_ms, NEW.retrieval_relative_end_ms,
        NEW.retrieval_category, NEW.retrieval_tags_json
    );
    NEW.retrieval_version := CASE WHEN retrieval_changed
        THEN OLD.retrieval_version + 1 ELSE OLD.retrieval_version END;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_memory_chunk_retrieval_fence_v2
BEFORE INSERT OR UPDATE ON memory_chunks
FOR EACH ROW EXECUTE FUNCTION memory_chunk_retrieval_fence_v2();

CREATE FUNCTION memory_chunk_locator_projection_events_v2()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.retrieval_locator IS NULL THEN RETURN NULL; END IF;
    IF NEW.status <> 'active' OR NEW.classification NOT IN ('public', 'internal') THEN
        IF TG_OP <> 'INSERT'
           AND NOT (
               (OLD.status = 'active' AND OLD.classification IN ('public', 'internal'))
               OR NEW.retrieval_version > OLD.retrieval_version
           ) THEN
            RETURN NULL;
        END IF;
        INSERT INTO memory_locator_projection_tombstones (
            chunk_id, canonical_version, created_at, updated_at
        ) VALUES (NEW.id, NEW.retrieval_version, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (chunk_id) DO UPDATE SET
            canonical_version = EXCLUDED.canonical_version,
            legacy_deleted_at = NULL, locator_deleted_at = NULL,
            updated_at = EXCLUDED.updated_at
        WHERE memory_locator_projection_tombstones.canonical_version < EXCLUDED.canonical_version;
        INSERT INTO memory_outbox (
            message_key, event_type, aggregate_type, aggregate_id,
            aggregate_version, workload_class, fairness_key, payload_json,
            status, attempt_count, next_attempt_at, created_at, updated_at
        ) VALUES (
            'locator-v2-tombstone:' || NEW.id || ':' || NEW.retrieval_version,
            'vector.delete_chunks', 'locator_chunk', NEW.id, NEW.retrieval_version,
            'projection', 'chunk:' || NEW.id,
            jsonb_build_object('chunk_ids', jsonb_build_array(NEW.id)),
            'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        ) ON CONFLICT (message_key) WHERE message_key IS NOT NULL DO NOTHING;
    ELSIF TG_OP = 'INSERT' OR NEW.retrieval_version <> OLD.retrieval_version THEN
        -- A later active version supersedes any completed/pending tombstone for the
        -- same point identity. The versioned upsert remains the repair authority.
        UPDATE memory_locator_projection_tombstones SET
            legacy_deleted_at = CURRENT_TIMESTAMP,
            locator_deleted_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE chunk_id = NEW.id AND canonical_version < NEW.retrieval_version;
        INSERT INTO memory_outbox (
            message_key, event_type, aggregate_type, aggregate_id,
            aggregate_version, workload_class, fairness_key, payload_json,
            status, attempt_count, next_attempt_at, created_at, updated_at
        ) VALUES (
            'locator-v2-reproject:' || NEW.id || ':' || NEW.retrieval_version,
            'vector.upsert_chunk', 'locator_chunk', NEW.id, NEW.retrieval_version,
            'projection', 'chunk:' || NEW.id,
            jsonb_build_object('chunk_id', NEW.id),
            'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        ) ON CONFLICT (message_key) WHERE message_key IS NOT NULL DO NOTHING;
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_memory_chunk_locator_projection_events_v2
AFTER INSERT OR UPDATE ON memory_chunks
FOR EACH ROW EXECUTE FUNCTION memory_chunk_locator_projection_events_v2();
