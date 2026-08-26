-- Separate the canonical lifecycle generation authorizing a tombstone from
-- the prior projected generation whose exact Qdrant point must be absent.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';

ALTER TABLE public.memory_locator_profile_tombstones
    ADD COLUMN delete_canonical_version BIGINT;

-- Published pre-0054 transitions incremented retrieval_version while making a
-- chunk ineligible. Repair those tombstones to target the immediately prior
-- active generation. Hard-deleted rows already carry their last active version.
UPDATE public.memory_locator_profile_tombstones AS tombstones
SET delete_canonical_version = COALESCE(
    (
        SELECT receipts.canonical_version
        FROM public.memory_locator_profile_projection_receipts AS receipts
        WHERE receipts.profile_id = tombstones.profile_id
          AND receipts.chunk_id = tombstones.chunk_id
    ),
    CASE
        WHEN tombstones.canonical_version > 1 AND EXISTS (
            SELECT 1
            FROM public.memory_chunks AS chunks
            WHERE chunks.id = tombstones.chunk_id
              AND chunks.retrieval_version = tombstones.canonical_version
              AND chunks.retrieval_locator IS NOT NULL
              AND NOT (
                  chunks.status = 'active'
                  AND chunks.classification IN ('public', 'internal')
              )
        ) THEN tombstones.canonical_version - 1
        ELSE tombstones.canonical_version
    END
);

ALTER TABLE public.memory_locator_profile_tombstones
    ALTER COLUMN delete_canonical_version SET NOT NULL,
    ADD CONSTRAINT ck_locator_profile_tombstone_delete_version
        CHECK (delete_canonical_version > 0);

-- A pre-0054 completion may have acknowledged a no-op delete against the new
-- lifecycle version. Reopen it and enqueue a content-addressed repair. Replay
-- is safe because the provider delete remains exact-version filtered.
UPDATE public.memory_locator_profile_tombstones
SET completed_at = NULL,
    updated_at = CURRENT_TIMESTAMP
WHERE delete_canonical_version <> canonical_version;

INSERT INTO public.memory_outbox (
    message_key, event_type, aggregate_type, aggregate_id,
    aggregate_version, workload_class, fairness_key, payload_json,
    status, attempt_count, next_attempt_at, created_at, updated_at
)
SELECT
    'locator-profile-delete-v2:' || pg_catalog.md5(
        tombstones.profile_id || ':' || tombstones.chunk_id || ':'
        || tombstones.canonical_version || ':' || tombstones.delete_canonical_version
    ),
    'vector.delete_locator_profile', 'locator_profile_chunk', tombstones.chunk_id,
    tombstones.canonical_version, 'projection', 'profile:' || tombstones.profile_id,
    pg_catalog.jsonb_build_object(
        'chunk_ids', pg_catalog.jsonb_build_array(tombstones.chunk_id),
        'profile_id', tombstones.profile_id,
        'delete_canonical_version', tombstones.delete_canonical_version
    ),
    'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM public.memory_locator_profile_tombstones AS tombstones
WHERE tombstones.delete_canonical_version <> tombstones.canonical_version
ON CONFLICT (message_key) WHERE message_key IS NOT NULL DO NOTHING;

