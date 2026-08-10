-- Enable the least-privilege strict-v4 canonical fact writer.
DO $fact_writer_precondition$
DECLARE
    role_row RECORD;
BEGIN
    SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
           rolreplication, rolbypassrls
    INTO role_row
    FROM pg_catalog.pg_roles
    WHERE rolname = 'infinity_context_strict_v4_fact_writer';
    IF role_row IS NULL
       OR role_row.rolcanlogin OR role_row.rolsuper OR role_row.rolcreatedb
       OR role_row.rolcreaterole OR role_row.rolreplication
       OR role_row.rolbypassrls
       OR pg_catalog.has_schema_privilege(
           'infinity_context_strict_v4_fact_writer', 'public', 'CREATE'
       )
       OR NOT pg_catalog.has_schema_privilege(
           'infinity_context_strict_v4_fact_writer', 'public', 'USAGE'
       )
       OR EXISTS (
           SELECT 1 FROM pg_catalog.pg_roles AS inherited
           WHERE inherited.rolname <> 'infinity_context_strict_v4_fact_writer'
             AND pg_catalog.pg_has_role(
                 'infinity_context_strict_v4_fact_writer',
                 inherited.oid,
                 'MEMBER'
             )
       )
    THEN
        RAISE EXCEPTION 'unsafe strict-v4 fact-writer capability role'
            USING ERRCODE = '42501';
    END IF;
END
$fact_writer_precondition$;

REVOKE ALL ON
    public.memory_comparison_benchmark_runs,
    public.memory_cleanup_v3_context_authorities,
    public.memory_comparison_strict_v4_preparations,
    public.memory_spaces,
    public.memory_scopes,
    public.memory_threads,
    public.memory_facts,
    public.memory_episodes,
    public.memory_documents,
    public.memory_chunks,
    public.memory_fact_operation_receipts,
    public.memory_idempotency_records,
    public.memory_anchors,
    public.memory_assets,
    public.memory_asset_extraction_jobs,
    public.memory_fact_relations,
    public.memory_fact_temporal_decisions,
    public.memory_suggestions,
    public.memory_captures,
    public.memory_context_links,
    public.memory_context_link_suggestions,
    public.memory_projection_result_receipts,
    public.memory_projection_receipt_claims,
    public.memory_projection_target_identities,
    public.memory_projection_receipt_identity_links,
    public.memory_cleanup_inventory_materializations,
    public.memory_cleanup_inventory_keys,
    public.memory_source_refs,
    public.memory_fact_versions,
    public.memory_outbox
FROM infinity_context_strict_v4_fact_writer;

REVOKE ALL ON SEQUENCE
    public.memory_source_refs_id_seq,
    public.memory_fact_versions_id_seq,
    public.memory_outbox_id_seq,
    public.memory_idempotency_records_id_seq
FROM infinity_context_strict_v4_fact_writer;

GRANT SELECT ON
    public.memory_comparison_benchmark_runs,
    public.memory_cleanup_v3_context_authorities,
    public.memory_comparison_strict_v4_preparations,
    public.memory_spaces,
    public.memory_scopes,
    public.memory_threads,
    public.memory_facts,
    public.memory_fact_versions,
    public.memory_source_refs,
    public.memory_outbox,
    public.memory_fact_operation_receipts
TO infinity_context_strict_v4_fact_writer;

GRANT INSERT ON
    public.memory_scopes,
    public.memory_threads,
    public.memory_facts,
    public.memory_fact_versions,
    public.memory_source_refs,
    public.memory_outbox,
    public.memory_fact_operation_receipts
TO infinity_context_strict_v4_fact_writer;

GRANT DELETE ON public.memory_source_refs
TO infinity_context_strict_v4_fact_writer;

GRANT USAGE ON SEQUENCE
    public.memory_source_refs_id_seq,
    public.memory_fact_versions_id_seq,
    public.memory_outbox_id_seq
TO infinity_context_strict_v4_fact_writer;

