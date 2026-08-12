-- Reconcile the login used by the general API/seed/projection/extraction runtime.
-- Apply through the migration object owner after every packaged migration completes.
DO $infinity_context_runtime_acl$
DECLARE
    runtime_oid oid;
    relation_name text;
    column_names text;
    sequence_name text;
    capability_name text;
    capability_signature text;
    object_identity text;
    writable_relations constant text[] := ARRAY[
        'code_repositories', 'code_repository_aliases', 'code_repository_bindings',
        'code_scope_authorizations', 'memory_anchors', 'memory_asset_extraction_artifacts',
        'memory_asset_extraction_jobs', 'memory_assets', 'memory_captures', 'memory_chunks',
        'memory_cognitive_dependencies', 'memory_cognitive_projections', 'memory_context_links',
        'memory_context_link_suggestions', 'memory_documents', 'memory_episodes',
        'memory_fact_operation_receipts', 'memory_fact_relations',
        'memory_fact_temporal_decisions', 'memory_fact_versions', 'memory_facts',
        'memory_idempotency_records', 'memory_outbox', 'memory_projection_receipt_claims',
        'memory_projection_receipt_identity_links', 'memory_projection_result_receipts',
        'memory_projection_target_identities', 'memory_scopes', 'memory_service_tokens',
        'memory_source_refs', 'memory_space_memberships', 'memory_spaces', 'memory_suggestions',
        'memory_threads', 'memory_usage_records', 'memory_users',
        'suggestion_resolution_receipts'
    ];
    authority_read_relations constant text[] := ARRAY[
        'memory_cleanup_inventory_keys', 'memory_cleanup_inventory_materializations',
        'memory_cleanup_v3_context_authorities', 'memory_comparison_benchmark_runs',
        'memory_comparison_strict_v4_preparations'
    ];
    runtime_sequences constant text[] := ARRAY[
        'code_repository_aliases_id_seq', 'memory_cognitive_dependencies_id_seq',
        'memory_fact_versions_id_seq', 'memory_idempotency_records_id_seq',
        'memory_outbox_id_seq', 'memory_source_refs_id_seq'
    ];
    strict_capability_functions constant text[] := ARRAY[
        'memory_comparison_is_strict_v4_canonical_writer',
        'memory_comparison_lock_strict_v4_registration_targets',
        'memory_comparison_lock_strict_v4_seal_targets'
    ];
