-- Enable the least-privilege strict-v4 canonical document writer.
DO $document_writer_precondition$
DECLARE
    role_row RECORD;
BEGIN
    SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
           rolreplication, rolbypassrls
    INTO role_row
    FROM pg_catalog.pg_roles
    WHERE rolname = 'infinity_context_strict_v4_document_writer';
    IF role_row IS NULL
       OR role_row.rolcanlogin OR role_row.rolsuper OR role_row.rolcreatedb
       OR role_row.rolcreaterole OR role_row.rolreplication
       OR role_row.rolbypassrls
       OR pg_catalog.has_schema_privilege(
           'infinity_context_strict_v4_document_writer', 'public', 'CREATE'
       )
       OR NOT pg_catalog.has_schema_privilege(
           'infinity_context_strict_v4_document_writer', 'public', 'USAGE'
       )
       OR EXISTS (
           SELECT 1 FROM pg_catalog.pg_roles AS inherited
           WHERE inherited.rolname <> 'infinity_context_strict_v4_document_writer'
             AND pg_catalog.pg_has_role(
                 'infinity_context_strict_v4_document_writer', inherited.oid, 'MEMBER'
             )
       )
    THEN
        RAISE EXCEPTION 'unsafe strict-v4 document-writer capability role'
            USING ERRCODE = '42501';
    END IF;
END
$document_writer_precondition$;

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
FROM infinity_context_strict_v4_document_writer;

REVOKE ALL ON SEQUENCE
    public.memory_source_refs_id_seq,
    public.memory_fact_versions_id_seq,
    public.memory_outbox_id_seq,
    public.memory_idempotency_records_id_seq
FROM infinity_context_strict_v4_document_writer;

GRANT SELECT ON
    public.memory_comparison_benchmark_runs,
    public.memory_cleanup_v3_context_authorities,
    public.memory_comparison_strict_v4_preparations,
    public.memory_spaces,
    public.memory_scopes,
    public.memory_threads,
    public.memory_documents,
    public.memory_chunks,
    public.memory_outbox,
    public.memory_idempotency_records
TO infinity_context_strict_v4_document_writer;

GRANT INSERT ON
    public.memory_scopes,
    public.memory_threads,
    public.memory_documents,
    public.memory_chunks,
    public.memory_outbox,
    public.memory_idempotency_records
TO infinity_context_strict_v4_document_writer;

GRANT USAGE ON SEQUENCE
    public.memory_outbox_id_seq,
    public.memory_idempotency_records_id_seq
