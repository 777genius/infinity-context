-- Make the exact canonical document authoritative for every locator child.
-- This is a forward-only drain boundary.  The staged migration runner first
-- installs this short cutover, repairs divergent rows in bounded transactions,
-- validates the constraint online, and then records this migration.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '30s';

-- Add the protocol declaration inside the same transaction as the drain check.
-- A failed check rolls this catalog change back, while a resumed staged run can
-- distinguish a post-cutover capable incarnation from a pre-cutover reader.
ALTER TABLE public.memory_locator_runtime_incarnations
    ADD COLUMN IF NOT EXISTS locator_parent_capability BIGINT NOT NULL DEFAULT 0;

-- Every post-0046 reader registers an incarnation.  An unsealed incarnation
-- without the post-cutover declaration may still be executing the pre-0059 read
-- predicate, so cutover must fail before committing any catalog change.  After
-- cutover, pre-0059 binaries also fail startup on the unknown migration-history row.
DO $fence$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.memory_locator_runtime_incarnations
        WHERE sealed_dead_generation IS NULL
          AND locator_parent_capability <> 1
    ) THEN
        RAISE EXCEPTION
            '0059 locator parent cutover requires every prior runtime incarnation to be sealed dead';
    END IF;
END
$fence$;

ALTER TABLE public.memory_chunks
    ADD COLUMN IF NOT EXISTS retrieval_parent_version BIGINT NOT NULL DEFAULT 1;

DO $constraint$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conname = 'ck_memory_chunks_retrieval_parent_version_positive'
          AND conrelid = 'public.memory_chunks'::pg_catalog.regclass
    ) THEN
        ALTER TABLE public.memory_chunks
            ADD CONSTRAINT ck_memory_chunks_retrieval_parent_version_positive
            CHECK (retrieval_parent_version BETWEEN 1 AND 9007199254740991) NOT VALID;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conname = 'ck_locator_runtime_parent_capability'
          AND conrelid = 'public.memory_locator_runtime_incarnations'::pg_catalog.regclass
    ) THEN
        ALTER TABLE public.memory_locator_runtime_incarnations
            ADD CONSTRAINT ck_locator_runtime_parent_capability
            CHECK (locator_parent_capability IN (0, 1)) NOT VALID;
    END IF;
END
$constraint$;

-- A catalog-enforced protocol declaration closes the crash window between the
-- staged cutover and migration-ledger commit.  Custom GUCs are not an authority
-- secret; this value is a binary protocol capability that pre-0059 code never
-- sends.  Dead-owner sealing remains possible without starting a reader.
CREATE OR REPLACE FUNCTION public.memory_locator_require_parent_capability_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.sealed_dead_generation IS NULL
       AND NEW.locator_parent_capability <> 1 THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'runtime binary lacks locator parent lifecycle capability 0059';
    END IF;
    IF NEW.sealed_dead_generation IS NULL
       AND (TG_OP = 'INSERT' OR OLD.locator_parent_capability IS DISTINCT FROM 1)
       AND pg_catalog.current_setting(
           'infinity_context.locator_parent_capability', TRUE
       ) IS DISTINCT FROM '0059' THEN
        RAISE EXCEPTION USING
            ERRCODE = '55000',
            MESSAGE = 'runtime binary lacks locator parent lifecycle capability 0059';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_00_locator_runtime_parent_capability
    ON public.memory_locator_runtime_incarnations;
CREATE TRIGGER trg_00_locator_runtime_parent_capability
BEFORE INSERT OR UPDATE ON public.memory_locator_runtime_incarnations
FOR EACH ROW EXECUTE FUNCTION public.memory_locator_require_parent_capability_v1();