CREATE OR REPLACE FUNCTION public.memory_chunk_locator_profile_events_v2()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    profile RECORD;
    chunk_key VARCHAR(80);
    chunk_version BIGINT;
    delete_version BIGINT;
    eligible BOOLEAN;
    old_eligible BOOLEAN := FALSE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.retrieval_locator IS NULL THEN RETURN OLD; END IF;
        chunk_key := OLD.id;
        chunk_version := OLD.retrieval_version;
        delete_version := OLD.retrieval_version;
        eligible := FALSE;
    ELSE
        chunk_key := NEW.id;
        chunk_version := NEW.retrieval_version;
        eligible := NEW.retrieval_locator IS NOT NULL
            AND NEW.status = 'active'
            AND NEW.classification IN ('public', 'internal');
        IF TG_OP = 'UPDATE' THEN
            old_eligible := OLD.retrieval_locator IS NOT NULL
                AND OLD.status = 'active'
                AND OLD.classification IN ('public', 'internal');
        END IF;
        IF TG_OP = 'INSERT' AND NOT eligible THEN RETURN NEW; END IF;
        IF TG_OP = 'UPDATE'
           AND OLD.retrieval_locator IS NULL
           AND NEW.retrieval_locator IS NULL THEN
            RETURN NEW;
        END IF;
    END IF;

    FOR profile IN
        SELECT profile_id FROM public.memory_locator_profiles
        WHERE state IN ('building', 'active', 'retained')
        ORDER BY profile_id
    LOOP
        IF eligible THEN
            DELETE FROM public.memory_locator_profile_tombstones
             WHERE profile_id = profile.profile_id AND chunk_id = chunk_key
               AND canonical_version < chunk_version;
            INSERT INTO public.memory_outbox (
                message_key, event_type, aggregate_type, aggregate_id,
                aggregate_version, workload_class, fairness_key, payload_json,
                status, attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (
                'locator-profile-upsert:' || pg_catalog.md5(
                    profile.profile_id || ':' || chunk_key || ':' || chunk_version
                ),
                'vector.upsert_locator_profile', 'locator_profile_chunk', chunk_key,
                chunk_version, 'projection', 'profile:' || profile.profile_id,
                pg_catalog.jsonb_build_object(
                    'chunk_id', chunk_key, 'profile_id', profile.profile_id
                ),
                'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) ON CONFLICT (message_key) WHERE message_key IS NOT NULL DO NOTHING;
        ELSE
            IF TG_OP <> 'DELETE' THEN
                IF old_eligible THEN
                    delete_version := OLD.retrieval_version;
                ELSE
                    SELECT tombstones.delete_canonical_version
                      INTO delete_version
                      FROM public.memory_locator_profile_tombstones AS tombstones
                     WHERE tombstones.profile_id = profile.profile_id
                       AND tombstones.chunk_id = chunk_key;
                    IF delete_version IS NULL THEN
                        SELECT receipts.canonical_version
                          INTO delete_version
                          FROM public.memory_locator_profile_projection_receipts AS receipts
                         WHERE receipts.profile_id = profile.profile_id
                           AND receipts.chunk_id = chunk_key;
                    END IF;
                    delete_version := COALESCE(delete_version, chunk_version);
                END IF;
            END IF;
            INSERT INTO public.memory_locator_profile_tombstones AS tombstones (
                profile_id, chunk_id, canonical_version, delete_canonical_version,
                created_at, updated_at
            ) VALUES (
                profile.profile_id, chunk_key, chunk_version, delete_version,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) ON CONFLICT (profile_id, chunk_id) DO UPDATE SET
                canonical_version = EXCLUDED.canonical_version,
                delete_canonical_version = EXCLUDED.delete_canonical_version,
                completed_at = NULL,
                updated_at = EXCLUDED.updated_at
            WHERE tombstones.canonical_version < EXCLUDED.canonical_version;
            INSERT INTO public.memory_outbox (
                message_key, event_type, aggregate_type, aggregate_id,
                aggregate_version, workload_class, fairness_key, payload_json,
                status, attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (
                'locator-profile-delete-v2:' || pg_catalog.md5(
                    profile.profile_id || ':' || chunk_key || ':' || chunk_version
                    || ':' || delete_version
                ),
                'vector.delete_locator_profile', 'locator_profile_chunk', chunk_key,
                chunk_version, 'projection', 'profile:' || profile.profile_id,
                pg_catalog.jsonb_build_object(
                    'chunk_ids', pg_catalog.jsonb_build_array(chunk_key),
                    'profile_id', profile.profile_id,
                    'delete_canonical_version', delete_version
                ),
                'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) ON CONFLICT (message_key) WHERE message_key IS NOT NULL DO NOTHING;
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