CREATE OR REPLACE FUNCTION memory_comparison_is_strict_v4_canonical_writer()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
SELECT COALESCE((
    SELECT current_user = session_user
       AND role.rolcanlogin
       AND NOT role.rolsuper
       AND NOT role.rolbypassrls
       AND NOT role.rolcreatedb
       AND NOT role.rolcreaterole
       AND NOT role.rolreplication
       AND NOT pg_catalog.has_schema_privilege(role.oid, 'public', 'CREATE')
       AND (
           pg_catalog.pg_has_role(
               role.oid, 'infinity_context_canonical_writer', 'MEMBER'
           ) <> pg_catalog.pg_has_role(
               role.oid, 'infinity_context_strict_v4_fact_writer', 'MEMBER'
           )
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_roles AS granted_role
           WHERE granted_role.oid <> role.oid
             AND granted_role.rolname NOT IN (
                 'infinity_context_canonical_writer',
                 'infinity_context_strict_v4_fact_writer'
             )
             AND pg_catalog.pg_has_role(role.oid, granted_role.oid, 'MEMBER')
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           WHERE namespace.nspname = 'public'
             AND relation.relname = ANY(ARRAY[
                 'memory_comparison_benchmark_runs',
                 'memory_cleanup_v3_context_authorities',
                 'memory_comparison_strict_v4_preparations',
                 'memory_spaces', 'memory_scopes', 'memory_threads',
                 'memory_facts', 'memory_episodes', 'memory_documents',
                 'memory_chunks', 'memory_fact_operation_receipts',
                 'memory_idempotency_records', 'memory_anchors',
                 'memory_assets', 'memory_asset_extraction_jobs',
                 'memory_fact_relations', 'memory_fact_temporal_decisions',
                 'memory_suggestions', 'memory_captures',
                 'memory_context_links', 'memory_context_link_suggestions',
                 'memory_projection_result_receipts',
                 'memory_projection_receipt_claims',
                 'memory_projection_target_identities',
                 'memory_projection_receipt_identity_links',
                 'memory_cleanup_inventory_materializations',
                 'memory_cleanup_inventory_keys',
                 'memory_source_refs', 'memory_fact_versions', 'memory_outbox',
                 'memory_source_refs_id_seq', 'memory_fact_versions_id_seq',
                 'memory_outbox_id_seq',
                 'memory_idempotency_records_id_seq'
             ]::text[])
             AND pg_catalog.pg_has_role(role.oid, relation.relowner, 'MEMBER')
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_namespace AS namespace
           WHERE namespace.nspname = 'public'
             AND pg_catalog.pg_has_role(role.oid, namespace.nspowner, 'MEMBER')
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = procedure.pronamespace
           WHERE namespace.nspname = 'public'
             AND procedure.proname = ANY(ARRAY[
                 'memory_comparison_is_strict_v4_canonical_writer',
                 'memory_comparison_enforce_benchmark_writer_fence',
                 'memory_cleanup_enforce_v3_context_authority_immutable',
                 'memory_comparison_lock_strict_v4_registration_targets',
                 'memory_comparison_lock_strict_v4_seal_targets',
                 'memory_comparison_enforce_strict_v4_preparation_immutable',
                 'memory_comparison_close_strict_v4_preparation',
                 'memory_comparison_lock_benchmark_writer_target',
                 'memory_comparison_lock_benchmark_fact_child_target',
                 'memory_comparison_enforce_benchmark_fact_child_fence',
                 'memory_comparison_enforce_benchmark_fact_receipt',
                 'memory_comparison_verify_benchmark_fact_outbox_receipt'
             ]::text[])
             AND pg_catalog.pg_has_role(role.oid, procedure.proowner, 'MEMBER')
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
           WHERE namespace.nspname = 'public'
             AND relation.relname = ANY(ARRAY[
                 'memory_comparison_benchmark_runs',
                 'memory_cleanup_v3_context_authorities',
                 'memory_comparison_strict_v4_preparations',
                 'memory_spaces', 'memory_scopes', 'memory_threads',
                 'memory_facts', 'memory_episodes', 'memory_documents',
                 'memory_chunks', 'memory_fact_operation_receipts',
                 'memory_idempotency_records', 'memory_anchors',
                 'memory_assets', 'memory_asset_extraction_jobs',
                 'memory_fact_relations', 'memory_fact_temporal_decisions',
                 'memory_suggestions', 'memory_captures',
                 'memory_context_links', 'memory_context_link_suggestions',
                 'memory_projection_result_receipts',
                 'memory_projection_receipt_claims',
                 'memory_projection_target_identities',
                 'memory_projection_receipt_identity_links',
                 'memory_cleanup_inventory_materializations',
                 'memory_cleanup_inventory_keys',
                 'memory_source_refs', 'memory_fact_versions', 'memory_outbox',
                 'memory_source_refs_id_seq', 'memory_fact_versions_id_seq',
                 'memory_outbox_id_seq',
                 'memory_idempotency_records_id_seq'
             ]::text[])
             AND acl.grantee = role.oid
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
           WHERE namespace.nspname = 'public'
             AND relation.relname = ANY(ARRAY[
                 'memory_comparison_benchmark_runs',
                 'memory_cleanup_v3_context_authorities',
                 'memory_comparison_strict_v4_preparations',
                 'memory_spaces', 'memory_scopes', 'memory_threads',
                 'memory_facts', 'memory_episodes', 'memory_documents',
                 'memory_chunks', 'memory_fact_operation_receipts',
                 'memory_idempotency_records', 'memory_anchors',
                 'memory_assets', 'memory_asset_extraction_jobs',
                 'memory_fact_relations', 'memory_fact_temporal_decisions',
                 'memory_suggestions', 'memory_captures',
                 'memory_context_links', 'memory_context_link_suggestions',
                 'memory_projection_result_receipts',
                 'memory_projection_receipt_claims',
                 'memory_projection_target_identities',
                 'memory_projection_receipt_identity_links',
                 'memory_cleanup_inventory_materializations',
                 'memory_cleanup_inventory_keys',
                 'memory_source_refs', 'memory_fact_versions', 'memory_outbox',
                 'memory_source_refs_id_seq', 'memory_fact_versions_id_seq',
                 'memory_outbox_id_seq',
                 'memory_idempotency_records_id_seq'
             ]::text[])
             AND acl.grantee = 0
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.unnest(ARRAY[
               'SELECT', 'INSERT', 'UPDATE', 'DELETE',
               'TRUNCATE', 'REFERENCES', 'TRIGGER'
           ]::text[]) AS privilege(name)
           WHERE namespace.nspname = 'public'
             AND relation.relname = ANY(ARRAY[
                 'memory_comparison_benchmark_runs',
                 'memory_cleanup_v3_context_authorities',
                 'memory_comparison_strict_v4_preparations',
                 'memory_spaces', 'memory_scopes', 'memory_threads',
                 'memory_facts', 'memory_episodes', 'memory_documents',
                 'memory_chunks', 'memory_fact_operation_receipts',
                 'memory_idempotency_records', 'memory_anchors',
                 'memory_assets', 'memory_asset_extraction_jobs',
                 'memory_fact_relations', 'memory_fact_temporal_decisions',
                 'memory_suggestions', 'memory_captures',
                 'memory_context_links', 'memory_context_link_suggestions',
                 'memory_projection_result_receipts',
                 'memory_projection_receipt_claims',
                 'memory_projection_target_identities',
                 'memory_projection_receipt_identity_links',
                 'memory_cleanup_inventory_materializations',
                 'memory_cleanup_inventory_keys',
                 'memory_source_refs', 'memory_fact_versions', 'memory_outbox'
             ]::text[])
             AND relation.relkind <> 'S'
             AND pg_catalog.has_table_privilege(
                 role.oid,
                 relation.oid,
                 privilege.name
             ) IS DISTINCT FROM CASE
                 WHEN privilege.name = 'SELECT' THEN
                     (pg_catalog.pg_has_role(
                         role.oid, 'infinity_context_canonical_writer', 'MEMBER'
                      ) AND relation.relname IN (
                          'memory_comparison_benchmark_runs',
                          'memory_cleanup_v3_context_authorities',
                          'memory_comparison_strict_v4_preparations',
                          'memory_idempotency_records'
                      )) OR (pg_catalog.pg_has_role(
                         role.oid, 'infinity_context_strict_v4_fact_writer', 'MEMBER'
                      ) AND relation.relname IN (
                          'memory_comparison_benchmark_runs',
                          'memory_cleanup_v3_context_authorities',
                          'memory_comparison_strict_v4_preparations',
                          'memory_spaces', 'memory_scopes', 'memory_threads',
                          'memory_facts', 'memory_fact_versions',
                          'memory_source_refs', 'memory_outbox',
                          'memory_fact_operation_receipts'
                      ))
                 WHEN privilege.name = 'INSERT' THEN
                     (pg_catalog.pg_has_role(
                         role.oid, 'infinity_context_canonical_writer', 'MEMBER'
                      ) AND relation.relname = 'memory_idempotency_records')
                     OR (pg_catalog.pg_has_role(
                         role.oid, 'infinity_context_strict_v4_fact_writer', 'MEMBER'
                      ) AND relation.relname IN (
                          'memory_scopes', 'memory_threads', 'memory_facts',
                          'memory_fact_versions', 'memory_source_refs',
                          'memory_outbox', 'memory_fact_operation_receipts'
                      ))
                 WHEN privilege.name = 'DELETE' THEN
                     pg_catalog.pg_has_role(
                         role.oid, 'infinity_context_strict_v4_fact_writer', 'MEMBER'
                     ) AND relation.relname = 'memory_source_refs'
                 ELSE FALSE
             END
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.unnest(
               ARRAY['SELECT', 'USAGE', 'UPDATE']::text[]
           ) AS privilege(name)
           WHERE namespace.nspname = 'public'
             AND relation.relname IN (
                 'memory_source_refs_id_seq',
                 'memory_fact_versions_id_seq',
                 'memory_outbox_id_seq',
                 'memory_idempotency_records_id_seq'
             )
             AND relation.relkind = 'S'
             AND pg_catalog.has_sequence_privilege(
                 role.oid,
                 relation.oid,
                 privilege.name
             ) IS DISTINCT FROM (
                 ((pg_catalog.pg_has_role(
                      role.oid, 'infinity_context_canonical_writer', 'MEMBER'
                   ) AND relation.relname = 'memory_idempotency_records_id_seq')
                  OR (pg_catalog.pg_has_role(
                      role.oid, 'infinity_context_strict_v4_fact_writer', 'MEMBER'
                  ) AND relation.relname IN (
                      'memory_source_refs_id_seq',
                      'memory_fact_versions_id_seq',
                      'memory_outbox_id_seq'
                  )))
                 AND privilege.name = 'USAGE'
             )
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_namespace AS namespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl
           WHERE namespace.nspname = 'public'
             AND acl.grantee = role.oid
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = procedure.pronamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(procedure.proacl) AS acl
           WHERE namespace.nspname = 'public'
             AND procedure.proname = ANY(ARRAY[
                 'memory_comparison_is_strict_v4_canonical_writer',
                 'memory_comparison_enforce_benchmark_writer_fence',
                 'memory_cleanup_enforce_v3_context_authority_immutable',
                 'memory_comparison_lock_strict_v4_registration_targets',
                 'memory_comparison_lock_strict_v4_seal_targets',
                 'memory_comparison_enforce_strict_v4_preparation_immutable',
                 'memory_comparison_close_strict_v4_preparation',
                 'memory_comparison_lock_benchmark_writer_target',
                 'memory_comparison_lock_benchmark_fact_child_target',
                 'memory_comparison_enforce_benchmark_fact_child_fence',
                 'memory_comparison_enforce_benchmark_fact_receipt',
                 'memory_comparison_verify_benchmark_fact_outbox_receipt'
             ]::text[])
             AND acl.grantee = role.oid
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = procedure.pronamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(
               COALESCE(
                   procedure.proacl,
                   pg_catalog.acldefault('f', procedure.proowner)
               )
           ) AS acl
           WHERE namespace.nspname = 'public'
             AND procedure.proname = ANY(ARRAY[
                 'memory_comparison_is_strict_v4_canonical_writer',
                 'memory_comparison_enforce_benchmark_writer_fence',
                 'memory_cleanup_enforce_v3_context_authority_immutable',
                 'memory_comparison_lock_strict_v4_registration_targets',
                 'memory_comparison_lock_strict_v4_seal_targets',
                 'memory_comparison_enforce_strict_v4_preparation_immutable',
                 'memory_comparison_close_strict_v4_preparation',
                 'memory_comparison_lock_benchmark_writer_target',
                 'memory_comparison_lock_benchmark_fact_child_target',
                 'memory_comparison_enforce_benchmark_fact_child_fence',
                 'memory_comparison_enforce_benchmark_fact_receipt',
                 'memory_comparison_verify_benchmark_fact_outbox_receipt'
             ]::text[])
             AND acl.grantee = 0
       )
    FROM pg_catalog.pg_roles AS role
    WHERE role.rolname = current_user
), FALSE)
$$;

