-- Repair the locator watermark ACL without assuming the staged 0040 sequence
-- exists, then replace its trigger functions with search-path-safe definitions.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5min';

DO $acl$
BEGIN
    IF pg_catalog.to_regclass('public.memory_locator_commit_watermark_seq') IS NOT NULL THEN
        REVOKE ALL PRIVILEGES ON SEQUENCE public.memory_locator_commit_watermark_seq
        FROM PUBLIC,
             infinity_context_canonical_writer,
             infinity_context_strict_v4_registrar,
             infinity_context_strict_v4_sealer;
        GRANT USAGE ON SEQUENCE public.memory_locator_commit_watermark_seq
        TO infinity_context_canonical_writer;
    END IF;
END
$acl$;

CREATE OR REPLACE FUNCTION public.memory_chunk_locator_watermark_v2()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    NEW.retrieval_commit_watermark := CASE
        WHEN TG_OP = 'INSERT' OR NEW.retrieval_version <> OLD.retrieval_version
            THEN pg_catalog.nextval('public.memory_locator_commit_watermark_seq')
        ELSE OLD.retrieval_commit_watermark
    END;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.memory_chunk_locator_projection_events_v2()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
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
        INSERT INTO public.memory_locator_projection_tombstones AS tombstones (
            chunk_id, canonical_version, created_at, updated_at
        ) VALUES (NEW.id, NEW.retrieval_version, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (chunk_id) DO UPDATE SET
            canonical_version = EXCLUDED.canonical_version,
            legacy_deleted_at = NULL, locator_deleted_at = NULL,
            updated_at = EXCLUDED.updated_at
        WHERE tombstones.canonical_version < EXCLUDED.canonical_version;
        INSERT INTO public.memory_outbox (
            message_key, event_type, aggregate_type, aggregate_id,
            aggregate_version, workload_class, fairness_key, payload_json,
            status, attempt_count, next_attempt_at, created_at, updated_at
        ) VALUES (
            'locator-v2-tombstone:' || NEW.id || ':' || NEW.retrieval_version,
            'vector.delete_chunks', 'locator_chunk', NEW.id, NEW.retrieval_version,
            'projection', 'chunk:' || NEW.id,
            pg_catalog.jsonb_build_object(
                'chunk_ids', pg_catalog.jsonb_build_array(NEW.id)
            ),
            'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        ) ON CONFLICT (message_key) WHERE message_key IS NOT NULL DO NOTHING;
    ELSIF TG_OP = 'INSERT' OR NEW.retrieval_version <> OLD.retrieval_version THEN
        -- A later active version supersedes any completed/pending tombstone for the
        -- same point identity. The versioned upsert remains the repair authority.
        UPDATE public.memory_locator_projection_tombstones SET
            legacy_deleted_at = CURRENT_TIMESTAMP,
            locator_deleted_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE chunk_id = NEW.id AND canonical_version < NEW.retrieval_version;
        INSERT INTO public.memory_outbox (
            message_key, event_type, aggregate_type, aggregate_id,
            aggregate_version, workload_class, fairness_key, payload_json,
            status, attempt_count, next_attempt_at, created_at, updated_at
        ) VALUES (
            'locator-v2-reproject:' || NEW.id || ':' || NEW.retrieval_version,
            'vector.upsert_chunk', 'locator_chunk', NEW.id, NEW.retrieval_version,
            'projection', 'chunk:' || NEW.id,
            pg_catalog.jsonb_build_object('chunk_id', NEW.id),
            'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        ) ON CONFLICT (message_key) WHERE message_key IS NOT NULL DO NOTHING;
    END IF;
    RETURN NULL;
END;
$$;

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
                profile_id, chunk_id, canonical_version, created_at, updated_at
            ) VALUES (
                profile.profile_id, chunk_key, chunk_version, CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            ) ON CONFLICT (profile_id, chunk_id) DO UPDATE SET
                canonical_version = EXCLUDED.canonical_version,
                completed_at = NULL,
                updated_at = EXCLUDED.updated_at
            WHERE tombstones.canonical_version < EXCLUDED.canonical_version;
            INSERT INTO public.memory_outbox (
                message_key, event_type, aggregate_type, aggregate_id,
                aggregate_version, workload_class, fairness_key, payload_json,
                status, attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (
                'locator-profile-delete:' || pg_catalog.md5(
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
