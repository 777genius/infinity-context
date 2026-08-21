-- An administrator must apply postgres/provisioning/strict_v4_roles.sql before
-- the ordinary application-owned migration. Runtime logins are members of
-- exactly one capability role and never own these tables.
SET LOCAL search_path = pg_catalog, public, pg_temp;
DO $role_precondition$
BEGIN
    IF (
        SELECT count(*) = 3
        FROM pg_catalog.pg_roles
        WHERE rolname IN (
            'infinity_context_canonical_writer',
            'infinity_context_strict_v4_registrar',
            'infinity_context_strict_v4_sealer'
        )
          AND NOT rolcanlogin
          AND NOT rolsuper
          AND NOT rolcreatedb
          AND NOT rolcreaterole
          AND NOT rolreplication
          AND NOT rolbypassrls
    ) IS NOT TRUE THEN
        RAISE EXCEPTION
            'strict-v4 NOLOGIN capability roles must be provisioned by an administrator'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS capability
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid <> capability.oid
        WHERE capability.rolname IN (
            'infinity_context_canonical_writer',
            'infinity_context_strict_v4_registrar',
            'infinity_context_strict_v4_sealer'
        )
          AND pg_catalog.pg_has_role(
              capability.oid,
              granted_role.oid,
              'MEMBER'
          )
    ) THEN
        RAISE EXCEPTION 'strict-v4 capability roles must not inherit other roles'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS capability
        CROSS JOIN pg_catalog.pg_namespace AS namespace
        WHERE capability.rolname IN (
            'infinity_context_canonical_writer',
            'infinity_context_strict_v4_registrar',
            'infinity_context_strict_v4_sealer'
        )
          AND namespace.nspname = 'public'
          AND pg_catalog.pg_has_role(capability.oid, namespace.nspowner, 'MEMBER')
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS capability
        CROSS JOIN pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE capability.rolname IN (
            'infinity_context_canonical_writer',
            'infinity_context_strict_v4_registrar',
            'infinity_context_strict_v4_sealer'
        )
          AND namespace.nspname = 'public'
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
          ]::pg_catalog.text[])
          AND pg_catalog.pg_has_role(capability.oid, relation.relowner, 'MEMBER')
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS capability
        CROSS JOIN pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        WHERE capability.rolname IN (
            'infinity_context_canonical_writer',
            'infinity_context_strict_v4_registrar',
            'infinity_context_strict_v4_sealer'
        )
          AND namespace.nspname = 'public'
          AND procedure.proname = ANY(ARRAY[
              'memory_comparison_is_strict_v4_canonical_writer',
              'memory_comparison_enforce_benchmark_writer_fence',
              'memory_cleanup_enforce_v3_context_authority_immutable',
              'memory_comparison_lock_strict_v4_registration_targets',
              'memory_comparison_lock_strict_v4_seal_targets',
              'memory_comparison_enforce_strict_v4_preparation_immutable',
              'memory_comparison_lock_benchmark_writer_target'
          ]::pg_catalog.text[])
          AND pg_catalog.pg_has_role(capability.oid, procedure.proowner, 'MEMBER')
    ) THEN
        RAISE EXCEPTION
            'strict-v4 capability roles must not own protected database objects'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS role
        CROSS JOIN pg_catalog.pg_namespace AS namespace
        WHERE role.rolname IN (
            'infinity_context_canonical_writer',
            'infinity_context_strict_v4_registrar',
            'infinity_context_strict_v4_sealer'
        )
          AND namespace.nspname = 'public'
          AND (
              NOT pg_catalog.has_schema_privilege(
                  role.oid, namespace.oid, 'USAGE'
              )
              OR pg_catalog.has_schema_privilege(
                  role.oid, namespace.oid, 'CREATE'
              )
              OR (
                  SELECT pg_catalog.count(*)
                  FROM pg_catalog.aclexplode(namespace.nspacl) AS acl
                  WHERE acl.grantee = role.oid
                    AND acl.privilege_type = 'USAGE'
                    AND NOT acl.is_grantable
              ) <> 1
              OR EXISTS (
                  SELECT 1
                  FROM pg_catalog.aclexplode(namespace.nspacl) AS acl
                  WHERE acl.grantee = role.oid
                    AND (
                        acl.privilege_type <> 'USAGE'
                        OR acl.is_grantable
                    )
              )
          )
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                namespace.nspacl,
                pg_catalog.acldefault('n', namespace.nspowner)
            )
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND acl.grantee = 0
          AND acl.privilege_type = 'CREATE'
    ) THEN
        RAISE EXCEPTION
            'strict-v4 capability roles require exact direct USAGE without CREATE'
            USING ERRCODE = '42501';
    END IF;
