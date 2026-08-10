"""Database-role capabilities for strict-v4 privileged adapters."""

from __future__ import annotations

from typing import Any

from infinity_context_core.features.projection_receipts import ProjectionReceiptError

STRICT_V4_CANONICAL_WRITER_ROLE = "infinity_context_canonical_writer"
STRICT_V4_FACT_WRITER_ROLE = "infinity_context_strict_v4_fact_writer"
STRICT_V4_DOCUMENT_WRITER_ROLE = "infinity_context_strict_v4_document_writer"
STRICT_V4_REGISTRAR_ROLE = "infinity_context_strict_v4_registrar"
STRICT_V4_SEALER_ROLE = "infinity_context_strict_v4_sealer"
STRICT_V4_CAPABILITY_ROLES = (
    STRICT_V4_CANONICAL_WRITER_ROLE,
    STRICT_V4_FACT_WRITER_ROLE,
    STRICT_V4_DOCUMENT_WRITER_ROLE,
    STRICT_V4_REGISTRAR_ROLE,
    STRICT_V4_SEALER_ROLE,
)
STRICT_V4_PROTECTED_RELATIONS = (
    "memory_comparison_benchmark_runs",
    "memory_cleanup_v3_context_authorities",
    "memory_comparison_strict_v4_preparations",
    "memory_spaces",
    "memory_scopes",
    "memory_threads",
    "memory_facts",
    "memory_episodes",
    "memory_documents",
    "memory_chunks",
    "memory_fact_operation_receipts",
    "memory_idempotency_records",
    "memory_anchors",
    "memory_assets",
    "memory_asset_extraction_jobs",
    "memory_fact_relations",
    "memory_fact_temporal_decisions",
    "memory_suggestions",
    "memory_captures",
    "memory_context_links",
    "memory_context_link_suggestions",
    "memory_projection_result_receipts",
    "memory_projection_receipt_claims",
    "memory_projection_target_identities",
    "memory_projection_receipt_identity_links",
    "memory_cleanup_inventory_materializations",
    "memory_cleanup_inventory_keys",
    "memory_source_refs",
    "memory_fact_versions",
    "memory_outbox",
    "memory_source_refs_id_seq",
    "memory_fact_versions_id_seq",
    "memory_outbox_id_seq",
    "memory_idempotency_records_id_seq",
)