REVOKE ALL ON FUNCTION memory_comparison_is_strict_v4_canonical_writer()
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_fact_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;
GRANT EXECUTE ON FUNCTION memory_comparison_is_strict_v4_canonical_writer()
    TO infinity_context_canonical_writer,
       infinity_context_strict_v4_fact_writer;

CREATE OR REPLACE FUNCTION memory_comparison_lock_benchmark_writer_target()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    target_space_id VARCHAR(80);
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF TG_TABLE_NAME = 'memory_spaces' THEN
            target_space_id := OLD.id;
        ELSE
            target_space_id := OLD.space_id;
        END IF;
    ELSE
        IF TG_TABLE_NAME = 'memory_spaces' THEN
            target_space_id := NEW.id;
        ELSE
            target_space_id := NEW.space_id;
        END IF;
    END IF;
    BEGIN
        PERFORM 1
        FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = target_space_id
        FOR SHARE NOWAIT;
    EXCEPTION
        WHEN lock_not_available THEN
            RAISE EXCEPTION 'benchmark canonical writer fence rejected data mutation'
                USING
                    ERRCODE = '23514',
                    CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION memory_comparison_lock_benchmark_writer_target()
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_fact_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;

CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_writer_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    registry_state VARCHAR(40);
    registry_projection_cleanup_state VARCHAR(40);
    registry_cleanup_plan_state VARCHAR(40);
    registry_run_id_sha256 CHAR(64);
    strict_v4_write_authorized BOOLEAN := FALSE;
    legacy_write_authorized BOOLEAN := FALSE;
    old_space_id VARCHAR(80);
    new_space_id VARCHAR(80);
    target_space_id VARCHAR(80);