CREATE OR REPLACE FUNCTION public.memory_chunk_retrieval_fence_v2()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public, pg_temp
AS $$
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
        OLD.retrieval_category, OLD.retrieval_tags_json,
        OLD.retrieval_parent_version
    ) IS DISTINCT FROM ROW(
        NEW.text, NEW.normalized_text, NEW.status, NEW.classification,
        NEW.space_id, NEW.memory_scope_id, NEW.thread_id, NEW.document_id,
        NEW.retrieval_locator, NEW.retrieval_source_key,
        NEW.retrieval_projection_generation, NEW.retrieval_sequence_ordinal,
        NEW.retrieval_kind, NEW.retrieval_actor_keys_json,
        NEW.retrieval_start_at, NEW.retrieval_end_at,
        NEW.retrieval_relative_start_ms, NEW.retrieval_relative_end_ms,
        NEW.retrieval_category, NEW.retrieval_tags_json,
        NEW.retrieval_parent_version
    );
    NEW.retrieval_version := CASE WHEN retrieval_changed
        THEN OLD.retrieval_version + 1 ELSE OLD.retrieval_version END;
    RETURN NEW;
END;
$$;

-- retrieval_parent_version is derived lifecycle bookkeeping: repair and parent
-- invalidation must be able to rotate it even for a historical orphan whose
-- document no longer exists.  Keep the strict-v4 document-child fences on
-- INSERT, DELETE, and every pre-0059 chunk column, excluding only that new
-- maintenance column.  PostgreSQL UPDATE OF gating is based on the explicit
-- SET target list, so any content, identity, status, locator, or other existing
-- column mutation still crosses both benchmark lock and policy functions.
DROP TRIGGER IF EXISTS trg_00_memory_chunks_benchmark_document_child_lock
    ON public.memory_chunks;
CREATE TRIGGER trg_00_memory_chunks_benchmark_document_child_lock
BEFORE INSERT OR DELETE OR UPDATE OF
    id, space_id, memory_scope_id, thread_id, document_id, episode_id,
    source_type, source_external_id, source_hash, kind, text, normalized_text,
    status, sequence, char_start, char_end, token_estimate, classification,
    created_at, updated_at, metadata_json, retrieval_locator,
    retrieval_source_key, retrieval_projection_generation,
    retrieval_sequence_ordinal, retrieval_kind, retrieval_version,
    retrieval_actor_keys_json, retrieval_start_at, retrieval_end_at,
    retrieval_relative_start_ms, retrieval_relative_end_ms,
    retrieval_category, retrieval_tags_json, retrieval_commit_watermark
ON public.memory_chunks
FOR EACH ROW EXECUTE FUNCTION
    public.memory_comparison_lock_benchmark_document_child_target();

DROP TRIGGER IF EXISTS trg_memory_chunks_benchmark_document_child_fence
    ON public.memory_chunks;
CREATE TRIGGER trg_memory_chunks_benchmark_document_child_fence
BEFORE INSERT OR DELETE OR UPDATE OF
    id, space_id, memory_scope_id, thread_id, document_id, episode_id,
    source_type, source_external_id, source_hash, kind, text, normalized_text,
    status, sequence, char_start, char_end, token_estimate, classification,
    created_at, updated_at, metadata_json, retrieval_locator,
    retrieval_source_key, retrieval_projection_generation,
    retrieval_sequence_ordinal, retrieval_kind, retrieval_version,
    retrieval_actor_keys_json, retrieval_start_at, retrieval_end_at,
    retrieval_relative_start_ms, retrieval_relative_end_ms,
    retrieval_category, retrieval_tags_json, retrieval_commit_watermark
ON public.memory_chunks
FOR EACH ROW EXECUTE FUNCTION
    public.memory_comparison_enforce_benchmark_document_child_fence();