END
$role_precondition$;
CREATE TABLE public.memory_comparison_strict_v4_preparations (
    run_id_sha256 CHAR(64) PRIMARY KEY
        REFERENCES public.memory_comparison_benchmark_runs(run_id_sha256),
    context_sha256 CHAR(64) NOT NULL UNIQUE,
    authority_terminal_sha256 CHAR(64) NOT NULL,
    preparation_receipt_json JSONB NOT NULL,
    preparation_receipt_sha256 CHAR(64) NOT NULL,
    preparation_receipt_mac_sha256 CHAR(64) NOT NULL,
    writer_authority_json JSONB NOT NULL,
    writer_authority_sha256 CHAR(64) NOT NULL,
    writer_authority_mac_sha256 CHAR(64) NOT NULL,
    registration_sha256 CHAR(64) NOT NULL,
    registration_mac_sha256 CHAR(64) NOT NULL,
    provider_calls INTEGER NOT NULL,
    paid_go_ready BOOLEAN NOT NULL,
    state VARCHAR(16) NOT NULL,
    sealed_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    CONSTRAINT fk_strict_v4_preparation_context_authority FOREIGN KEY (
        run_id_sha256, context_sha256, authority_terminal_sha256
    ) REFERENCES public.memory_cleanup_v3_context_authorities(
        run_id_sha256, context_sha256, authority_terminal_sha256
    ),
    CONSTRAINT ck_strict_v4_preparation_digests CHECK (
        run_id_sha256 ~ '^[0-9a-f]{64}$'
        AND context_sha256 ~ '^[0-9a-f]{64}$'
        AND authority_terminal_sha256 ~ '^[0-9a-f]{64}$'
        AND preparation_receipt_sha256 ~ '^[0-9a-f]{64}$'
        AND preparation_receipt_mac_sha256 ~ '^[0-9a-f]{64}$'
        AND writer_authority_sha256 ~ '^[0-9a-f]{64}$'
        AND writer_authority_mac_sha256 ~ '^[0-9a-f]{64}$'
        AND registration_sha256 ~ '^[0-9a-f]{64}$'
        AND registration_mac_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_strict_v4_preparation_provider_free CHECK (
        provider_calls = 0 AND paid_go_ready = FALSE
    ),
    CONSTRAINT ck_strict_v4_preparation_lifecycle CHECK (
        (state = 'sealed' AND closed_at IS NULL)
        OR (state = 'closed' AND closed_at IS NOT NULL AND closed_at >= sealed_at)
    ),
    CONSTRAINT ck_strict_v4_preparation_temporal_binding CHECK (
        preparation_receipt_json ? 'prepared_at'
        AND preparation_receipt_json ? 'registered_at'
        AND writer_authority_json ? 'sealed_at'
        AND
        sealed_at >= (preparation_receipt_json->>'prepared_at')::pg_catalog.timestamptz
        AND (preparation_receipt_json->>'prepared_at')::pg_catalog.timestamptz >=
            (preparation_receipt_json->>'registered_at')::pg_catalog.timestamptz
        AND sealed_at >=
            (preparation_receipt_json->>'registered_at')::pg_catalog.timestamptz
        AND (writer_authority_json->>'sealed_at')::pg_catalog.timestamptz = sealed_at
    ),
    CONSTRAINT ck_strict_v4_preparation_receipt_binding CHECK (
        preparation_receipt_json->>'schema_version'
            = 'memory-comparison-strict-v4-full-preparation.v1'
        AND preparation_receipt_json->>'run_id_sha256' = run_id_sha256
        AND preparation_receipt_json#>>'{a2_context,context_sha256}' = context_sha256
        AND preparation_receipt_json#>>'{a2_authority,terminal_commitment_sha256}'
            = authority_terminal_sha256
        AND preparation_receipt_json->>'receipt_sha256' = preparation_receipt_sha256
        AND preparation_receipt_json->>'receipt_mac_sha256'
            = preparation_receipt_mac_sha256
        AND preparation_receipt_json->>'registration_sha256' = registration_sha256
        AND preparation_receipt_json->>'registration_mac_sha256'
            = registration_mac_sha256
        AND preparation_receipt_json->>'provider_calls' = '0'
        AND preparation_receipt_json->>'paid_go_ready' = 'false'
    ),
    CONSTRAINT ck_strict_v4_writer_authority_binding CHECK (
        writer_authority_json->>'schema_version'
            = 'memory-comparison-strict-v4-writer-authority.v1'
        AND writer_authority_json->>'run_id_sha256' = run_id_sha256
        AND writer_authority_json->>'context_sha256' = context_sha256
        AND writer_authority_json->>'authority_terminal_sha256'
            = authority_terminal_sha256
        AND writer_authority_json->>'preparation_receipt_sha256'
            = preparation_receipt_sha256
        AND writer_authority_json->>'preparation_receipt_mac_sha256'
            = preparation_receipt_mac_sha256
        AND writer_authority_json->>'registration_sha256' = registration_sha256
        AND writer_authority_json->>'registration_mac_sha256'
            = registration_mac_sha256
        AND writer_authority_json->>'a2_terminal_commitment_sha256'
            = authority_terminal_sha256
        AND writer_authority_json->>'expected_index_terminal_sha256'
            = authority_terminal_sha256
        AND writer_authority_json->>'provider_calls' = '0'
        AND writer_authority_json->>'paid_go_ready' = 'false'
        AND writer_authority_json->>'writer_authority_sha256'
            = writer_authority_sha256
        AND writer_authority_json->>'writer_authority_mac_sha256'
            = writer_authority_mac_sha256
    )
);
-- The execution writer can inspect the fence but cannot mint or alter authority.
DO $normalize_strict_v4_relation_acls$
DECLARE
    protected_relation TEXT;
    protected_columns TEXT;
BEGIN
    FOREACH protected_relation IN ARRAY ARRAY[
        'memory_comparison_benchmark_runs',
        'memory_cleanup_v3_context_authorities',
        'memory_comparison_strict_v4_preparations',
        'memory_spaces', 'memory_scopes', 'memory_threads', 'memory_facts',
        'memory_episodes', 'memory_documents', 'memory_chunks',
        'memory_fact_operation_receipts', 'memory_idempotency_records',
        'memory_anchors', 'memory_assets', 'memory_asset_extraction_jobs',
        'memory_fact_relations', 'memory_fact_temporal_decisions',
        'memory_suggestions', 'memory_captures', 'memory_context_links',
        'memory_context_link_suggestions', 'memory_source_refs',
        'memory_fact_versions', 'memory_outbox',
        'memory_projection_result_receipts',
        'memory_projection_receipt_claims',
        'memory_projection_target_identities',
        'memory_projection_receipt_identity_links',
        'memory_cleanup_inventory_materializations',
        'memory_cleanup_inventory_keys'
    ]
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM PUBLIC, '
            'infinity_context_canonical_writer, '
            'infinity_context_strict_v4_registrar, '
            'infinity_context_strict_v4_sealer',
            protected_relation
        );
        SELECT pg_catalog.string_agg(
            pg_catalog.format('%I', attribute.attname),
            ', ' ORDER BY attribute.attnum
        )
        INTO protected_columns
        FROM pg_catalog.pg_attribute AS attribute
        JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = protected_relation
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped;
        EXECUTE pg_catalog.format(
            'REVOKE SELECT (%1$s), INSERT (%1$s), UPDATE (%1$s), '
            'REFERENCES (%1$s) ON TABLE public.%2$I FROM PUBLIC, '
            'infinity_context_canonical_writer, '
            'infinity_context_strict_v4_registrar, '
            'infinity_context_strict_v4_sealer',
            protected_columns,
            protected_relation
        );
    END LOOP;
