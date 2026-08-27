-- Record the provider generation actually observed and deleted.  Canonical
-- lifecycle generations cannot infer derived state after pending/dead/crashed
-- upserts, and projection receipts may have been removed by false completion.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';

ALTER TABLE public.memory_locator_profile_tombstones
    ADD COLUMN delete_canonical_version BIGINT,
    ADD COLUMN provider_observed_at TIMESTAMPTZ,
    ADD COLUMN delete_authorized_mutation_epoch BIGINT,
    ADD COLUMN delete_completed_mutation_epoch BIGINT;

ALTER TABLE public.memory_locator_profile_tombstones
    ADD CONSTRAINT ck_locator_profile_tombstone_delete_version
        CHECK (delete_canonical_version IS NULL OR delete_canonical_version > 0),
    ADD CONSTRAINT ck_locator_profile_tombstone_authorized_epoch
        CHECK (
            delete_authorized_mutation_epoch IS NULL
            OR delete_authorized_mutation_epoch >= 0
        ),
    ADD CONSTRAINT ck_locator_profile_tombstone_completed_epoch
        CHECK (
            delete_completed_mutation_epoch IS NULL
            OR delete_completed_mutation_epoch >= delete_authorized_mutation_epoch
        );

-- No pre-0054 completion contains a provider observation.  Reopen every
-- historical tombstone and let the application observe the deterministic
-- point id.  This works even when a prior false completion removed its receipt.
UPDATE public.memory_locator_profile_tombstones
SET completed_at = NULL,
    delete_canonical_version = NULL,
    provider_observed_at = NULL,
    delete_authorized_mutation_epoch = NULL,
    delete_completed_mutation_epoch = NULL,
    updated_at = CURRENT_TIMESTAMP;

ALTER TABLE public.memory_locator_profile_tombstones
    ADD CONSTRAINT ck_locator_profile_tombstone_observation
        CHECK (
            (completed_at IS NULL AND provider_observed_at IS NULL
                AND delete_completed_mutation_epoch IS NULL)
            OR (completed_at IS NOT NULL AND provider_observed_at IS NOT NULL
                AND delete_authorized_mutation_epoch IS NOT NULL
                AND delete_completed_mutation_epoch IS NOT NULL)
        );

INSERT INTO public.memory_outbox (
    message_key, event_type, aggregate_type, aggregate_id,
    aggregate_version, workload_class, fairness_key, payload_json,
    status, attempt_count, next_attempt_at, created_at, updated_at
)
SELECT
    'locator-profile-delete-observe:' || pg_catalog.md5(
        tombstones.profile_id || ':' || tombstones.chunk_id || ':'
        || tombstones.canonical_version
    ),
    'vector.delete_locator_profile', 'locator_profile_chunk', tombstones.chunk_id,
    tombstones.canonical_version, 'projection', 'profile:' || tombstones.profile_id,
    pg_catalog.jsonb_build_object(
        'chunk_ids', pg_catalog.jsonb_build_array(tombstones.chunk_id),
        'profile_id', tombstones.profile_id
    ),
    'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM public.memory_locator_profile_tombstones AS tombstones
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
            INSERT INTO public.memory_locator_profile_tombstones AS tombstones (
                profile_id, chunk_id, canonical_version, delete_canonical_version,
                provider_observed_at, delete_authorized_mutation_epoch,
                delete_completed_mutation_epoch, created_at, updated_at
            ) VALUES (
                profile.profile_id, chunk_key, chunk_version, NULL,
                NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) ON CONFLICT (profile_id, chunk_id) DO UPDATE SET
                canonical_version = EXCLUDED.canonical_version,
                delete_canonical_version = NULL,
                provider_observed_at = NULL,
                delete_authorized_mutation_epoch = NULL,
                delete_completed_mutation_epoch = NULL,
                completed_at = NULL,
                updated_at = EXCLUDED.updated_at
            WHERE tombstones.canonical_version < EXCLUDED.canonical_version;
            INSERT INTO public.memory_outbox (
                message_key, event_type, aggregate_type, aggregate_id,
                aggregate_version, workload_class, fairness_key, payload_json,
                status, attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (
                'locator-profile-delete-observe:' || pg_catalog.md5(
                    profile.profile_id || ':' || chunk_key || ':' || chunk_version
                ),
                'vector.delete_locator_profile', 'locator_profile_chunk', chunk_key,
                chunk_version, 'projection', 'profile:' || profile.profile_id,
                pg_catalog.jsonb_build_object(
                    'chunk_ids', pg_catalog.jsonb_build_array(chunk_key),
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