BEGIN
    IF TG_OP <> 'DELETE' THEN
        IF TG_TABLE_NAME = 'memory_spaces' THEN
            new_space_id := NEW.id;
        ELSE
            new_space_id := NEW.space_id;
        END IF;
    END IF;

    IF TG_OP <> 'INSERT' THEN
        IF TG_TABLE_NAME = 'memory_spaces' THEN
            old_space_id := OLD.id;
        ELSE
            old_space_id := OLD.space_id;
        END IF;
    END IF;

    IF TG_OP = 'UPDATE' AND old_space_id IS DISTINCT FROM new_space_id THEN
        IF EXISTS (
            SELECT 1
            FROM public.memory_comparison_benchmark_runs AS benchmark_run
            WHERE benchmark_run.space_id IN (old_space_id, new_space_id)
        ) THEN
            RAISE EXCEPTION 'benchmark canonical space identity is immutable'
                USING
                    ERRCODE = '23514',
                    CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
        END IF;
    END IF;

    target_space_id := COALESCE(new_space_id, old_space_id);
    SELECT benchmark_run.state, benchmark_run.projection_cleanup_state,
           benchmark_run.cleanup_plan_state, benchmark_run.run_id_sha256
    INTO registry_state, registry_projection_cleanup_state,
         registry_cleanup_plan_state, registry_run_id_sha256
    FROM public.memory_comparison_benchmark_runs AS benchmark_run
    WHERE benchmark_run.space_id = target_space_id;

    IF registry_state IS NOT NULL THEN
        legacy_write_authorized := registry_cleanup_plan_state = 'sealed';
        SELECT EXISTS (
            SELECT 1
            FROM public.memory_comparison_strict_v4_preparations AS preparation
            JOIN public.memory_cleanup_v3_context_authorities AS context_authority
              ON context_authority.run_id_sha256 = preparation.run_id_sha256
             AND context_authority.context_sha256 = preparation.context_sha256
             AND context_authority.authority_terminal_sha256
                 = preparation.authority_terminal_sha256
            WHERE preparation.run_id_sha256 = registry_run_id_sha256
              AND preparation.state = 'sealed'
              AND preparation.provider_calls = 0
              AND preparation.paid_go_ready = FALSE
              AND preparation.registration_sha256
                  = context_authority.registration_sha256
              AND preparation.registration_mac_sha256
                  = context_authority.registration_mac_sha256
              AND public.memory_comparison_is_strict_v4_canonical_writer()
        ) INTO strict_v4_write_authorized;
    END IF;

    IF registry_state IS NULL THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    IF registry_state = 'active'
        AND registry_projection_cleanup_state = 'unsealed'
        AND legacy_write_authorized <> strict_v4_write_authorized
        AND TG_OP = 'INSERT'
        AND TG_TABLE_NAME IN (
            'memory_scopes', 'memory_threads', 'memory_facts', 'memory_documents',
            'memory_chunks', 'memory_fact_operation_receipts',
            'memory_idempotency_records'
        )
    THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE'
        AND TG_TABLE_NAME IN (
            'memory_spaces', 'memory_scopes', 'memory_threads', 'memory_facts',
            'memory_episodes', 'memory_documents', 'memory_chunks'
        )
    THEN
        IF registry_state = 'cleanup_pending'
            AND registry_projection_cleanup_state IN ('pending', 'blocked')
            AND OLD.status = 'active'
            AND NEW.status = 'deleted'
            AND (to_jsonb(OLD) - 'status' - 'updated_at' - 'thread_scope_key')
                = (to_jsonb(NEW) - 'status' - 'updated_at' - 'thread_scope_key')
        THEN
            RETURN NEW;
        END IF;
    END IF;

    RAISE EXCEPTION 'benchmark canonical writer fence rejected data mutation'
        USING
            ERRCODE = '23514',
            CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