_CAPABILITY_SQL = """
SELECT current_user = session_user AS direct_login,
       pg_catalog.pg_has_role(current_user, $1, 'MEMBER') AS role_member,
       NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_roles AS granted_role
           WHERE granted_role.oid <> role.oid
             AND granted_role.rolname <> $1
             AND pg_catalog.pg_has_role(role.oid, granted_role.oid, 'MEMBER')
       ) AS no_other_membership,
       NOT role.rolsuper AS not_superuser,
       NOT role.rolbypassrls AS no_bypass_rls,
       NOT role.rolcreatedb AS no_createdb,
       NOT role.rolcreaterole AS no_createrole,
       NOT role.rolreplication AS no_replication,
       NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid=relation.relnamespace
           WHERE namespace.nspname='public'
             AND relation.relname=ANY($2::text[])
             AND pg_catalog.pg_has_role(role.oid, relation.relowner, 'MEMBER')
       ) AS owns_no_protected_relation
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_namespace AS namespace
           WHERE namespace.nspname='public'
             AND pg_catalog.pg_has_role(role.oid, namespace.nspowner, 'MEMBER')
       ) AS owns_no_protected_schema
       , NOT pg_catalog.has_schema_privilege(role.oid, 'public', 'CREATE')
         AS cannot_create_in_protected_schema
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS function
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid=function.pronamespace
           WHERE namespace.nspname='public'
             AND function.proname IN (
                 'memory_comparison_lock_strict_v4_registration_targets',
                 'memory_comparison_lock_strict_v4_seal_targets',
                 'memory_comparison_is_strict_v4_canonical_writer',
                 'memory_comparison_enforce_benchmark_writer_fence',
                 'memory_comparison_close_strict_v4_preparation',
                 'memory_cleanup_enforce_v3_context_authority_immutable',
                 'memory_comparison_enforce_strict_v4_preparation_immutable',
                 'memory_comparison_lock_benchmark_writer_target'
                 , 'memory_comparison_lock_benchmark_fact_child_target'
                 , 'memory_comparison_enforce_benchmark_fact_child_fence'
                 , 'memory_comparison_enforce_benchmark_fact_receipt'
                 , 'memory_comparison_verify_benchmark_fact_outbox_receipt'
                 , 'memory_comparison_is_strict_v4_document_writer'
                 , 'memory_comparison_lock_benchmark_document_child_target'
                 , 'memory_comparison_enforce_benchmark_document_child_fence'
                 , 'memory_comparison_enforce_benchmark_document_idempotency'
                 , 'memory_comparison_verify_benchmark_document_receipt'
             )
             AND pg_catalog.pg_has_role(role.oid, function.proowner, 'MEMBER')
       ) AS owns_no_protected_function
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid=relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
           WHERE namespace.nspname='public'
             AND relation.relname=ANY($2::text[])
             AND acl.grantee=role.oid
       ) AS has_no_direct_relation_acl
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_namespace AS namespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl
           WHERE namespace.nspname='public'
             AND acl.grantee=role.oid
       ) AS has_no_direct_schema_acl
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS function
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid=function.pronamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(function.proacl) AS acl
           WHERE namespace.nspname='public'
             AND function.proname IN (
                 'memory_comparison_lock_strict_v4_registration_targets',
                 'memory_comparison_lock_strict_v4_seal_targets',
                 'memory_comparison_is_strict_v4_canonical_writer',
                 'memory_comparison_enforce_benchmark_writer_fence',
                 'memory_comparison_close_strict_v4_preparation',
                 'memory_cleanup_enforce_v3_context_authority_immutable',
                 'memory_comparison_enforce_strict_v4_preparation_immutable',
                 'memory_comparison_lock_benchmark_writer_target'
                 , 'memory_comparison_lock_benchmark_fact_child_target'
                 , 'memory_comparison_enforce_benchmark_fact_child_fence'
                 , 'memory_comparison_enforce_benchmark_fact_receipt'
                 , 'memory_comparison_verify_benchmark_fact_outbox_receipt'
                 , 'memory_comparison_is_strict_v4_document_writer'
                 , 'memory_comparison_lock_benchmark_document_child_target'
                 , 'memory_comparison_enforce_benchmark_document_child_fence'
                 , 'memory_comparison_enforce_benchmark_document_idempotency'
                 , 'memory_comparison_verify_benchmark_document_receipt'
             )
             AND acl.grantee=role.oid
       ) AS has_no_direct_function_acl
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid=relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
           WHERE namespace.nspname='public'
             AND relation.relname=ANY($2::text[])
             AND acl.grantee=0
       ) AS has_no_public_relation_acl
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS function
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid=function.pronamespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(
               COALESCE(
                   function.proacl,
                   pg_catalog.acldefault('f', function.proowner)
               )
           ) AS acl
           WHERE namespace.nspname='public'
             AND function.proname IN (
                 'memory_comparison_lock_strict_v4_registration_targets',
                 'memory_comparison_lock_strict_v4_seal_targets',
                 'memory_comparison_is_strict_v4_canonical_writer',
                 'memory_comparison_enforce_benchmark_writer_fence',
                 'memory_comparison_close_strict_v4_preparation',
                 'memory_cleanup_enforce_v3_context_authority_immutable',
                 'memory_comparison_enforce_strict_v4_preparation_immutable',
                 'memory_comparison_lock_benchmark_writer_target'
                 , 'memory_comparison_lock_benchmark_fact_child_target'
                 , 'memory_comparison_enforce_benchmark_fact_child_fence'
                 , 'memory_comparison_enforce_benchmark_fact_receipt'
                 , 'memory_comparison_verify_benchmark_fact_outbox_receipt'
                 , 'memory_comparison_is_strict_v4_document_writer'
                 , 'memory_comparison_lock_benchmark_document_child_target'
                 , 'memory_comparison_enforce_benchmark_document_child_fence'
                 , 'memory_comparison_enforce_benchmark_document_idempotency'
                 , 'memory_comparison_verify_benchmark_document_receipt'
             )
             AND acl.grantee=0
       ) AS has_no_public_function_acl
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid=relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.unnest(ARRAY[
               'SELECT', 'INSERT', 'UPDATE', 'DELETE',
               'TRUNCATE', 'REFERENCES', 'TRIGGER'
           ]::text[]) AS privilege(name)
           WHERE namespace.nspname='public'
             AND relation.relname=ANY($2::text[])
             AND relation.relkind <> 'S'
             AND pg_catalog.has_table_privilege(
                 role.oid,
                 relation.oid,
                 privilege.name
             ) IS DISTINCT FROM CASE
                 WHEN privilege.name = 'SELECT' THEN
                     CASE $1
                         WHEN 'infinity_context_canonical_writer' THEN
                             relation.relname IN (
                                 'memory_comparison_benchmark_runs',
                                 'memory_cleanup_v3_context_authorities',
                                 'memory_comparison_strict_v4_preparations',
                                 'memory_idempotency_records'
                             )
                         WHEN 'infinity_context_strict_v4_fact_writer' THEN
                             relation.relname IN (
                                 'memory_comparison_benchmark_runs',
                                 'memory_cleanup_v3_context_authorities',
                                 'memory_comparison_strict_v4_preparations',
                                 'memory_spaces', 'memory_scopes',
                                 'memory_threads', 'memory_facts',
                                 'memory_fact_versions', 'memory_source_refs',
                                 'memory_outbox',
                                 'memory_fact_operation_receipts'
                             )
                         WHEN 'infinity_context_strict_v4_document_writer' THEN
                             relation.relname IN (
                                 'memory_comparison_benchmark_runs',
                                 'memory_cleanup_v3_context_authorities',
                                 'memory_comparison_strict_v4_preparations',
                                 'memory_spaces', 'memory_scopes',
                                 'memory_threads', 'memory_documents',
                                 'memory_chunks', 'memory_outbox',
                                 'memory_idempotency_records'
                             )
                         WHEN 'infinity_context_strict_v4_registrar' THEN
                             relation.relname IN (
                                 'memory_comparison_benchmark_runs',
                                 'memory_cleanup_v3_context_authorities',
                                 'memory_scopes', 'memory_threads', 'memory_facts',
                                 'memory_documents', 'memory_chunks',
                                 'memory_fact_operation_receipts',
                                 'memory_idempotency_records',
                                 'memory_projection_result_receipts'
                             )
                         WHEN 'infinity_context_strict_v4_sealer' THEN
                             relation.relname IN (
                                 'memory_comparison_benchmark_runs',
                                 'memory_cleanup_v3_context_authorities',
                                 'memory_comparison_strict_v4_preparations',
                                 'memory_scopes', 'memory_threads', 'memory_facts',
                                 'memory_documents', 'memory_chunks',
                                 'memory_fact_operation_receipts',
                                 'memory_idempotency_records',
                                 'memory_projection_result_receipts'
                             )
                         ELSE FALSE
                     END
                 WHEN privilege.name = 'INSERT' THEN
                     ($1 = 'infinity_context_canonical_writer'
                         AND relation.relname = 'memory_idempotency_records')
                     OR ($1 = 'infinity_context_strict_v4_fact_writer'
                         AND relation.relname IN (
                             'memory_scopes', 'memory_threads', 'memory_facts',
                             'memory_fact_versions', 'memory_source_refs',
                             'memory_outbox', 'memory_fact_operation_receipts'
                         ))
                     OR ($1 = 'infinity_context_strict_v4_document_writer'
                         AND relation.relname IN (
                             'memory_scopes', 'memory_threads',
                             'memory_documents', 'memory_chunks',
                             'memory_outbox', 'memory_idempotency_records'
                         ))
                     OR ($1 = 'infinity_context_strict_v4_registrar'
                         AND relation.relname =
                             'memory_cleanup_v3_context_authorities')
                     OR ($1 = 'infinity_context_strict_v4_sealer'
                         AND relation.relname =
                             'memory_comparison_strict_v4_preparations')
                 WHEN privilege.name = 'DELETE' THEN
                     $1 = 'infinity_context_strict_v4_fact_writer'
                     AND relation.relname = 'memory_source_refs'
                 ELSE FALSE
             END
       ) AS has_exact_effective_relation_acl
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid=relation.relnamespace
           CROSS JOIN LATERAL pg_catalog.unnest(
               ARRAY['SELECT', 'USAGE', 'UPDATE']::text[]
           ) AS privilege(name)
           WHERE namespace.nspname='public'
             AND relation.relname=ANY($2::text[])
             AND relation.relkind = 'S'
             AND pg_catalog.has_sequence_privilege(
                 role.oid,
                 relation.oid,
                 privilege.name
             ) IS DISTINCT FROM (
                 (($1 = 'infinity_context_canonical_writer'
                   AND relation.relname = 'memory_idempotency_records_id_seq')
                  OR ($1 = 'infinity_context_strict_v4_fact_writer'
                      AND relation.relname IN (
                          'memory_source_refs_id_seq',
                          'memory_fact_versions_id_seq',
                          'memory_outbox_id_seq'
                      ))
                  OR ($1 = 'infinity_context_strict_v4_document_writer'
                      AND relation.relname IN (
                          'memory_outbox_id_seq',
                          'memory_idempotency_records_id_seq'
                      )))
                 AND privilege.name = 'USAGE'
             )
       ) AS has_exact_effective_sequence_acl
FROM pg_catalog.pg_roles AS role
WHERE role.rolname = current_user
"""