TO infinity_context_strict_v4_document_writer;

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
FROM infinity_context_strict_v4_document_writer;

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
           )::integer
           + pg_catalog.pg_has_role(
               role.oid, 'infinity_context_strict_v4_fact_writer', 'MEMBER'
           )::integer
           + pg_catalog.pg_has_role(
               role.oid, 'infinity_context_strict_v4_document_writer', 'MEMBER'
           )::integer
       ) = 1
       AND NOT EXISTS (
           SELECT 1 FROM pg_catalog.pg_roles AS granted_role
           WHERE granted_role.oid <> role.oid
             AND granted_role.rolname NOT IN (
                 'infinity_context_canonical_writer',
                 'infinity_context_strict_v4_fact_writer',
                 'infinity_context_strict_v4_document_writer'
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
                 'memory_outbox_id_seq', 'memory_idempotency_records_id_seq'
             ]::text[])
             AND pg_catalog.pg_has_role(role.oid, relation.relowner, 'MEMBER')
       )
       AND NOT EXISTS (
           SELECT 1 FROM pg_catalog.pg_namespace AS namespace
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
                 'memory_comparison_lock_strict_v4_registration_targets',
                 'memory_comparison_lock_strict_v4_seal_targets',
                 'memory_comparison_is_strict_v4_canonical_writer',
                 'memory_comparison_is_strict_v4_document_writer',
                 'memory_comparison_enforce_benchmark_writer_fence',
                 'memory_comparison_close_strict_v4_preparation',
                 'memory_cleanup_enforce_v3_context_authority_immutable',
                 'memory_comparison_enforce_strict_v4_preparation_immutable',
                 'memory_comparison_lock_benchmark_writer_target',
                 'memory_comparison_lock_benchmark_fact_child_target',
                 'memory_comparison_enforce_benchmark_fact_child_fence',
                 'memory_comparison_enforce_benchmark_fact_receipt',
                 'memory_comparison_verify_benchmark_fact_outbox_receipt',
                 'memory_comparison_lock_benchmark_document_child_target',
                 'memory_comparison_enforce_benchmark_document_child_fence',
                 'memory_comparison_enforce_benchmark_document_idempotency',
                 'memory_comparison_verify_benchmark_document_receipt'
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
                 'memory_outbox_id_seq', 'memory_idempotency_records_id_seq'
             ]::text[])
             AND acl.grantee IN (0, role.oid)
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
                 'memory_comparison_lock_strict_v4_registration_targets',
                 'memory_comparison_lock_strict_v4_seal_targets',
                 'memory_comparison_is_strict_v4_canonical_writer',
                 'memory_comparison_is_strict_v4_document_writer',
                 'memory_comparison_enforce_benchmark_writer_fence',
                 'memory_comparison_close_strict_v4_preparation',
                 'memory_cleanup_enforce_v3_context_authority_immutable',
                 'memory_comparison_enforce_strict_v4_preparation_immutable',
                 'memory_comparison_lock_benchmark_writer_target',
                 'memory_comparison_lock_benchmark_fact_child_target',
                 'memory_comparison_enforce_benchmark_fact_child_fence',
                 'memory_comparison_enforce_benchmark_fact_receipt',
                 'memory_comparison_verify_benchmark_fact_outbox_receipt',
                 'memory_comparison_lock_benchmark_document_child_target',
                 'memory_comparison_enforce_benchmark_document_child_fence',
                 'memory_comparison_enforce_benchmark_document_idempotency',
                 'memory_comparison_verify_benchmark_document_receipt'
             ]::text[])
             AND acl.grantee IN (0, role.oid)
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
                 role.oid, relation.oid, privilege.name
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
                      )) OR (pg_catalog.pg_has_role(
                         role.oid, 'infinity_context_strict_v4_document_writer', 'MEMBER'
                      ) AND relation.relname IN (
                          'memory_comparison_benchmark_runs',
                          'memory_cleanup_v3_context_authorities',
                          'memory_comparison_strict_v4_preparations',
                          'memory_spaces', 'memory_scopes', 'memory_threads',
                          'memory_documents', 'memory_chunks', 'memory_outbox',
                          'memory_idempotency_records'
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
                     OR (pg_catalog.pg_has_role(
                         role.oid, 'infinity_context_strict_v4_document_writer', 'MEMBER'
                      ) AND relation.relname IN (
                          'memory_scopes', 'memory_threads', 'memory_documents',
                          'memory_chunks', 'memory_outbox',
                          'memory_idempotency_records'
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
                 'memory_source_refs_id_seq', 'memory_fact_versions_id_seq',
                 'memory_outbox_id_seq', 'memory_idempotency_records_id_seq'
             )
             AND relation.relkind = 'S'
             AND pg_catalog.has_sequence_privilege(
                 role.oid, relation.oid, privilege.name
             ) IS DISTINCT FROM (
                 privilege.name = 'USAGE' AND (
                     (pg_catalog.pg_has_role(
                         role.oid, 'infinity_context_canonical_writer', 'MEMBER'
                      ) AND relation.relname = 'memory_idempotency_records_id_seq')
                     OR (pg_catalog.pg_has_role(
                         role.oid, 'infinity_context_strict_v4_fact_writer', 'MEMBER'
                      ) AND relation.relname IN (
                          'memory_source_refs_id_seq',
                          'memory_fact_versions_id_seq', 'memory_outbox_id_seq'
                      ))
                     OR (pg_catalog.pg_has_role(
                         role.oid, 'infinity_context_strict_v4_document_writer', 'MEMBER'
                      ) AND relation.relname IN (
                          'memory_outbox_id_seq', 'memory_idempotency_records_id_seq'
                      ))
                 )
             )
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = procedure.pronamespace
           WHERE namespace.nspname = 'public'
             AND procedure.proname = ANY(ARRAY[
                 'memory_comparison_lock_strict_v4_registration_targets',
                 'memory_comparison_lock_strict_v4_seal_targets',
                 'memory_comparison_is_strict_v4_canonical_writer',
                 'memory_comparison_is_strict_v4_document_writer',
                 'memory_comparison_enforce_benchmark_writer_fence',
                 'memory_comparison_close_strict_v4_preparation',
                 'memory_cleanup_enforce_v3_context_authority_immutable',
                 'memory_comparison_enforce_strict_v4_preparation_immutable',
                 'memory_comparison_lock_benchmark_writer_target',
                 'memory_comparison_lock_benchmark_fact_child_target',
                 'memory_comparison_enforce_benchmark_fact_child_fence',
                 'memory_comparison_enforce_benchmark_fact_receipt',
                 'memory_comparison_verify_benchmark_fact_outbox_receipt',
                 'memory_comparison_lock_benchmark_document_child_target',
                 'memory_comparison_enforce_benchmark_document_child_fence',
                 'memory_comparison_enforce_benchmark_document_idempotency',
                 'memory_comparison_verify_benchmark_document_receipt'
             ]::text[])
             AND pg_catalog.has_function_privilege(
                 role.oid, procedure.oid, 'EXECUTE'
             ) IS DISTINCT FROM (
                 procedure.proname = 'memory_comparison_is_strict_v4_canonical_writer'
                 OR procedure.proname = 'memory_comparison_is_strict_v4_document_writer'
             )
       )
    FROM pg_catalog.pg_roles AS role
    WHERE role.rolname = current_user
), FALSE)
$$;