END
$normalize_strict_v4_relation_acls$;
REVOKE ALL PRIVILEGES ON SEQUENCE
    public.memory_source_refs_id_seq,
    public.memory_fact_versions_id_seq,
    public.memory_outbox_id_seq,
    public.memory_idempotency_records_id_seq
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;
GRANT SELECT ON public.memory_comparison_benchmark_runs
    TO infinity_context_canonical_writer,
       infinity_context_strict_v4_registrar,
       infinity_context_strict_v4_sealer;
GRANT SELECT ON public.memory_cleanup_v3_context_authorities
    TO infinity_context_canonical_writer,
       infinity_context_strict_v4_sealer;
GRANT SELECT, INSERT ON public.memory_cleanup_v3_context_authorities
    TO infinity_context_strict_v4_registrar;
GRANT SELECT ON public.memory_comparison_strict_v4_preparations
    TO infinity_context_canonical_writer;
GRANT SELECT, INSERT ON public.memory_comparison_strict_v4_preparations
    TO infinity_context_strict_v4_sealer;
GRANT SELECT, INSERT ON public.memory_idempotency_records
    TO infinity_context_canonical_writer;
GRANT USAGE ON SEQUENCE public.memory_idempotency_records_id_seq
    TO infinity_context_canonical_writer;
