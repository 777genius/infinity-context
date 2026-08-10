"""Postgres DDL for the managed benchmark canonical writer fence."""

from __future__ import annotations

from infinity_context_adapters.postgres.strict_v4_fact_graph_fence import (
    STRICT_V4_FACT_GRAPH_FENCE_STATEMENTS,
)

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

BENCHMARK_INITIAL_INSERT_TABLES = (
    "memory_scopes",
    "memory_threads",
    "memory_facts",
    "memory_documents",
    "memory_chunks",
    "memory_fact_operation_receipts",
    "memory_idempotency_records",
)

BENCHMARK_WRITER_FENCE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {BENCHMARK_STRICT_V4_CANONICAL_WRITER_FUNCTION}()
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
                    ERRCODE = '{BENCHMARK_WRITER_FENCE_SQLSTATE}',
                    CONSTRAINT = '{BENCHMARK_WRITER_FENCE_CONSTRAINT}';
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

CREATE OR REPLACE FUNCTION {BENCHMARK_WRITER_FENCE_FUNCTION}()
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
              AND public.{BENCHMARK_STRICT_V4_CANONICAL_WRITER_FUNCTION}()
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
            ERRCODE = '{BENCHMARK_WRITER_FENCE_SQLSTATE}',
            CONSTRAINT = '{BENCHMARK_WRITER_FENCE_CONSTRAINT}';
END;
$$;

REVOKE ALL ON FUNCTION memory_comparison_enforce_benchmark_writer_fence()
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_fact_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer
""".strip()


def _trigger_statements(table: str, _update_columns: str) -> tuple[str, str, str, str]:
    lock_trigger_name = f"trg_00_{table}_benchmark_writer_lock"
    trigger_name = f"trg_{table}_benchmark_writer_fence"
    return (
        f"DROP TRIGGER IF EXISTS {lock_trigger_name} ON {table}",
        f"""
        CREATE TRIGGER {lock_trigger_name}
        BEFORE INSERT OR UPDATE OR DELETE ON {table}
        FOR EACH ROW
        EXECUTE FUNCTION memory_comparison_lock_benchmark_writer_target()
        """.strip(),
        f"DROP TRIGGER IF EXISTS {trigger_name} ON {table}",
        f"""
        CREATE TRIGGER {trigger_name}
        BEFORE INSERT OR UPDATE OR DELETE ON {table}
        FOR EACH ROW
        EXECUTE FUNCTION {BENCHMARK_WRITER_FENCE_FUNCTION}()
        """.strip(),
    )


BENCHMARK_WRITER_FENCE_STATEMENTS = (
    BENCHMARK_WRITER_FENCE_FUNCTION_SQL,
    *(
        statement
        for table, update_columns in BENCHMARK_WRITER_FENCE_TABLES
        for statement in _trigger_statements(table, update_columns)
    ),
    *STRICT_V4_FACT_GRAPH_FENCE_STATEMENTS,
)

__all__ = (
    "BENCHMARK_WRITER_FENCE_CONSTRAINT",
    "BENCHMARK_WRITER_FENCE_FUNCTION",
    "BENCHMARK_STRICT_V4_CANONICAL_WRITER_FUNCTION",
    "BENCHMARK_INITIAL_INSERT_TABLES",
    "BENCHMARK_WRITER_FENCE_SQLSTATE",
    "BENCHMARK_WRITER_FENCE_STATEMENTS",
    "BENCHMARK_WRITER_FENCE_TABLES",
)