CREATE OR REPLACE FUNCTION memory_comparison_is_strict_v4_document_writer()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
SELECT public.memory_comparison_is_strict_v4_canonical_writer()
   AND pg_catalog.pg_has_role(
       current_user, 'infinity_context_strict_v4_document_writer', 'MEMBER'
   )
$$;

REVOKE ALL ON FUNCTION
    public.memory_comparison_is_strict_v4_canonical_writer(),
    public.memory_comparison_is_strict_v4_document_writer()
FROM PUBLIC,
     infinity_context_canonical_writer,
     infinity_context_strict_v4_fact_writer,
     infinity_context_strict_v4_document_writer,
     infinity_context_strict_v4_registrar,
     infinity_context_strict_v4_sealer;

GRANT EXECUTE ON FUNCTION public.memory_comparison_is_strict_v4_canonical_writer()
TO infinity_context_canonical_writer,
   infinity_context_strict_v4_fact_writer,
   infinity_context_strict_v4_document_writer;

GRANT EXECUTE ON FUNCTION public.memory_comparison_is_strict_v4_document_writer()
TO infinity_context_canonical_writer,
   infinity_context_strict_v4_fact_writer,
   infinity_context_strict_v4_document_writer;

CREATE OR REPLACE FUNCTION memory_comparison_lock_benchmark_document_child_target()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    target_document_id VARCHAR(80);
    target_space_id VARCHAR(80);