GRANT SELECT ON public.memory_scopes,
                public.memory_threads,
                public.memory_facts,
                public.memory_documents,
                public.memory_chunks,
                public.memory_fact_operation_receipts,
                public.memory_idempotency_records,
                public.memory_projection_result_receipts
    TO infinity_context_strict_v4_registrar,
       infinity_context_strict_v4_sealer;
CREATE OR REPLACE FUNCTION public.memory_cleanup_enforce_v3_context_authority_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'cleanup context authority is immutable'
        USING ERRCODE = '23514',
              CONSTRAINT = 'ck_memory_cleanup_v3_context_authority_immutable';
END;
$$;
REVOKE ALL PRIVILEGES ON FUNCTION
    public.memory_cleanup_enforce_v3_context_authority_immutable()
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;
CREATE TRIGGER trg_cleanup_v3_context_authority_immutable
BEFORE UPDATE OR DELETE ON public.memory_cleanup_v3_context_authorities
FOR EACH ROW
EXECUTE FUNCTION public.memory_cleanup_enforce_v3_context_authority_immutable();
CREATE OR REPLACE FUNCTION public.memory_comparison_lock_strict_v4_registration_targets(
    requested_run_id_sha256 CHAR(64),
    requested_context_sha256 CHAR(64)
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF requested_run_id_sha256 !~ '^[0-9a-f]{64}$'
        OR requested_context_sha256 !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION 'strict-v4 registration lock identity is invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM 1
    FROM public.memory_comparison_benchmark_runs
    WHERE run_id_sha256 = requested_run_id_sha256
    FOR UPDATE;
    PERFORM 1
    FROM public.memory_cleanup_v3_context_authorities
    WHERE run_id_sha256 = requested_run_id_sha256
       OR context_sha256 = requested_context_sha256
    ORDER BY run_id_sha256, context_sha256
    FOR UPDATE;
    IF NOT EXISTS (SELECT 1 FROM public.memory_cleanup_v3_context_authorities
                   WHERE run_id_sha256 = requested_run_id_sha256
                      OR context_sha256 = requested_context_sha256)
       AND EXISTS (
        SELECT 1 FROM public.memory_projection_receipt_claims WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
        UNION ALL SELECT 1 FROM public.memory_projection_target_identities WHERE run_id_sha256 = requested_run_id_sha256
        UNION ALL SELECT 1 FROM public.memory_projection_receipt_identity_links WHERE run_id_sha256 = requested_run_id_sha256
        UNION ALL SELECT 1 FROM public.memory_cleanup_inventory_materializations WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
        UNION ALL SELECT 1 FROM public.memory_cleanup_inventory_keys WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
    ) THEN
        RAISE EXCEPTION 'strict-v4 registration target state is not pristine'
            USING ERRCODE = '23514',
              CONSTRAINT = 'ck_memory_comparison_strict_v4_registration_pristine';
    END IF;
END;
$$;
REVOKE ALL PRIVILEGES ON FUNCTION
    public.memory_comparison_lock_strict_v4_registration_targets(CHAR, CHAR)
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;
GRANT EXECUTE ON FUNCTION
    public.memory_comparison_lock_strict_v4_registration_targets(CHAR, CHAR)
    TO infinity_context_strict_v4_registrar;
-- The sealer needs stable row locks but no UPDATE privilege over canonical
-- lifecycle rows. This narrowly scoped definer function locks and validates state;
-- it accepts no authority payload and performs no mutation.
CREATE OR REPLACE FUNCTION public.memory_comparison_lock_strict_v4_seal_targets(
    requested_run_id_sha256 CHAR(64),
    requested_context_sha256 CHAR(64)
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF requested_run_id_sha256 !~ '^[0-9a-f]{64}$'
        OR requested_context_sha256 !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION 'strict-v4 seal lock identity is invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM 1
    FROM public.memory_comparison_benchmark_runs
    WHERE run_id_sha256 = requested_run_id_sha256
    FOR UPDATE;
    PERFORM 1
    FROM public.memory_cleanup_v3_context_authorities
    WHERE run_id_sha256 = requested_run_id_sha256
       OR context_sha256 = requested_context_sha256
    ORDER BY run_id_sha256, context_sha256
    FOR UPDATE;
    PERFORM 1
    FROM public.memory_comparison_strict_v4_preparations
    WHERE run_id_sha256 = requested_run_id_sha256
       OR context_sha256 = requested_context_sha256
    ORDER BY run_id_sha256, context_sha256
    FOR UPDATE;
    IF NOT EXISTS (SELECT 1 FROM public.memory_comparison_strict_v4_preparations
                   WHERE run_id_sha256 = requested_run_id_sha256
                      OR context_sha256 = requested_context_sha256)
       AND EXISTS (
        SELECT 1 FROM public.memory_projection_receipt_claims WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
        UNION ALL SELECT 1 FROM public.memory_projection_target_identities WHERE run_id_sha256 = requested_run_id_sha256
        UNION ALL SELECT 1 FROM public.memory_projection_receipt_identity_links WHERE run_id_sha256 = requested_run_id_sha256
        UNION ALL SELECT 1 FROM public.memory_cleanup_inventory_materializations WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
        UNION ALL SELECT 1 FROM public.memory_cleanup_inventory_keys WHERE run_id_sha256 = requested_run_id_sha256 AND context_sha256 = requested_context_sha256
    ) THEN
        RAISE EXCEPTION 'strict-v4 seal target state is not pristine'
            USING ERRCODE = '23514',
              CONSTRAINT = 'ck_memory_comparison_strict_v4_seal_pristine';
    END IF;
END;
$$;
REVOKE ALL PRIVILEGES ON FUNCTION
    public.memory_comparison_lock_strict_v4_seal_targets(CHAR, CHAR)
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;
GRANT EXECUTE ON FUNCTION
    public.memory_comparison_lock_strict_v4_seal_targets(CHAR, CHAR)
    TO infinity_context_strict_v4_sealer;
CREATE OR REPLACE FUNCTION public.memory_comparison_enforce_strict_v4_preparation_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'strict-v4 preparation audit is immutable'
        USING ERRCODE = '23514',
              CONSTRAINT = 'ck_memory_comparison_strict_v4_preparation_immutable';
END;
$$;
REVOKE ALL PRIVILEGES ON FUNCTION
    public.memory_comparison_enforce_strict_v4_preparation_immutable()
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;
CREATE TRIGGER trg_strict_v4_preparation_immutable
BEFORE UPDATE OR DELETE ON public.memory_comparison_strict_v4_preparations
FOR EACH ROW
EXECUTE FUNCTION public.memory_comparison_enforce_strict_v4_preparation_immutable();
CREATE OR REPLACE FUNCTION public.memory_comparison_is_strict_v4_canonical_writer()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog, public, pg_temp
AS $$
WITH inventory AS (
    SELECT ARRAY[
        'memory_comparison_benchmark_runs',
        'memory_cleanup_v3_context_authorities',
        'memory_comparison_strict_v4_preparations',
        'memory_spaces', 'memory_scopes', 'memory_threads', 'memory_facts',
        'memory_episodes', 'memory_documents', 'memory_chunks',
        'memory_fact_operation_receipts', 'memory_idempotency_records',
        'memory_anchors', 'memory_assets', 'memory_asset_extraction_jobs',
        'memory_fact_relations', 'memory_fact_temporal_decisions',
        'memory_suggestions', 'memory_captures', 'memory_context_links',
        'memory_context_link_suggestions', 'memory_projection_result_receipts',
        'memory_projection_receipt_claims', 'memory_projection_target_identities',
        'memory_projection_receipt_identity_links',
        'memory_cleanup_inventory_materializations', 'memory_cleanup_inventory_keys',
        'memory_source_refs', 'memory_fact_versions', 'memory_outbox',
        'memory_source_refs_id_seq', 'memory_fact_versions_id_seq',
        'memory_outbox_id_seq', 'memory_idempotency_records_id_seq'
    ]::pg_catalog.text[] AS relation_names,
    ARRAY[
        'memory_comparison_is_strict_v4_canonical_writer',
        'memory_comparison_enforce_benchmark_writer_fence',
        'memory_cleanup_enforce_v3_context_authority_immutable',
        'memory_comparison_lock_strict_v4_registration_targets',
        'memory_comparison_lock_strict_v4_seal_targets',
        'memory_comparison_enforce_strict_v4_preparation_immutable',
        'memory_comparison_lock_benchmark_writer_target',
        'memory_comparison_lock_benchmark_fact_child_target',
        'memory_comparison_enforce_benchmark_fact_child_fence',
        'memory_comparison_enforce_benchmark_fact_receipt',
        'memory_comparison_verify_benchmark_fact_outbox_receipt',
        'memory_comparison_is_strict_v4_document_writer',
        'memory_comparison_lock_benchmark_document_child_target',
        'memory_comparison_enforce_benchmark_document_child_fence',
        'memory_comparison_enforce_benchmark_document_idempotency',
        'memory_comparison_verify_benchmark_document_receipt'
    ]::pg_catalog.text[] AS function_names
)
SELECT COALESCE((
    SELECT current_user = session_user
       AND role.rolcanlogin
       AND NOT role.rolsuper
       AND NOT role.rolbypassrls
       AND NOT role.rolcreatedb
       AND NOT role.rolcreaterole
       AND NOT role.rolreplication
       AND NOT capability.rolcanlogin AND NOT capability.rolsuper
       AND NOT capability.rolbypassrls AND NOT capability.rolcreatedb
       AND NOT capability.rolcreaterole AND NOT capability.rolreplication
       AND pg_catalog.has_schema_privilege(role.oid, 'public', 'USAGE')
       AND NOT pg_catalog.has_schema_privilege(role.oid, 'public', 'CREATE')
       AND pg_catalog.pg_has_role(
           role.oid, capability.oid, 'MEMBER'
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_roles AS granted_role
           WHERE granted_role.oid <> role.oid
             AND granted_role.rolname <> 'infinity_context_canonical_writer'
             AND pg_catalog.pg_has_role(role.oid, granted_role.oid, 'MEMBER')
       )
       AND NOT EXISTS (
           SELECT 1 FROM pg_catalog.pg_auth_members AS membership
           WHERE membership.member = role.oid AND membership.admin_option
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           WHERE namespace.nspname = 'public'
             AND relation.relname = ANY(inventory.relation_names)
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
             AND procedure.proname = ANY(inventory.function_names)
             AND pg_catalog.pg_has_role(role.oid, procedure.proowner, 'MEMBER')
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
           WHERE namespace.nspname = 'public'
             AND relation.relname = ANY(inventory.relation_names)
             AND (
                 acl.grantee = role.oid
                 OR (acl.grantee = capability.oid AND acl.is_grantable)
             )
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
           WHERE namespace.nspname = 'public'
             AND relation.relname = ANY(inventory.relation_names)
             AND acl.grantee = 0
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_attribute AS attribute
           JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
           WHERE namespace.nspname = 'public'
             AND relation.relname = ANY(inventory.relation_names)
             AND attribute.attnum > 0 AND NOT attribute.attisdropped
             AND acl.grantee IN (0, role.oid, capability.oid)
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.unnest(ARRAY[
               'SELECT', 'INSERT', 'UPDATE', 'DELETE',
               'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN'
           ]::pg_catalog.text[]) AS privilege(name)
           WHERE namespace.nspname = 'public'
             AND relation.relname = ANY(inventory.relation_names)
             AND relation.relkind <> 'S'
             AND pg_catalog.has_table_privilege(
                 role.oid,
                 relation.oid,
                 privilege.name
             ) IS DISTINCT FROM CASE
                 WHEN privilege.name = 'SELECT' THEN
                     relation.relname IN (
                         'memory_comparison_benchmark_runs',
                         'memory_cleanup_v3_context_authorities',
                         'memory_comparison_strict_v4_preparations',
                         'memory_idempotency_records'
                     )
                 WHEN privilege.name = 'INSERT' THEN
                     relation.relname = 'memory_idempotency_records'
                 ELSE FALSE
             END
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.unnest(
               ARRAY['SELECT', 'USAGE', 'UPDATE']::pg_catalog.text[]
           ) AS privilege(name)
           WHERE namespace.nspname = 'public'
             AND relation.relname = ANY(inventory.relation_names)
             AND relation.relkind = 'S'
             AND pg_catalog.has_sequence_privilege(
                 role.oid,
                 relation.oid,
                 privilege.name
             ) IS DISTINCT FROM (
                 relation.relname = 'memory_idempotency_records_id_seq'
                 AND privilege.name = 'USAGE'
             )
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_namespace AS namespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl
           WHERE namespace.nspname = 'public'
             AND (
                 acl.grantee = role.oid
                 OR (acl.grantee = capability.oid AND (
                     acl.privilege_type <> 'USAGE' OR acl.is_grantable
                 ))
             )
       )
       AND (
           SELECT pg_catalog.count(*)
           FROM pg_catalog.pg_namespace AS namespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl
           WHERE namespace.nspname = 'public' AND acl.grantee = capability.oid
             AND acl.privilege_type = 'USAGE' AND NOT acl.is_grantable
       ) = 1
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = procedure.pronamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(procedure.proacl) AS acl
           WHERE namespace.nspname = 'public'
             AND procedure.proname = ANY(inventory.function_names)
             AND (
                 acl.grantee = role.oid
                 OR (acl.grantee = capability.oid AND acl.is_grantable)
             )
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
             AND procedure.proname = ANY(inventory.function_names)
             AND acl.grantee = 0
       )
       AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = procedure.pronamespace
           WHERE namespace.nspname = 'public'
             AND procedure.proname = ANY(inventory.function_names)
             AND pg_catalog.has_function_privilege(
                 role.oid, procedure.oid, 'EXECUTE'
             ) IS DISTINCT FROM (
                 procedure.oid = pg_catalog.to_regprocedure(
                     'public.memory_comparison_is_strict_v4_canonical_writer()'
                 )
             )
       )
    FROM pg_catalog.pg_roles AS role
    CROSS JOIN pg_catalog.pg_roles AS capability
    CROSS JOIN inventory
    WHERE role.rolname = current_user
      AND capability.rolname = 'infinity_context_canonical_writer'
), FALSE)
$$;
REVOKE ALL PRIVILEGES ON FUNCTION
    public.memory_comparison_is_strict_v4_canonical_writer()
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;
GRANT EXECUTE ON FUNCTION public.memory_comparison_is_strict_v4_canonical_writer()
    TO infinity_context_canonical_writer;
