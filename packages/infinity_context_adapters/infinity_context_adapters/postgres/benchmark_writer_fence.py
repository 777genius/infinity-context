"""Postgres DDL for the managed benchmark canonical writer fence."""

from __future__ import annotations

BENCHMARK_WRITER_FENCE_SQLSTATE = "23514"
BENCHMARK_WRITER_FENCE_CONSTRAINT = "ck_memory_comparison_benchmark_run_writer_fence"
BENCHMARK_WRITER_FENCE_FUNCTION = "memory_comparison_enforce_benchmark_writer_fence"
BENCHMARK_STRICT_V4_CANONICAL_WRITER_FUNCTION = "memory_comparison_is_strict_v4_canonical_writer"
BENCHMARK_WRITER_FENCE_TABLES = (
    ("memory_spaces", "id, status"),
    ("memory_scopes", "space_id, status"),
    ("memory_threads", "space_id, status"),
    ("memory_facts", "space_id, status"),
    ("memory_episodes", "space_id, status"),
    ("memory_documents", "space_id, status"),
    ("memory_chunks", "space_id, status"),
    ("memory_fact_operation_receipts", "space_id"),
    ("memory_idempotency_records", "space_id"),
    ("memory_anchors", "space_id, status"),
    ("memory_assets", "space_id, status"),
    ("memory_asset_extraction_jobs", "space_id, status"),
    ("memory_fact_relations", "space_id, status"),
    ("memory_fact_temporal_decisions", "space_id"),
    ("memory_suggestions", "space_id, status"),
    ("memory_captures", "space_id, status"),
    ("memory_context_links", "space_id, status"),
    ("memory_context_link_suggestions", "space_id, status"),
)

BENCHMARK_INITIAL_INSERT_TABLES = ("memory_idempotency_records",)

BENCHMARK_WRITER_FENCE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION public.{BENCHMARK_STRICT_V4_CANONICAL_WRITER_FUNCTION}()
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
                    ERRCODE = '{BENCHMARK_WRITER_FENCE_SQLSTATE}',
                    CONSTRAINT = '{BENCHMARK_WRITER_FENCE_CONSTRAINT}';
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

CREATE OR REPLACE FUNCTION public.{BENCHMARK_WRITER_FENCE_FUNCTION}()
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
            public.{BENCHMARK_STRICT_V4_CANONICAL_WRITER_FUNCTION}();
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
                    ERRCODE = '{BENCHMARK_WRITER_FENCE_SQLSTATE}',
                    CONSTRAINT = '{BENCHMARK_WRITER_FENCE_CONSTRAINT}';
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
            ERRCODE = '{BENCHMARK_WRITER_FENCE_SQLSTATE}',
            CONSTRAINT = '{BENCHMARK_WRITER_FENCE_CONSTRAINT}';
END;
$$;

REVOKE ALL PRIVILEGES ON FUNCTION
    public.memory_comparison_enforce_benchmark_writer_fence()
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer
""".strip()


def _installed_function_body(function_name: str) -> str:
    marker = f"CREATE OR REPLACE FUNCTION public.{function_name}()"
    function_sql = BENCHMARK_WRITER_FENCE_FUNCTION_SQL.split(marker, 1)[1]
    return function_sql.split("AS $$", 1)[1].split("$$;", 1)[0]


BENCHMARK_WRITER_LOCK_FUNCTION_BODY = _installed_function_body(
    "memory_comparison_lock_benchmark_writer_target"
)
BENCHMARK_CANONICAL_WRITER_FUNCTION_BODY = _installed_function_body(
    BENCHMARK_STRICT_V4_CANONICAL_WRITER_FUNCTION
)
BENCHMARK_WRITER_POLICY_FUNCTION_BODY = _installed_function_body(BENCHMARK_WRITER_FENCE_FUNCTION)


def _trigger_statements(table: str, _update_columns: str) -> tuple[str, str, str, str]:
    lock_trigger_name = f"trg_00_{table}_benchmark_writer_lock"
    trigger_name = f"trg_{table}_benchmark_writer_fence"
    return (
        f"DROP TRIGGER IF EXISTS {lock_trigger_name} ON public.{table}",
        f"""
        CREATE TRIGGER {lock_trigger_name}
        BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
        FOR EACH ROW
        EXECUTE FUNCTION public.memory_comparison_lock_benchmark_writer_target()
        """.strip(),
        f"DROP TRIGGER IF EXISTS {trigger_name} ON public.{table}",
        f"""
        CREATE TRIGGER {trigger_name}
        BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
        FOR EACH ROW
        EXECUTE FUNCTION public.{BENCHMARK_WRITER_FENCE_FUNCTION}()
        """.strip(),
    )


BENCHMARK_WRITER_FENCE_STATEMENTS = (
    BENCHMARK_WRITER_FENCE_FUNCTION_SQL,
    *(
        statement
        for table, update_columns in BENCHMARK_WRITER_FENCE_TABLES
        for statement in _trigger_statements(table, update_columns)
    ),
)

__all__ = (
    "BENCHMARK_WRITER_FENCE_CONSTRAINT",
    "BENCHMARK_WRITER_FENCE_FUNCTION",
    "BENCHMARK_STRICT_V4_CANONICAL_WRITER_FUNCTION",
    "BENCHMARK_INITIAL_INSERT_TABLES",
    "BENCHMARK_CANONICAL_WRITER_FUNCTION_BODY",
    "BENCHMARK_WRITER_LOCK_FUNCTION_BODY",
    "BENCHMARK_WRITER_POLICY_FUNCTION_BODY",
    "BENCHMARK_WRITER_FENCE_SQLSTATE",
    "BENCHMARK_WRITER_FENCE_STATEMENTS",
    "BENCHMARK_WRITER_FENCE_TABLES",
)