BEGIN
    IF TG_TABLE_NAME = 'memory_outbox' THEN
        IF TG_OP = 'DELETE' THEN
            IF OLD.aggregate_type <> 'chunk' THEN RETURN OLD; END IF;
            target_document_id := NULL;
            SELECT chunk.document_id, document.space_id
            INTO target_document_id, target_space_id
            FROM public.memory_chunks AS chunk
            JOIN public.memory_documents AS document ON document.id = chunk.document_id
            WHERE chunk.id = OLD.aggregate_id;
        ELSE
            IF NEW.aggregate_type <> 'chunk' THEN RETURN NEW; END IF;
            SELECT chunk.document_id, document.space_id
            INTO target_document_id, target_space_id
            FROM public.memory_chunks AS chunk
            JOIN public.memory_documents AS document ON document.id = chunk.document_id
            WHERE chunk.id = NEW.aggregate_id;
        END IF;
    ELSE
        IF TG_OP = 'DELETE' THEN target_document_id := OLD.document_id;
        ELSE target_document_id := NEW.document_id;
        END IF;
        SELECT document.space_id INTO target_space_id
        FROM public.memory_documents AS document
        WHERE document.id = target_document_id;
    END IF;
    IF target_document_id IS NULL OR target_space_id IS NULL THEN
        RAISE EXCEPTION 'benchmark document child parent is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    BEGIN
        PERFORM 1
        FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = target_space_id
        FOR SHARE NOWAIT;
    EXCEPTION WHEN lock_not_available THEN
        RAISE EXCEPTION 'benchmark document child writer fence rejected data mutation'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_document_child_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    target_document_id VARCHAR(80);
    target_space_id VARCHAR(80);
    parent_scope_id VARCHAR(80);
    parent_thread_id VARCHAR(80);
    parent_source_type VARCHAR(80);
    parent_source_external_id VARCHAR(240);
    parent_classification VARCHAR(40);
    parent_status VARCHAR(40);
    registry_state VARCHAR(40);
    registry_projection_state VARCHAR(40);
    registry_cleanup_plan_state VARCHAR(40);
    registry_run_id CHAR(64);
    strict_authorized BOOLEAN := FALSE;
    document_writer BOOLEAN := public.memory_comparison_is_strict_v4_document_writer();
BEGIN
    IF TG_TABLE_NAME = 'memory_outbox' THEN
        IF TG_OP = 'DELETE' THEN
            IF OLD.aggregate_type <> 'chunk' THEN RETURN OLD; END IF;
            SELECT chunk.document_id INTO target_document_id
            FROM public.memory_chunks AS chunk WHERE chunk.id = OLD.aggregate_id;
        ELSE
            IF NEW.aggregate_type <> 'chunk' THEN RETURN NEW; END IF;
            SELECT chunk.document_id INTO target_document_id
            FROM public.memory_chunks AS chunk WHERE chunk.id = NEW.aggregate_id;
        END IF;
    ELSE
        IF TG_OP = 'DELETE' THEN target_document_id := OLD.document_id;
        ELSE target_document_id := NEW.document_id;
        END IF;
    END IF;
    SELECT document.space_id, document.memory_scope_id, document.thread_id,
           document.source_type, document.source_external_id,
           document.classification, document.status
    INTO target_space_id, parent_scope_id, parent_thread_id,
         parent_source_type, parent_source_external_id,
         parent_classification, parent_status
    FROM public.memory_documents AS document
    WHERE document.id = target_document_id;
    SELECT benchmark_run.state, benchmark_run.projection_cleanup_state,
           benchmark_run.cleanup_plan_state, benchmark_run.run_id_sha256
    INTO registry_state, registry_projection_state,
         registry_cleanup_plan_state, registry_run_id
    FROM public.memory_comparison_benchmark_runs AS benchmark_run
    WHERE benchmark_run.space_id = target_space_id;
    IF registry_state IS NULL THEN
        IF document_writer THEN
            RAISE EXCEPTION 'strict-v4 document writer cannot mutate an unmanaged child'
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
    IF TG_OP = 'INSERT' AND NOT document_writer AND NOT strict_authorized
        AND registry_state = 'active' AND registry_projection_state = 'unsealed'
        AND registry_cleanup_plan_state = 'sealed'
    THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'INSERT' AND document_writer AND strict_authorized
        AND registry_state = 'active' AND registry_projection_state = 'unsealed'
    THEN
        IF TG_TABLE_NAME = 'memory_chunks' THEN
            IF NEW.space_id = target_space_id
                AND NEW.memory_scope_id = parent_scope_id
                AND COALESCE(NEW.thread_id, '') = COALESCE(parent_thread_id, '')
                AND NEW.episode_id IS NULL
                AND NEW.source_type = parent_source_type
                AND NEW.source_external_id = parent_source_external_id
                AND NEW.classification = parent_classification
                AND NEW.status = 'active'
                AND parent_status = 'active'
                AND NEW.sequence >= 0
                AND NEW.char_start >= 0
                AND NEW.char_end >= NEW.char_start
            THEN RETURN NEW; END IF;
        ELSIF TG_TABLE_NAME = 'memory_outbox' THEN
            IF NEW.aggregate_type = 'chunk'
                AND NEW.event_type = 'vector.upsert_chunk'
                AND NEW.aggregate_version IS NULL
                AND NEW.status = 'pending'
                AND NEW.attempt_count = 0
                AND NEW.workload_class = 'projection'
                AND NEW.payload_json = pg_catalog.jsonb_build_object(
                    'chunk_id', NEW.aggregate_id
                )
            THEN RETURN NEW; END IF;
        END IF;
    END IF;
    RAISE EXCEPTION 'benchmark document child writer fence rejected data mutation'
        USING ERRCODE = '23514',
              CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