CREATE OR REPLACE FUNCTION public.memory_comparison_lock_benchmark_writer_target()
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
REVOKE ALL PRIVILEGES ON FUNCTION public.memory_comparison_lock_benchmark_writer_target()
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;
CREATE OR REPLACE FUNCTION public.memory_comparison_enforce_benchmark_writer_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    registry_state VARCHAR(40);
    registry_projection_cleanup_state VARCHAR(40);
    registry_cleanup_plan_state VARCHAR(40);
    registry_run_id_sha256 CHAR(64);
    strict_v4_writer_credential BOOLEAN := pg_catalog.pg_has_role(
        session_user, 'infinity_context_canonical_writer', 'MEMBER'
    );
    strict_v4_authority_credential BOOLEAN := pg_catalog.pg_has_role(
        session_user, 'infinity_context_strict_v4_registrar', 'MEMBER'
    ) OR pg_catalog.pg_has_role(
        session_user, 'infinity_context_strict_v4_sealer', 'MEMBER'
    );
    strict_v4_writer_login BOOLEAN := FALSE;
    strict_v4_authority_exists BOOLEAN := FALSE;
    strict_v4_write_authorized BOOLEAN := FALSE;
    legacy_write_authorized BOOLEAN := FALSE;
    old_space_id VARCHAR(80);
    new_space_id VARCHAR(80);
    target_space_id VARCHAR(80);