END;
$$;

REVOKE ALL ON FUNCTION memory_comparison_enforce_benchmark_writer_fence()
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_fact_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;

CREATE OR REPLACE FUNCTION memory_comparison_lock_benchmark_fact_child_target()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    target_fact_id VARCHAR(80);
    target_space_id VARCHAR(80);
    target_aggregate_type VARCHAR(80);
BEGIN
    IF TG_TABLE_NAME = 'memory_outbox' THEN
        IF TG_OP = 'UPDATE' AND (
            OLD.aggregate_type IS DISTINCT FROM NEW.aggregate_type
            OR OLD.aggregate_id IS DISTINCT FROM NEW.aggregate_id
        ) THEN
            RAISE EXCEPTION 'benchmark fact child identity is immutable'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
        END IF;
        IF TG_OP = 'DELETE' THEN
            target_aggregate_type := OLD.aggregate_type;
            target_fact_id := OLD.aggregate_id;
            target_space_id := OLD.payload_json->>'space_id';
        ELSE
            target_aggregate_type := NEW.aggregate_type;
            target_fact_id := NEW.aggregate_id;
            target_space_id := NEW.payload_json->>'space_id';
        END IF;
        IF target_aggregate_type = 'fact' THEN
            SELECT fact.space_id INTO target_space_id
            FROM public.memory_facts AS fact
            WHERE fact.id = target_fact_id;
        END IF;
    ELSE
        IF TG_OP = 'UPDATE' AND OLD.fact_id IS DISTINCT FROM NEW.fact_id THEN
            RAISE EXCEPTION 'benchmark fact child identity is immutable'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
        END IF;
        IF TG_OP = 'DELETE' THEN
            target_fact_id := OLD.fact_id;
        ELSE
            target_fact_id := NEW.fact_id;
        END IF;
        SELECT fact.space_id INTO target_space_id
        FROM public.memory_facts AS fact
        WHERE fact.id = target_fact_id;
    END IF;

    IF target_space_id IS NULL THEN
        RAISE EXCEPTION 'benchmark fact child parent is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    BEGIN
        PERFORM 1
        FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = target_space_id
        FOR SHARE NOWAIT;
    EXCEPTION WHEN lock_not_available THEN
        RAISE EXCEPTION 'benchmark fact child writer fence rejected data mutation'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_fact_child_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    target_fact_id VARCHAR(80);
    target_space_id VARCHAR(80);
    parent_scope_id VARCHAR(80);
    parent_thread_id VARCHAR(80);
    parent_version INTEGER;
    parent_status VARCHAR(40);
    parent_text TEXT;
    target_aggregate_type VARCHAR(80);
    registry_state VARCHAR(40);
    registry_projection_state VARCHAR(40);
    registry_cleanup_plan_state VARCHAR(40);
    registry_run_id CHAR(64);
    strict_authorized BOOLEAN := FALSE;
    fact_writer BOOLEAN := public.memory_comparison_is_strict_v4_canonical_writer()
        AND pg_catalog.pg_has_role(
            current_user, 'infinity_context_strict_v4_fact_writer', 'MEMBER'
        );