END;
$$;

CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_document_idempotency()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.memory_comparison_is_strict_v4_document_writer() THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = NEW.space_id
    ) OR NEW.result_type <> 'document'
       OR NEW.key NOT LIKE 'managed-benchmark-document-v4-%'
       OR pg_catalog.length(NEW.key) <> 94
       OR NOT EXISTS (
           SELECT 1 FROM public.memory_documents AS document
           WHERE document.id = NEW.result_id
             AND document.space_id = NEW.space_id
             AND document.content_hash = NEW.fingerprint
             AND document.status = 'active'
       )
    THEN
        RAISE EXCEPTION 'benchmark document idempotency receipt is invalid'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_comparison_verify_benchmark_document_receipt()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.memory_comparison_is_strict_v4_document_writer() THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = NEW.space_id
    ) THEN RETURN NEW; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_idempotency_records AS receipt
        WHERE receipt.space_id = NEW.space_id
          AND receipt.result_type = 'document'
          AND receipt.result_id = NEW.id
          AND receipt.fingerprint = NEW.content_hash
          AND receipt.key LIKE 'managed-benchmark-document-v4-%'
          AND pg_catalog.length(receipt.key) = 94
    ) OR NOT EXISTS (
        SELECT 1 FROM public.memory_chunks AS chunk
        WHERE chunk.document_id = NEW.id
    ) OR EXISTS (
        SELECT 1 FROM public.memory_chunks AS chunk
        WHERE chunk.document_id = NEW.id
          AND NOT EXISTS (
              SELECT 1 FROM public.memory_outbox AS outbox
              WHERE outbox.aggregate_type = 'chunk'
                AND outbox.aggregate_id = chunk.id
                AND outbox.event_type = 'vector.upsert_chunk'
                AND outbox.payload_json = pg_catalog.jsonb_build_object(
                    'chunk_id', chunk.id
                )
          )
    ) THEN
        RAISE EXCEPTION 'benchmark document receipt is missing or incomplete'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_00_memory_outbox_benchmark_fact_child_lock
ON memory_outbox;
DROP TRIGGER IF EXISTS trg_memory_outbox_benchmark_fact_child_fence
ON memory_outbox;
CREATE TRIGGER trg_00_memory_outbox_benchmark_fact_child_lock
BEFORE INSERT OR UPDATE ON memory_outbox
FOR EACH ROW WHEN (NEW.aggregate_type = 'fact')
EXECUTE FUNCTION memory_comparison_lock_benchmark_fact_child_target();
CREATE TRIGGER trg_00_memory_outbox_benchmark_fact_child_delete_lock
BEFORE DELETE ON memory_outbox
FOR EACH ROW WHEN (OLD.aggregate_type = 'fact')
EXECUTE FUNCTION memory_comparison_lock_benchmark_fact_child_target();
CREATE TRIGGER trg_memory_outbox_benchmark_fact_child_fence
BEFORE INSERT OR UPDATE ON memory_outbox
FOR EACH ROW WHEN (NEW.aggregate_type = 'fact')
EXECUTE FUNCTION memory_comparison_enforce_benchmark_fact_child_fence();
CREATE TRIGGER trg_memory_outbox_benchmark_fact_child_delete_fence
BEFORE DELETE ON memory_outbox
FOR EACH ROW WHEN (OLD.aggregate_type = 'fact')
EXECUTE FUNCTION memory_comparison_enforce_benchmark_fact_child_fence();