BEGIN
    IF strict_v4_writer_credential THEN
        strict_v4_writer_login :=
            public.memory_comparison_is_strict_v4_canonical_writer();
    END IF;
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
        ) INTO strict_v4_authority_exists;
        strict_v4_write_authorized :=
            strict_v4_writer_login AND strict_v4_authority_exists;
    END IF;
    IF registry_state IS NULL AND NOT strict_v4_writer_credential
        AND NOT strict_v4_authority_credential THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    IF registry_state = 'active'
        AND registry_projection_cleanup_state = 'unsealed'
        AND TG_OP = 'INSERT'
        AND (
            (legacy_write_authorized AND NOT strict_v4_writer_credential
                AND NOT strict_v4_authority_credential
                AND NOT strict_v4_authority_exists
                AND TG_TABLE_NAME IN (
                'memory_scopes', 'memory_threads', 'memory_facts',
                'memory_documents', 'memory_chunks',
                'memory_fact_operation_receipts', 'memory_idempotency_records'
            ))
            OR (NOT legacy_write_authorized AND strict_v4_write_authorized
                AND TG_TABLE_NAME = 'memory_idempotency_records')
        )
    THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' AND NOT strict_v4_writer_credential
        AND NOT strict_v4_authority_credential
        AND TG_TABLE_NAME IN (
            'memory_spaces', 'memory_scopes', 'memory_threads', 'memory_facts',
            'memory_episodes', 'memory_documents', 'memory_chunks'
        )
    THEN
        IF registry_state = 'cleanup_pending'
            AND registry_projection_cleanup_state IN ('pending', 'blocked')
            AND OLD.status = 'active'
            AND NEW.status = 'deleted'
            AND (pg_catalog.to_jsonb(OLD) - 'status' - 'updated_at' - 'thread_scope_key')
                = (pg_catalog.to_jsonb(NEW) - 'status' - 'updated_at' - 'thread_scope_key')
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
REVOKE ALL PRIVILEGES ON FUNCTION
    public.memory_comparison_enforce_benchmark_writer_fence()
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;
DO $install_benchmark_writer_triggers$
DECLARE
    protected_table TEXT;
    lock_trigger TEXT;
    policy_trigger TEXT;