BEGIN
    SELECT role.oid INTO runtime_oid
      FROM pg_catalog.pg_roles AS role
     WHERE role.rolname = 'infinity_context_runtime'
       AND role.rolcanlogin
       AND NOT role.rolsuper
       AND NOT role.rolinherit
       AND NOT role.rolcreaterole
       AND NOT role.rolcreatedb
       AND NOT role.rolreplication
       AND NOT role.rolbypassrls;
    IF runtime_oid IS NULL THEN
        RAISE EXCEPTION
            'infinity_context_runtime must be a LOGIN NOINHERIT non-powerful role';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members AS membership
         WHERE membership.member = runtime_oid
    ) THEN
        RAISE EXCEPTION 'infinity_context_runtime must not inherit role memberships';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_class AS relation WHERE relation.relowner = runtime_oid
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc AS function WHERE function.proowner = runtime_oid
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_namespace AS namespace
         WHERE namespace.nspowner = runtime_oid
    ) THEN
        RAISE EXCEPTION 'infinity_context_runtime must not own database objects';
    END IF;

    REVOKE ALL PRIVILEGES ON SCHEMA public FROM infinity_context_runtime;
    GRANT USAGE ON SCHEMA public TO infinity_context_runtime;

    -- Erase direct drift across the schema before installing the fixed inventory.
    FOR object_identity IN
        SELECT pg_catalog.format('%I.%I', namespace.nspname, relation.relname)
          FROM pg_catalog.pg_class AS relation
          JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
         WHERE namespace.nspname = 'public'
           AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES ON TABLE %s FROM infinity_context_runtime',
            object_identity
        );
    END LOOP;
    FOR object_identity IN
        SELECT pg_catalog.format('%I.%I', namespace.nspname, relation.relname)
          FROM pg_catalog.pg_class AS relation
          JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
         WHERE namespace.nspname = 'public'
           AND relation.relkind = 'S'
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES ON SEQUENCE %s FROM infinity_context_runtime',
            object_identity
        );
    END LOOP;
    FOR object_identity IN
        SELECT pg_catalog.format(
                   '%I.%I(%s)', namespace.nspname, function.proname,
                   pg_catalog.pg_get_function_identity_arguments(function.oid)
               )
          FROM pg_catalog.pg_proc AS function
          JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = function.pronamespace
         WHERE namespace.nspname = 'public'
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES ON FUNCTION %s FROM infinity_context_runtime',
            object_identity
        );
    END LOOP;

    FOREACH relation_name IN ARRAY writable_relations || authority_read_relations LOOP
        IF pg_catalog.to_regclass(pg_catalog.format('public.%I', relation_name)) IS NULL THEN
            RAISE EXCEPTION 'runtime ACL relation is missing: %', relation_name;
        END IF;
        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM PUBLIC, infinity_context_runtime',
            relation_name
        );
        SELECT pg_catalog.string_agg(pg_catalog.quote_ident(attribute.attname), ', ')
          INTO column_names
          FROM pg_catalog.pg_attribute AS attribute
         WHERE attribute.attrelid = pg_catalog.to_regclass(
                   pg_catalog.format('public.%I', relation_name)
               )
           AND attribute.attnum > 0
           AND NOT attribute.attisdropped;
        EXECUTE pg_catalog.format(
            'REVOKE SELECT (%1$s), INSERT (%1$s), UPDATE (%1$s), REFERENCES (%1$s) '
            'ON TABLE public.%2$I FROM PUBLIC, infinity_context_runtime',
            column_names,
            relation_name
        );
    END LOOP;
    FOREACH relation_name IN ARRAY writable_relations LOOP
        EXECUTE pg_catalog.format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO infinity_context_runtime',
            relation_name
        );
    END LOOP;
    FOREACH relation_name IN ARRAY authority_read_relations LOOP
        EXECUTE pg_catalog.format(
            'GRANT SELECT ON TABLE public.%I TO infinity_context_runtime', relation_name
        );
    END LOOP;

    FOREACH sequence_name IN ARRAY runtime_sequences LOOP
        IF pg_catalog.to_regclass(pg_catalog.format('public.%I', sequence_name)) IS NULL THEN
            RAISE EXCEPTION 'runtime ACL sequence is missing: %', sequence_name;
        END IF;
        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES ON SEQUENCE public.%I FROM PUBLIC, infinity_context_runtime',
            sequence_name
        );
        EXECUTE pg_catalog.format(
            'GRANT USAGE ON SEQUENCE public.%I TO infinity_context_runtime', sequence_name
        );
    END LOOP;

    FOREACH capability_name IN ARRAY strict_capability_functions LOOP
        capability_signature := NULL;
        FOR capability_signature IN
            SELECT pg_catalog.format(
                       '%I.%I(%s)', namespace.nspname, function.proname,
                       pg_catalog.pg_get_function_identity_arguments(function.oid)
                   )
              FROM pg_catalog.pg_proc AS function
              JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = function.pronamespace
             WHERE namespace.nspname = 'public'
               AND function.proname = capability_name
        LOOP
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON FUNCTION %s FROM PUBLIC, infinity_context_runtime',
                capability_signature
            );
        END LOOP;
        IF capability_signature IS NULL THEN
            RAISE EXCEPTION 'strict capability function is missing: %', capability_name;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_class AS relation
          JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
          CROSS JOIN LATERAL pg_catalog.aclexplode(
              COALESCE(relation.relacl, pg_catalog.acldefault(
                  CASE relation.relkind WHEN 'S' THEN 'S'::"char" ELSE 'r'::"char" END,
                  relation.relowner
              ))
          ) AS acl
         WHERE namespace.nspname = 'public'
           AND relation.relname = ANY(writable_relations || authority_read_relations)
           AND (
               acl.grantee = 0
               OR (acl.grantee = runtime_oid AND (
                   acl.is_grantable OR acl.privilege_type <> ALL(
                       CASE WHEN relation.relname = ANY(writable_relations)
                           THEN ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']
                           ELSE ARRAY['SELECT'] END
                   )
               ))
           )
    ) THEN
        RAISE EXCEPTION 'runtime relation ACL reconciliation failed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_attribute AS attribute
          JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
          JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
          CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
         WHERE namespace.nspname = 'public'
           AND relation.relname = ANY(writable_relations || authority_read_relations)
           AND acl.grantee IN (0, runtime_oid)
    ) THEN
        RAISE EXCEPTION 'runtime column ACL reconciliation failed';
    END IF;
    FOREACH relation_name IN ARRAY writable_relations LOOP
        IF NOT pg_catalog.has_table_privilege(
            runtime_oid, pg_catalog.format('public.%I', relation_name), 'SELECT'
        ) OR NOT pg_catalog.has_table_privilege(
            runtime_oid, pg_catalog.format('public.%I', relation_name), 'INSERT'
        ) OR NOT pg_catalog.has_table_privilege(
            runtime_oid, pg_catalog.format('public.%I', relation_name), 'UPDATE'
        ) OR NOT pg_catalog.has_table_privilege(
            runtime_oid, pg_catalog.format('public.%I', relation_name), 'DELETE'
        ) OR pg_catalog.has_table_privilege(
            runtime_oid, pg_catalog.format('public.%I', relation_name),
            'TRUNCATE, REFERENCES, TRIGGER'
        ) THEN
            RAISE EXCEPTION 'runtime writable relation ACL is incomplete: %', relation_name;
        END IF;
    END LOOP;
    FOREACH relation_name IN ARRAY authority_read_relations LOOP
        IF NOT pg_catalog.has_table_privilege(
            runtime_oid, pg_catalog.format('public.%I', relation_name), 'SELECT'
        ) OR pg_catalog.has_table_privilege(
            runtime_oid, pg_catalog.format('public.%I', relation_name),
            'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'
        ) THEN
            RAISE EXCEPTION 'runtime authority relation ACL is not read-only: %', relation_name;
        END IF;
    END LOOP;
    FOREACH sequence_name IN ARRAY runtime_sequences LOOP
        IF NOT pg_catalog.has_sequence_privilege(
            runtime_oid, pg_catalog.format('public.%I', sequence_name), 'USAGE'
        ) OR pg_catalog.has_sequence_privilege(
            runtime_oid, pg_catalog.format('public.%I', sequence_name), 'SELECT, UPDATE'
        ) THEN
            RAISE EXCEPTION 'runtime sequence ACL is not usage-only: %', sequence_name;
        END IF;
    END LOOP;
END
$infinity_context_runtime_acl$;