-- The advisory identity also exists when the parent row does not, closing the
-- absent/mismatched-parent race.  Document lifecycle triggers take this same
-- lock after the profile evidence lock, matching the chunk statement-trigger
-- order.  The row lock remains stronger than KEY SHARE because status and
-- projection changes do not modify the key.  A locator child may retract after
-- its exact parent becomes inactive or changes mutable coordinates, but the
-- parent must still exist and the child's parent/locator identity coordinates
-- must remain unchanged.  The same narrow
-- rule lets an active, retrieval-eligible child tighten to restricted: the
-- extant parent retains its immutable coordinates, and no lifecycle or
-- identity change can ride along.  Restricted-to-eligible
-- restoration takes the ordinary admission path.  Repair-only version bumps
-- do not re-admit a divergent historical row and bypass this check.
CREATE OR REPLACE FUNCTION public.memory_chunk_require_locator_parent_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    parent RECORD;
    identity_preserving_retraction BOOLEAN := FALSE;
    identity_preserving_classification_tightening BOOLEAN := FALSE;
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.retrieval_locator IS NOT NULL
       AND OLD.status IS DISTINCT FROM 'deleted'
       AND NEW.status = 'deleted' THEN
        IF ROW(
            OLD.id, OLD.space_id, OLD.memory_scope_id, OLD.thread_id,
            OLD.document_id, OLD.source_type, OLD.source_external_id,
            OLD.source_hash, OLD.classification, OLD.retrieval_locator,
            OLD.retrieval_source_key, OLD.retrieval_projection_generation,
            OLD.retrieval_sequence_ordinal, OLD.retrieval_kind,
            OLD.retrieval_category
        ) IS DISTINCT FROM ROW(
            NEW.id, NEW.space_id, NEW.memory_scope_id, NEW.thread_id,
            NEW.document_id, NEW.source_type, NEW.source_external_id,
            NEW.source_hash, NEW.classification, NEW.retrieval_locator,
            NEW.retrieval_source_key, NEW.retrieval_projection_generation,
            NEW.retrieval_sequence_ordinal, NEW.retrieval_kind,
            NEW.retrieval_category
        ) THEN
            RAISE EXCEPTION USING
                ERRCODE = '23514',
                MESSAGE = 'locator chunk retraction must preserve canonical parent identity';
        END IF;
        identity_preserving_retraction := TRUE;
    END IF;

    IF TG_OP = 'UPDATE'
       AND OLD.retrieval_locator IS NOT NULL
       AND OLD.status = 'active'
       AND NEW.status = 'active'
       AND OLD.classification IN ('public', 'internal')
       AND NEW.classification = 'restricted' THEN
        IF ROW(
            OLD.id, OLD.space_id, OLD.memory_scope_id, OLD.thread_id,
            OLD.document_id, OLD.source_type, OLD.source_external_id,
            OLD.source_hash, OLD.status, OLD.retrieval_locator,
            OLD.retrieval_source_key, OLD.retrieval_projection_generation,
            OLD.retrieval_sequence_ordinal, OLD.retrieval_kind,
            OLD.retrieval_category
        ) IS DISTINCT FROM ROW(
            NEW.id, NEW.space_id, NEW.memory_scope_id, NEW.thread_id,
            NEW.document_id, NEW.source_type, NEW.source_external_id,
            NEW.source_hash, NEW.status, NEW.retrieval_locator,
            NEW.retrieval_source_key, NEW.retrieval_projection_generation,
            NEW.retrieval_sequence_ordinal, NEW.retrieval_kind,
            NEW.retrieval_category
        ) THEN
            RAISE EXCEPTION USING
                ERRCODE = '23514',
                MESSAGE = 'locator chunk classification tightening must preserve canonical parent identity';
        END IF;
        identity_preserving_classification_tightening := TRUE;
    END IF;

    IF NEW.retrieval_locator IS NULL OR (
        TG_OP = 'UPDATE'
        AND ROW(
            OLD.space_id, OLD.memory_scope_id, OLD.thread_id, OLD.document_id,
            OLD.source_type, OLD.source_external_id, OLD.classification,
            OLD.status, OLD.retrieval_locator
        ) IS NOT DISTINCT FROM ROW(
            NEW.space_id, NEW.memory_scope_id, NEW.thread_id, NEW.document_id,
            NEW.source_type, NEW.source_external_id, NEW.classification,
            NEW.status, NEW.retrieval_locator
        )
    ) THEN
        RETURN NEW;
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('locator-parent:' || NEW.document_id, 0)
    );
    SELECT document.* INTO parent
    FROM public.memory_documents AS document
    WHERE document.id = NEW.document_id
    FOR NO KEY UPDATE OF document;
    -- Retraction and classification tightening only remove retrieval evidence.
    -- Require the parent row, but not admission eligibility.  OLD/NEW guards
    -- above prevent the child from changing identity; comparing its preserved
    -- coordinates to the parent's current mutable coordinates would strand
    -- removal after a parent coordinate edit.
    IF identity_preserving_retraction
       OR identity_preserving_classification_tightening THEN
        IF NOT FOUND THEN
            RAISE EXCEPTION USING
                ERRCODE = '23503',
                MESSAGE = 'locator chunk egress requires its canonical document parent';
        END IF;
        RETURN NEW;
    END IF;

    -- Admission and restoration retain the full exact active projected-parent
    -- contract.  Egress cannot use this branch to re-admit retrieval evidence.
    IF NOT FOUND
       OR parent.space_id IS DISTINCT FROM NEW.space_id
       OR parent.memory_scope_id IS DISTINCT FROM NEW.memory_scope_id
       OR parent.thread_id IS DISTINCT FROM NEW.thread_id
       OR parent.source_type IS DISTINCT FROM NEW.source_type
       OR parent.source_external_id IS DISTINCT FROM NEW.source_external_id
       OR parent.classification IS DISTINCT FROM NEW.classification
       OR parent.status IS DISTINCT FROM 'active'
       OR parent.retrieval_projected IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION USING
            ERRCODE = '23503',
            MESSAGE = 'locator chunk requires an eligible exact canonical document parent';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_00_memory_chunk_require_locator_parent ON public.memory_chunks;