BEGIN
    IF TG_TABLE_NAME = 'memory_outbox' THEN
        IF TG_OP = 'DELETE' THEN
            target_aggregate_type := OLD.aggregate_type;
            target_fact_id := OLD.aggregate_id;
            target_space_id := OLD.payload_json->>'space_id';
        ELSE
            target_aggregate_type := NEW.aggregate_type;
            target_fact_id := NEW.aggregate_id;
            target_space_id := NEW.payload_json->>'space_id';
        END IF;
        IF target_aggregate_type <> 'fact' THEN
            target_fact_id := NULL;
        END IF;
    ELSE
        IF TG_OP = 'DELETE' THEN
            target_fact_id := OLD.fact_id;
        ELSE
            target_fact_id := NEW.fact_id;
        END IF;
    END IF;
    IF target_fact_id IS NOT NULL THEN
        SELECT fact.space_id, fact.memory_scope_id, fact.thread_id,
               fact.version, fact.status, fact.text
        INTO target_space_id, parent_scope_id, parent_thread_id,
             parent_version, parent_status, parent_text
        FROM public.memory_facts AS fact
        WHERE fact.id = target_fact_id;
    END IF;
    SELECT benchmark_run.state, benchmark_run.projection_cleanup_state,
           benchmark_run.cleanup_plan_state, benchmark_run.run_id_sha256
    INTO registry_state, registry_projection_state,
         registry_cleanup_plan_state, registry_run_id
    FROM public.memory_comparison_benchmark_runs AS benchmark_run
    WHERE benchmark_run.space_id = target_space_id;

    IF registry_state IS NULL THEN
        IF fact_writer THEN
            RAISE EXCEPTION 'strict-v4 fact writer cannot mutate an unmanaged child'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    SELECT EXISTS (
        SELECT 1
        FROM public.memory_comparison_strict_v4_preparations AS preparation
        JOIN public.memory_cleanup_v3_context_authorities AS context_authority
          ON context_authority.run_id_sha256 = preparation.run_id_sha256
         AND context_authority.context_sha256 = preparation.context_sha256
         AND context_authority.authority_terminal_sha256
             = preparation.authority_terminal_sha256
        WHERE preparation.run_id_sha256 = registry_run_id
          AND preparation.state = 'sealed'
          AND preparation.provider_calls = 0
          AND preparation.paid_go_ready = FALSE
          AND preparation.registration_sha256 = context_authority.registration_sha256
          AND preparation.registration_mac_sha256 = context_authority.registration_mac_sha256
    ) INTO strict_authorized;

    IF TG_OP = 'INSERT' AND NOT fact_writer AND NOT strict_authorized
        AND registry_state = 'active' AND registry_projection_state = 'unsealed'
        AND registry_cleanup_plan_state = 'sealed'
    THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'INSERT' AND fact_writer AND strict_authorized
        AND registry_state = 'active' AND registry_projection_state = 'unsealed'
    THEN
        IF TG_TABLE_NAME = 'memory_fact_versions' THEN
            IF NEW.version = 1 AND parent_version = 1
                AND NEW.status = 'active' AND parent_status = 'active'
                AND NEW.text = parent_text
            THEN
                RETURN NEW;
            END IF;
        ELSIF TG_TABLE_NAME = 'memory_source_refs' THEN
            IF NEW.fact_version = 1 AND parent_version = 1
                AND parent_status = 'active'
            THEN
                RETURN NEW;
            END IF;
        ELSIF TG_TABLE_NAME = 'memory_outbox' THEN
            IF NEW.aggregate_type = 'fact'
                AND NEW.aggregate_version = 1
                AND NEW.event_type = 'fact.created'
                AND NEW.status = 'pending' AND NEW.attempt_count = 0
                AND NEW.message_key IS NOT NULL
                AND NEW.payload_json->>'fact_id' = target_fact_id
                AND NEW.payload_json->>'space_id' = target_space_id
                AND NEW.payload_json->>'memory_scope_id' = parent_scope_id
                AND COALESCE(NEW.payload_json->>'thread_id', '')
                    = COALESCE(parent_thread_id, '')
                AND (NEW.payload_json->>'version')::integer = 1
            THEN
                RETURN NEW;
            END IF;
        END IF;
    END IF;
    RAISE EXCEPTION 'benchmark fact child writer fence rejected data mutation'
        USING ERRCODE = '23514',
              CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