BEGIN
    FOREACH protected_table IN ARRAY ARRAY[
        'memory_spaces', 'memory_scopes', 'memory_threads', 'memory_facts',
        'memory_episodes', 'memory_documents', 'memory_chunks',
        'memory_fact_operation_receipts', 'memory_idempotency_records',
        'memory_anchors', 'memory_assets', 'memory_asset_extraction_jobs',
        'memory_fact_relations', 'memory_fact_temporal_decisions',
        'memory_suggestions', 'memory_captures', 'memory_context_links',
        'memory_context_link_suggestions'
    ]
    LOOP
        lock_trigger := 'trg_00_' || protected_table || '_benchmark_writer_lock';
        EXECUTE pg_catalog.format(
            'DROP TRIGGER IF EXISTS %I ON public.%I',
            lock_trigger,
            protected_table
        );
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER %I BEFORE INSERT OR UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'public.memory_comparison_lock_benchmark_writer_target()',
            lock_trigger,
            protected_table
        );
        policy_trigger := 'trg_' || protected_table || '_benchmark_writer_fence';
        EXECUTE pg_catalog.format(
            'DROP TRIGGER IF EXISTS %I ON public.%I', policy_trigger, protected_table
        );
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER %I BEFORE INSERT OR UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'public.memory_comparison_enforce_benchmark_writer_fence()',
            policy_trigger, protected_table
        );
    END LOOP;
END
$install_benchmark_writer_triggers$;
SET LOCAL search_path = public, pg_catalog, pg_temp;