async def assert_strict_v4_runtime_capability(
    connection: Any,
    *,
    capability_role: str,
    error_code: str,
) -> None:
    if capability_role not in STRICT_V4_CAPABILITY_ROLES:
        raise ProjectionReceiptError(error_code)
    row = await connection.fetchrow(
        _CAPABILITY_SQL,
        capability_role,
        list(STRICT_V4_PROTECTED_RELATIONS),
    )
    if row is None or not all(
        row.get(field) is True
        for field in (
            "direct_login",
            "role_member",
            "no_other_membership",
            "not_superuser",
            "no_bypass_rls",
            "no_createdb",
            "no_createrole",
            "no_replication",
            "owns_no_protected_relation",
            "owns_no_protected_schema",
            "cannot_create_in_protected_schema",
            "owns_no_protected_function",
            "has_no_direct_relation_acl",
            "has_no_direct_schema_acl",
            "has_no_direct_function_acl",
            "has_no_public_relation_acl",
            "has_no_public_function_acl",
            "has_exact_effective_relation_acl",
            "has_exact_effective_sequence_acl",
        )
    ):
        raise ProjectionReceiptError(error_code)


__all__ = (
    "STRICT_V4_CANONICAL_WRITER_ROLE",
    "STRICT_V4_FACT_WRITER_ROLE",
    "STRICT_V4_DOCUMENT_WRITER_ROLE",
    "STRICT_V4_REGISTRAR_ROLE",
    "STRICT_V4_SEALER_ROLE",
    "STRICT_V4_CAPABILITY_ROLES",
    "STRICT_V4_PROTECTED_RELATIONS",
    "assert_strict_v4_runtime_capability",
)
