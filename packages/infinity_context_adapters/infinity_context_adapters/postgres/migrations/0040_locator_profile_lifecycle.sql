-- Retrieval V2 profile lifecycle. Postgres is canonical; provider collections are
-- disposable projections addressed only through immutable profile identities.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5min';

-- The sequence and populated NOT NULL watermark column are created online by
-- the staged migration runner before this transactional schema phase.

CREATE TABLE memory_locator_profiles (
    profile_id VARCHAR(120) PRIMARY KEY,
    generation VARCHAR(160) NOT NULL,
    profile_digest CHAR(64) NOT NULL,
    collection_name VARCHAR(240) NOT NULL,
    state VARCHAR(24) NOT NULL,
    backfill_cursor VARCHAR(80),
    backfill_complete BOOLEAN NOT NULL DEFAULT FALSE,
    canonical_watermark BIGINT NOT NULL DEFAULT 0,
    projected_watermark BIGINT NOT NULL DEFAULT 0,
    expected_count BIGINT NOT NULL DEFAULT 0,
    projected_count BIGINT NOT NULL DEFAULT 0,
    expected_digest CHAR(64) NOT NULL
        DEFAULT 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    projected_digest CHAR(64) NOT NULL
        DEFAULT 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    created_at TIMESTAMPTZ NOT NULL,
    backfill_updated_at TIMESTAMPTZ,
    activated_at TIMESTAMPTZ,
    retained_at TIMESTAMPTZ,
    retired_at TIMESTAMPTZ,
    CONSTRAINT ck_locator_profile_state CHECK (
        state IN ('building', 'active', 'retained', 'retired')
    ),
    CONSTRAINT ck_locator_profile_digest CHECK (profile_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_locator_profile_attestation_digests CHECK (
        expected_digest ~ '^[0-9a-f]{64}$' AND projected_digest ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_locator_profile_counts CHECK (
        expected_count >= 0 AND projected_count >= 0
        AND canonical_watermark >= 0 AND projected_watermark >= 0
    ),
    CONSTRAINT uq_locator_profile_identity UNIQUE (generation, profile_digest),
    CONSTRAINT uq_locator_profile_collection UNIQUE (collection_name)
);

CREATE UNIQUE INDEX uq_locator_profile_one_building
    ON memory_locator_profiles (state) WHERE state = 'building';
CREATE UNIQUE INDEX uq_locator_profile_one_active
    ON memory_locator_profiles (state) WHERE state = 'active';
CREATE INDEX ix_locator_profiles_routable
    ON memory_locator_profiles (state, created_at)
    WHERE state IN ('building', 'active', 'retained');

CREATE TABLE memory_locator_profile_projection_receipts (
    profile_id VARCHAR(120) NOT NULL REFERENCES memory_locator_profiles(profile_id),
    chunk_id VARCHAR(80) NOT NULL,
    canonical_version BIGINT NOT NULL,
    canonical_watermark BIGINT NOT NULL,
    payload_digest CHAR(64) NOT NULL,
    projected_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (profile_id, chunk_id),
    CONSTRAINT ck_locator_profile_receipt_version CHECK (
        canonical_version BETWEEN 1 AND 9007199254740991
    ),
    CONSTRAINT ck_locator_profile_receipt_watermark CHECK (canonical_watermark >= 0),
    CONSTRAINT ck_locator_profile_receipt_digest CHECK (
        payload_digest ~ '^[0-9a-f]{64}$'
    )
);

CREATE TABLE memory_locator_profile_lanes (
    profile_id VARCHAR(120) NOT NULL REFERENCES memory_locator_profiles(profile_id),
    lane_id VARCHAR(120) NOT NULL,
    required BOOLEAN NOT NULL,
    healthy BOOLEAN NOT NULL DEFAULT FALSE,
    profile_qualified BOOLEAN NOT NULL DEFAULT FALSE,
    failure_code VARCHAR(120),
    checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (profile_id, lane_id)
);

CREATE TABLE memory_locator_profile_tombstones (
    profile_id VARCHAR(120) NOT NULL REFERENCES memory_locator_profiles(profile_id),
    chunk_id VARCHAR(80) NOT NULL,
    canonical_version BIGINT NOT NULL,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (profile_id, chunk_id),
    CONSTRAINT ck_locator_profile_tombstone_version CHECK (canonical_version > 0)
);
CREATE INDEX ix_locator_profile_tombstones_pending
    ON memory_locator_profile_tombstones (profile_id, updated_at, chunk_id)
    WHERE completed_at IS NULL;

CREATE FUNCTION memory_locator_profile_identity_immutable_v2()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(OLD.profile_id, OLD.generation, OLD.profile_digest, OLD.collection_name)
       IS DISTINCT FROM
       ROW(NEW.profile_id, NEW.generation, NEW.profile_digest, NEW.collection_name) THEN
        RAISE EXCEPTION 'retrieval profile identity is immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_memory_locator_profile_identity_immutable_v2
BEFORE UPDATE ON memory_locator_profiles
FOR EACH ROW EXECUTE FUNCTION memory_locator_profile_identity_immutable_v2();

CREATE FUNCTION memory_chunk_locator_watermark_v2()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.retrieval_commit_watermark := CASE
        WHEN TG_OP = 'INSERT' OR NEW.retrieval_version <> OLD.retrieval_version
            THEN nextval('memory_locator_commit_watermark_seq')
        ELSE OLD.retrieval_commit_watermark
    END;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_zz_memory_chunk_locator_watermark_v2
BEFORE INSERT OR UPDATE ON memory_chunks
FOR EACH ROW EXECUTE FUNCTION memory_chunk_locator_watermark_v2();

CREATE FUNCTION memory_chunk_locator_profile_events_v2()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    profile RECORD;
    chunk_key VARCHAR(80);
    chunk_version BIGINT;
    eligible BOOLEAN;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.retrieval_locator IS NULL THEN RETURN OLD; END IF;
        chunk_key := OLD.id;
        chunk_version := OLD.retrieval_version;
        eligible := FALSE;
    ELSE
        chunk_key := NEW.id;
        chunk_version := NEW.retrieval_version;
        eligible := NEW.retrieval_locator IS NOT NULL
            AND NEW.status = 'active'
            AND NEW.classification IN ('public', 'internal');
        IF TG_OP = 'INSERT' AND NOT eligible THEN RETURN NEW; END IF;
        IF TG_OP = 'UPDATE'
           AND OLD.retrieval_locator IS NULL
           AND NEW.retrieval_locator IS NULL THEN
            RETURN NEW;
        END IF;
    END IF;

    FOR profile IN
        SELECT profile_id FROM memory_locator_profiles
        WHERE state IN ('building', 'active', 'retained')
        ORDER BY profile_id
    LOOP
        IF eligible THEN
            DELETE FROM memory_locator_profile_tombstones
             WHERE profile_id = profile.profile_id AND chunk_id = chunk_key
               AND canonical_version < chunk_version;
            INSERT INTO memory_outbox (
                message_key, event_type, aggregate_type, aggregate_id,
                aggregate_version, workload_class, fairness_key, payload_json,
                status, attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (
                'locator-profile-upsert:' || md5(
                    profile.profile_id || ':' || chunk_key || ':' || chunk_version
                ),
                'vector.upsert_locator_profile', 'locator_profile_chunk', chunk_key,
                chunk_version, 'projection', 'profile:' || profile.profile_id,
                jsonb_build_object('chunk_id', chunk_key, 'profile_id', profile.profile_id),
                'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) ON CONFLICT (message_key) WHERE message_key IS NOT NULL DO NOTHING;
        ELSE
            INSERT INTO memory_locator_profile_tombstones (
                profile_id, chunk_id, canonical_version, created_at, updated_at
            ) VALUES (
                profile.profile_id, chunk_key, chunk_version, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) ON CONFLICT (profile_id, chunk_id) DO UPDATE SET
                canonical_version = EXCLUDED.canonical_version,
                completed_at = NULL,
                updated_at = EXCLUDED.updated_at
            WHERE memory_locator_profile_tombstones.canonical_version < EXCLUDED.canonical_version;
            INSERT INTO memory_outbox (
                message_key, event_type, aggregate_type, aggregate_id,
                aggregate_version, workload_class, fairness_key, payload_json,
                status, attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (
                'locator-profile-delete:' || md5(
                    profile.profile_id || ':' || chunk_key || ':' || chunk_version
                ),
                'vector.delete_locator_profile', 'locator_profile_chunk', chunk_key,
                chunk_version, 'projection', 'profile:' || profile.profile_id,
                jsonb_build_object(
                    'chunk_ids', jsonb_build_array(chunk_key),
                    'profile_id', profile.profile_id
                ),
                'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) ON CONFLICT (message_key) WHERE message_key IS NOT NULL DO NOTHING;
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_memory_chunk_locator_profile_events_v2
AFTER INSERT OR UPDATE OR DELETE ON memory_chunks
FOR EACH ROW EXECUTE FUNCTION memory_chunk_locator_profile_events_v2();