END;
$$;

CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_fact_receipt()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT (
        public.memory_comparison_is_strict_v4_canonical_writer()
        AND pg_catalog.pg_has_role(
            current_user, 'infinity_context_strict_v4_fact_writer', 'MEMBER'
        )
    ) THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = NEW.space_id
    ) AND (
        NEW.operation <> 'remember'
        OR NEW.result_fact_version <> 1
        OR NEW.idempotency_key NOT LIKE 'managed-benchmark-fact-v4-%'
        OR pg_catalog.length(NEW.idempotency_key) <> 90
        OR NEW.tombstone_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'benchmark fact receipt is invalid'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_comparison_verify_benchmark_fact_outbox_receipt()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT (
        public.memory_comparison_is_strict_v4_canonical_writer()
        AND pg_catalog.pg_has_role(
            current_user, 'infinity_context_strict_v4_fact_writer', 'MEMBER'
        )
    ) THEN
        RETURN NEW;
    END IF;
    IF NEW.aggregate_type <> 'fact' OR NOT EXISTS (
        SELECT 1 FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = NEW.payload_json->>'space_id'
    ) THEN
        RETURN NEW;
    END IF;
    IF NEW.message_key IS NULL THEN
        RAISE EXCEPTION 'benchmark fact outbox message key is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_fact_operation_receipts AS receipt
        WHERE receipt.result_fact_id = NEW.aggregate_id
    ) THEN
        RAISE EXCEPTION 'benchmark fact outbox result receipt is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_fact_operation_receipts AS receipt
        WHERE receipt.result_fact_id = NEW.aggregate_id
          AND receipt.space_id = NEW.payload_json->>'space_id'
    ) THEN
        RAISE EXCEPTION 'benchmark fact outbox receipt space is invalid'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_fact_operation_receipts AS receipt
        WHERE receipt.result_fact_id = NEW.aggregate_id
          AND receipt.space_id = NEW.payload_json->>'space_id'
          AND receipt.result_fact_version = NEW.aggregate_version
    ) THEN
        RAISE EXCEPTION 'benchmark fact outbox receipt version is invalid'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.memory_fact_operation_receipts AS receipt
        WHERE receipt.space_id = NEW.payload_json->>'space_id'
          AND receipt.result_fact_id = NEW.aggregate_id
          AND receipt.result_fact_version = NEW.aggregate_version
          AND receipt.operation = 'remember'
          AND receipt.idempotency_key LIKE 'managed-benchmark-fact-v4-%'
          AND pg_catalog.length(receipt.idempotency_key) = 90
    ) THEN
        RAISE EXCEPTION 'benchmark fact outbox receipt identity is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.memory_fact_operation_receipts AS receipt
        WHERE receipt.space_id = NEW.payload_json->>'space_id'
          AND receipt.result_fact_id = NEW.aggregate_id
          AND receipt.result_fact_version = NEW.aggregate_version
          AND receipt.operation = 'remember'
          AND receipt.outbox_message_ids_json
              @> pg_catalog.jsonb_build_array(NEW.message_key)
    ) THEN
        RAISE EXCEPTION 'benchmark fact outbox receipt link is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_00_memory_fact_versions_benchmark_fact_child_lock ON memory_fact_versions;