CREATE TRIGGER trg_00_memory_chunk_require_locator_parent
BEFORE INSERT OR UPDATE ON public.memory_chunks
FOR EACH ROW EXECUTE FUNCTION public.memory_chunk_require_locator_parent_v1();

CREATE OR REPLACE FUNCTION public.memory_document_lock_locator_parent_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE document_key VARCHAR(80);
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.id IS DISTINCT FROM NEW.id THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'canonical document identity is immutable';
    END IF;
    document_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END;
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('locator-parent:' || document_key, 0)
    );
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

-- Profile-owned cleanup is the only derived cleanup lane.  Keep the exact
-- parent predicate inline so ordinary runtime writes cross no new function ACL.
CREATE OR REPLACE FUNCTION public.memory_chunk_locator_profile_events_v2()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
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
            AND NEW.classification IN ('public', 'internal')
            AND EXISTS (
                SELECT 1 FROM public.memory_documents AS document
                WHERE document.id = NEW.document_id
                  AND document.space_id = NEW.space_id
                  AND document.memory_scope_id = NEW.memory_scope_id
                  AND document.thread_id IS NOT DISTINCT FROM NEW.thread_id
                  AND document.source_type = NEW.source_type
                  AND document.source_external_id = NEW.source_external_id
                  AND document.classification = NEW.classification
                  AND document.status = 'active'
                  AND document.retrieval_projected = TRUE
            );
        IF TG_OP = 'INSERT' AND NOT eligible THEN RETURN NEW; END IF;
        IF TG_OP = 'UPDATE' AND OLD.retrieval_locator IS NULL
           AND NEW.retrieval_locator IS NULL THEN RETURN NEW; END IF;
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

CREATE OR REPLACE FUNCTION public.memory_document_invalidate_locator_children_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE document_key VARCHAR(80);
BEGIN
    document_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END;
    UPDATE public.memory_chunks
       SET retrieval_parent_version = retrieval_parent_version + 1
     WHERE document_id = document_key
       AND retrieval_locator IS NOT NULL;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.memory_document_invalidate_locator_children_v1() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_00_document_locator_profile_evidence_insert
    ON public.memory_documents;
CREATE TRIGGER trg_00_document_locator_profile_evidence_insert
BEFORE INSERT ON public.memory_documents
FOR EACH ROW WHEN (NEW.retrieval_projected)
EXECUTE FUNCTION public.memory_locator_profile_invalidate_evidence_v1();

DROP TRIGGER IF EXISTS trg_00_document_locator_profile_evidence_update
    ON public.memory_documents;
CREATE TRIGGER trg_00_document_locator_profile_evidence_update
BEFORE UPDATE ON public.memory_documents
FOR EACH ROW WHEN (
    (OLD.retrieval_projected OR NEW.retrieval_projected)
    AND ROW(
        OLD.status, OLD.classification, OLD.retrieval_projected,
        OLD.space_id, OLD.memory_scope_id, OLD.thread_id,
        OLD.source_type, OLD.source_external_id
    ) IS DISTINCT FROM ROW(
        NEW.status, NEW.classification, NEW.retrieval_projected,
        NEW.space_id, NEW.memory_scope_id, NEW.thread_id,
        NEW.source_type, NEW.source_external_id
    )
)
EXECUTE FUNCTION public.memory_locator_profile_invalidate_evidence_v1();