DROP TRIGGER IF EXISTS trg_00_memory_chunks_benchmark_document_child_lock
ON memory_chunks;
CREATE TRIGGER trg_00_memory_chunks_benchmark_document_child_lock
BEFORE INSERT OR UPDATE OR DELETE ON memory_chunks
FOR EACH ROW EXECUTE FUNCTION memory_comparison_lock_benchmark_document_child_target();
DROP TRIGGER IF EXISTS trg_memory_chunks_benchmark_document_child_fence
ON memory_chunks;
CREATE TRIGGER trg_memory_chunks_benchmark_document_child_fence
BEFORE INSERT OR UPDATE OR DELETE ON memory_chunks
FOR EACH ROW EXECUTE FUNCTION memory_comparison_enforce_benchmark_document_child_fence();

DROP TRIGGER IF EXISTS trg_00_memory_outbox_benchmark_document_child_lock
ON memory_outbox;
CREATE TRIGGER trg_00_memory_outbox_benchmark_document_child_lock
BEFORE INSERT OR UPDATE ON memory_outbox
FOR EACH ROW WHEN (NEW.aggregate_type = 'chunk')
EXECUTE FUNCTION memory_comparison_lock_benchmark_document_child_target();
CREATE TRIGGER trg_00_memory_outbox_benchmark_document_child_delete_lock
BEFORE DELETE ON memory_outbox
FOR EACH ROW WHEN (OLD.aggregate_type = 'chunk')
EXECUTE FUNCTION memory_comparison_lock_benchmark_document_child_target();
DROP TRIGGER IF EXISTS trg_memory_outbox_benchmark_document_child_fence
ON memory_outbox;
CREATE TRIGGER trg_memory_outbox_benchmark_document_child_fence
BEFORE INSERT OR UPDATE ON memory_outbox
FOR EACH ROW WHEN (NEW.aggregate_type = 'chunk')
EXECUTE FUNCTION memory_comparison_enforce_benchmark_document_child_fence();
CREATE TRIGGER trg_memory_outbox_benchmark_document_child_delete_fence
BEFORE DELETE ON memory_outbox
FOR EACH ROW WHEN (OLD.aggregate_type = 'chunk')
EXECUTE FUNCTION memory_comparison_enforce_benchmark_document_child_fence();

DROP TRIGGER IF EXISTS trg_memory_idempotency_benchmark_document_policy
ON memory_idempotency_records;
CREATE TRIGGER trg_memory_idempotency_benchmark_document_policy
BEFORE INSERT ON memory_idempotency_records
FOR EACH ROW EXECUTE FUNCTION memory_comparison_enforce_benchmark_document_idempotency();

DROP TRIGGER IF EXISTS trg_memory_document_benchmark_document_receipt
ON memory_documents;
CREATE CONSTRAINT TRIGGER trg_memory_document_benchmark_document_receipt
AFTER INSERT ON memory_documents DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION memory_comparison_verify_benchmark_document_receipt();

REVOKE ALL ON FUNCTION
    public.memory_comparison_lock_benchmark_document_child_target(),
    public.memory_comparison_enforce_benchmark_document_child_fence(),
    public.memory_comparison_enforce_benchmark_document_idempotency(),
    public.memory_comparison_verify_benchmark_document_receipt()
FROM PUBLIC,
     infinity_context_canonical_writer,
     infinity_context_strict_v4_fact_writer,
     infinity_context_strict_v4_document_writer,
     infinity_context_strict_v4_registrar,
     infinity_context_strict_v4_sealer;