CREATE TRIGGER trg_00_memory_fact_versions_benchmark_fact_child_lock BEFORE INSERT OR UPDATE OR DELETE ON memory_fact_versions FOR EACH ROW EXECUTE FUNCTION memory_comparison_lock_benchmark_fact_child_target();

DROP TRIGGER IF EXISTS trg_memory_fact_versions_benchmark_fact_child_fence ON memory_fact_versions;

CREATE TRIGGER trg_memory_fact_versions_benchmark_fact_child_fence BEFORE INSERT OR UPDATE OR DELETE ON memory_fact_versions FOR EACH ROW EXECUTE FUNCTION memory_comparison_enforce_benchmark_fact_child_fence();

DROP TRIGGER IF EXISTS trg_00_memory_source_refs_benchmark_fact_child_lock ON memory_source_refs;

CREATE TRIGGER trg_00_memory_source_refs_benchmark_fact_child_lock BEFORE INSERT OR UPDATE OR DELETE ON memory_source_refs FOR EACH ROW EXECUTE FUNCTION memory_comparison_lock_benchmark_fact_child_target();

DROP TRIGGER IF EXISTS trg_memory_source_refs_benchmark_fact_child_fence ON memory_source_refs;

CREATE TRIGGER trg_memory_source_refs_benchmark_fact_child_fence BEFORE INSERT OR UPDATE OR DELETE ON memory_source_refs FOR EACH ROW EXECUTE FUNCTION memory_comparison_enforce_benchmark_fact_child_fence();

DROP TRIGGER IF EXISTS trg_00_memory_outbox_benchmark_fact_child_lock ON memory_outbox;

CREATE TRIGGER trg_00_memory_outbox_benchmark_fact_child_lock BEFORE INSERT OR UPDATE OR DELETE ON memory_outbox FOR EACH ROW EXECUTE FUNCTION memory_comparison_lock_benchmark_fact_child_target();

DROP TRIGGER IF EXISTS trg_memory_outbox_benchmark_fact_child_fence ON memory_outbox;

CREATE TRIGGER trg_memory_outbox_benchmark_fact_child_fence BEFORE INSERT OR UPDATE OR DELETE ON memory_outbox FOR EACH ROW EXECUTE FUNCTION memory_comparison_enforce_benchmark_fact_child_fence();

DROP TRIGGER IF EXISTS trg_memory_outbox_benchmark_fact_receipt ON memory_outbox;

CREATE CONSTRAINT TRIGGER trg_memory_outbox_benchmark_fact_receipt AFTER INSERT ON memory_outbox DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION memory_comparison_verify_benchmark_fact_outbox_receipt();

DROP TRIGGER IF EXISTS trg_memory_fact_operation_receipt_benchmark_fact_policy ON memory_fact_operation_receipts;

CREATE TRIGGER trg_memory_fact_operation_receipt_benchmark_fact_policy BEFORE INSERT ON memory_fact_operation_receipts FOR EACH ROW EXECUTE FUNCTION memory_comparison_enforce_benchmark_fact_receipt();

REVOKE ALL ON FUNCTION
    public.memory_cleanup_enforce_v3_context_authority_immutable(),
    public.memory_comparison_lock_strict_v4_registration_targets(CHAR, CHAR),
    public.memory_comparison_lock_strict_v4_seal_targets(CHAR, CHAR),
    public.memory_comparison_enforce_strict_v4_preparation_immutable(),
    public.memory_comparison_close_strict_v4_preparation(),
    public.memory_comparison_is_strict_v4_canonical_writer(),
    public.memory_comparison_lock_benchmark_writer_target(),
    public.memory_comparison_enforce_benchmark_writer_fence(),
    public.memory_comparison_lock_benchmark_fact_child_target(),
    public.memory_comparison_enforce_benchmark_fact_child_fence(),
    public.memory_comparison_enforce_benchmark_fact_receipt(),
    public.memory_comparison_verify_benchmark_fact_outbox_receipt()
FROM PUBLIC,
     infinity_context_canonical_writer,
     infinity_context_strict_v4_fact_writer,
     infinity_context_strict_v4_registrar,
     infinity_context_strict_v4_sealer;

GRANT EXECUTE ON FUNCTION
    public.memory_comparison_lock_strict_v4_registration_targets(CHAR, CHAR)
TO infinity_context_strict_v4_registrar;

GRANT EXECUTE ON FUNCTION
    public.memory_comparison_lock_strict_v4_seal_targets(CHAR, CHAR)
TO infinity_context_strict_v4_sealer;

GRANT EXECUTE ON FUNCTION
    public.memory_comparison_is_strict_v4_canonical_writer()
TO infinity_context_canonical_writer,
   infinity_context_strict_v4_fact_writer;