DROP TRIGGER IF EXISTS trg_00_document_locator_profile_evidence_delete
    ON public.memory_documents;
CREATE TRIGGER trg_00_document_locator_profile_evidence_delete
BEFORE DELETE ON public.memory_documents
FOR EACH ROW WHEN (OLD.retrieval_projected)
EXECUTE FUNCTION public.memory_locator_profile_invalidate_evidence_v1();

-- These run after the trg_00 profile-evidence triggers.  Chunk admissions first
-- cross the corresponding statement-level evidence trigger and then take this
-- identity, so both mutation paths preserve evidence -> profiles -> parent.
DROP TRIGGER IF EXISTS trg_01_document_locator_parent_lock_insert
    ON public.memory_documents;
CREATE TRIGGER trg_01_document_locator_parent_lock_insert
BEFORE INSERT ON public.memory_documents
FOR EACH ROW WHEN (NEW.retrieval_projected)
EXECUTE FUNCTION public.memory_document_lock_locator_parent_v1();

DROP TRIGGER IF EXISTS trg_01_document_locator_parent_lock_update
    ON public.memory_documents;
CREATE TRIGGER trg_01_document_locator_parent_lock_update
BEFORE UPDATE ON public.memory_documents
FOR EACH ROW WHEN (
    OLD.id IS DISTINCT FROM NEW.id OR (OLD.retrieval_projected OR NEW.retrieval_projected)
    AND ROW(
        OLD.status, OLD.classification, OLD.retrieval_projected,
        OLD.space_id, OLD.memory_scope_id, OLD.thread_id,
        OLD.source_type, OLD.source_external_id
    ) IS DISTINCT FROM ROW(
        NEW.status, NEW.classification, NEW.retrieval_projected,
        NEW.space_id, NEW.memory_scope_id, NEW.thread_id,
        NEW.source_type, NEW.source_external_id
    )
)
EXECUTE FUNCTION public.memory_document_lock_locator_parent_v1();

DROP TRIGGER IF EXISTS trg_01_document_locator_parent_lock_delete
    ON public.memory_documents;
CREATE TRIGGER trg_01_document_locator_parent_lock_delete
BEFORE DELETE ON public.memory_documents
FOR EACH ROW WHEN (OLD.retrieval_projected)
EXECUTE FUNCTION public.memory_document_lock_locator_parent_v1();

DROP TRIGGER IF EXISTS trg_document_invalidate_locator_children_insert
    ON public.memory_documents;
CREATE TRIGGER trg_document_invalidate_locator_children_insert
AFTER INSERT ON public.memory_documents
FOR EACH ROW WHEN (NEW.retrieval_projected)
EXECUTE FUNCTION public.memory_document_invalidate_locator_children_v1();

DROP TRIGGER IF EXISTS trg_document_invalidate_locator_children_update
    ON public.memory_documents;
CREATE TRIGGER trg_document_invalidate_locator_children_update
AFTER UPDATE ON public.memory_documents
FOR EACH ROW WHEN (
    OLD.id IS DISTINCT FROM NEW.id OR ROW(
        OLD.status, OLD.classification, OLD.retrieval_projected,
        OLD.space_id, OLD.memory_scope_id, OLD.thread_id,
        OLD.source_type, OLD.source_external_id
    ) IS DISTINCT FROM ROW(
        NEW.status, NEW.classification, NEW.retrieval_projected,
        NEW.space_id, NEW.memory_scope_id, NEW.thread_id,
        NEW.source_type, NEW.source_external_id
    )
)
EXECUTE FUNCTION public.memory_document_invalidate_locator_children_v1();

DROP TRIGGER IF EXISTS trg_document_invalidate_locator_children_delete
    ON public.memory_documents;
CREATE TRIGGER trg_document_invalidate_locator_children_delete
AFTER DELETE ON public.memory_documents
FOR EACH ROW EXECUTE FUNCTION public.memory_document_invalidate_locator_children_v1();
