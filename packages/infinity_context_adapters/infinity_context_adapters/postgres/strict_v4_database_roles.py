"""Database-role capabilities for strict-v4 privileged adapters."""

from __future__ import annotations

from typing import Any

from infinity_context_core.features.projection_receipts import ProjectionReceiptError

STRICT_V4_CANONICAL_WRITER_ROLE = "infinity_context_canonical_writer"
# Retained as legacy identifiers for callers that have not yet removed the paid-write
# lanes. They are deliberately not accepted by the strict-v4 runtime attestation.
STRICT_V4_FACT_WRITER_ROLE = "infinity_context_strict_v4_fact_writer"
STRICT_V4_DOCUMENT_WRITER_ROLE = "infinity_context_strict_v4_document_writer"
STRICT_V4_REGISTRAR_ROLE = "infinity_context_strict_v4_registrar"
STRICT_V4_SEALER_ROLE = "infinity_context_strict_v4_sealer"
STRICT_V4_CAPABILITY_ROLES = (
    STRICT_V4_CANONICAL_WRITER_ROLE,
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
    "memory_locator_commit_watermark_seq",
)
STRICT_V4_PROTECTED_FUNCTIONS = (
    "memory_comparison_lock_strict_v4_registration_targets",
    "memory_comparison_lock_strict_v4_seal_targets",
    "memory_comparison_is_strict_v4_canonical_writer",
    "memory_comparison_enforce_benchmark_writer_fence",
    "memory_cleanup_enforce_v3_context_authority_immutable",
    "memory_comparison_enforce_strict_v4_preparation_immutable",
    "memory_comparison_lock_benchmark_writer_target",
    "memory_comparison_lock_benchmark_fact_child_target",
    "memory_comparison_enforce_benchmark_fact_child_fence",
    "memory_comparison_enforce_benchmark_fact_receipt",
    "memory_comparison_verify_benchmark_fact_outbox_receipt",
    "memory_comparison_lock_benchmark_document_child_target",
    "memory_comparison_enforce_benchmark_document_child_fence",
    "memory_comparison_enforce_benchmark_document_idempotency",
    "memory_comparison_verify_benchmark_document_receipt",
)
STRICT_V4_REQUIRED_FUNCTION_SIGNATURES = (
    "public.memory_cleanup_enforce_v3_context_authority_immutable()",
    "public.memory_comparison_lock_strict_v4_registration_targets("
    "pg_catalog.bpchar,pg_catalog.bpchar)",
    "public.memory_comparison_lock_strict_v4_seal_targets(pg_catalog.bpchar,pg_catalog.bpchar)",
    "public.memory_comparison_enforce_strict_v4_preparation_immutable()",
    "public.memory_comparison_is_strict_v4_canonical_writer()",
    "public.memory_comparison_lock_benchmark_writer_target()",
    "public.memory_comparison_enforce_benchmark_writer_fence()",
)
STRICT_V4_PROTECTED_SEQUENCES = (
    "memory_source_refs_id_seq",
    "memory_fact_versions_id_seq",
    "memory_outbox_id_seq",
    "memory_idempotency_records_id_seq",
)

_CAPABILITY_SQL = """
WITH protected_relations AS (
    SELECT relation.oid, relation.relkind, relation.relname,
           relation.relowner, relation.relacl
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid=relation.relnamespace
    WHERE namespace.nspname='public'
      AND relation.relname=ANY($2::pg_catalog.text[])
),
protected_functions AS (
    SELECT procedure.oid, procedure.proname, procedure.proowner, procedure.proacl
    FROM pg_catalog.pg_proc AS procedure
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid=procedure.pronamespace
    WHERE namespace.nspname='public'
      AND procedure.proname=ANY($3::pg_catalog.text[])
),
required_functions AS (
    SELECT pg_catalog.to_regprocedure(signature) AS oid
    FROM pg_catalog.unnest($4::pg_catalog.text[]) AS required(signature)
),
expected_function AS (
    SELECT CASE $1
        WHEN 'infinity_context_canonical_writer' THEN
            pg_catalog.to_regprocedure(
                'public.memory_comparison_is_strict_v4_canonical_writer()'
            )
        WHEN 'infinity_context_strict_v4_registrar' THEN
            pg_catalog.to_regprocedure(
                'public.memory_comparison_lock_strict_v4_registration_targets('
                'pg_catalog.bpchar,pg_catalog.bpchar)'
            )
        WHEN 'infinity_context_strict_v4_sealer' THEN
            pg_catalog.to_regprocedure(
                'public.memory_comparison_lock_strict_v4_seal_targets('
                'pg_catalog.bpchar,pg_catalog.bpchar)'
            )
    END AS oid
)
SELECT current_user = session_user AS direct_login,
       role.rolcanlogin AS is_login,
       pg_catalog.pg_has_role(role.oid, capability.oid, 'MEMBER') AS role_member,
       NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_roles AS granted_role
           WHERE granted_role.oid <> role.oid
             AND granted_role.oid <> capability.oid
             AND pg_catalog.pg_has_role(role.oid, granted_role.oid, 'MEMBER')
       ) AS no_other_membership,
       NOT role.rolsuper AS not_superuser,
       NOT role.rolbypassrls AS no_bypass_rls,
       NOT role.rolcreatedb AS no_createdb,
       NOT role.rolcreaterole AS no_createrole,
       NOT role.rolreplication AS no_replication,
       NOT capability.rolcanlogin
         AND NOT capability.rolsuper
         AND NOT capability.rolbypassrls
         AND NOT capability.rolcreatedb
         AND NOT capability.rolcreaterole
         AND NOT capability.rolreplication
         AS capability_role_safe,
       (SELECT pg_catalog.count(*)=pg_catalog.cardinality($2::pg_catalog.text[])
           AND pg_catalog.bool_and(
               relation.relkind = CASE
                   WHEN relation.relname=ANY($5::pg_catalog.text[]) THEN 'S'
                   ELSE 'r'
               END
           )
        FROM protected_relations AS relation) AS has_exact_relation_inventory,
       NOT EXISTS (
           SELECT 1 FROM required_functions WHERE oid IS NULL
       ) AS has_required_function_inventory,
       NOT EXISTS (
           SELECT 1
           FROM protected_relations AS relation
           WHERE pg_catalog.pg_has_role(role.oid, relation.relowner, 'MEMBER')
       ) AS owns_no_protected_relation
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_namespace AS namespace
           WHERE namespace.nspname='public'
             AND pg_catalog.pg_has_role(role.oid, namespace.nspowner, 'MEMBER')
       ) AS owns_no_protected_schema
       , pg_catalog.has_schema_privilege(role.oid, 'public', 'USAGE')
         AS can_use_protected_schema
       , NOT pg_catalog.has_schema_privilege(role.oid, 'public', 'CREATE')
         AS cannot_create_in_protected_schema
       , NOT EXISTS (
           SELECT 1
           FROM protected_functions AS procedure
           WHERE pg_catalog.pg_has_role(role.oid, procedure.proowner, 'MEMBER')
       ) AS owns_no_protected_function
       , NOT EXISTS (
           SELECT 1
           FROM protected_relations AS relation
           CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
           WHERE acl.grantee=role.oid
       ) AS has_no_direct_relation_acl
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_namespace AS namespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl
           WHERE namespace.nspname='public'
             AND acl.grantee=role.oid
       ) AS has_no_direct_schema_acl
       , (
           SELECT pg_catalog.count(*)=1
              AND pg_catalog.bool_and(
                  acl.privilege_type='USAGE' AND NOT acl.is_grantable
              )
           FROM pg_catalog.pg_namespace AS namespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl
           WHERE namespace.nspname='public'
             AND acl.grantee=capability.oid
       ) AS has_exact_capability_schema_acl
       , NOT EXISTS (
           SELECT 1
           FROM protected_functions AS procedure
           CROSS JOIN LATERAL pg_catalog.aclexplode(procedure.proacl) AS acl
           WHERE acl.grantee=role.oid
       ) AS has_no_direct_function_acl
       , NOT EXISTS (
           SELECT 1
           FROM protected_relations AS relation
           CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
           WHERE acl.grantee=0
       ) AS has_no_public_relation_acl
       , NOT EXISTS (
           SELECT 1
           FROM protected_functions AS procedure
           CROSS JOIN LATERAL pg_catalog.aclexplode(
               COALESCE(
                   procedure.proacl,
                   pg_catalog.acldefault('f', procedure.proowner)
               )
           ) AS acl
           WHERE acl.grantee=0
       ) AS has_no_public_function_acl
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_attribute AS attribute
           JOIN protected_relations AS relation
             ON relation.oid=attribute.attrelid
           CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
           WHERE attribute.attnum > 0
             AND NOT attribute.attisdropped
             AND acl.grantee=role.oid
       ) AS has_no_direct_column_acl
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_attribute AS attribute
           JOIN protected_relations AS relation
             ON relation.oid=attribute.attrelid
           CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
           WHERE attribute.attnum > 0
             AND NOT attribute.attisdropped
             AND acl.grantee=capability.oid
       ) AS has_no_capability_column_acl
       , NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_attribute AS attribute
           JOIN protected_relations AS relation
             ON relation.oid=attribute.attrelid
           CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
           WHERE attribute.attnum > 0
             AND NOT attribute.attisdropped
             AND acl.grantee=0
       ) AS has_no_public_column_acl
       , NOT EXISTS (
           SELECT 1
           FROM protected_relations AS relation
           CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
           WHERE acl.grantee=capability.oid
             AND acl.is_grantable
       )
         AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_namespace AS namespace
           CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl
           WHERE namespace.nspname='public'
             AND acl.grantee=capability.oid
             AND acl.is_grantable
       )
         AND NOT EXISTS (
           SELECT 1
           FROM protected_functions AS procedure
           CROSS JOIN LATERAL pg_catalog.aclexplode(procedure.proacl) AS acl
           WHERE acl.grantee=capability.oid
             AND acl.is_grantable
       )
         AND NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_auth_members AS membership
           WHERE membership.member=role.oid
             AND membership.admin_option
       ) AS has_no_grant_options
       , NOT EXISTS (
           SELECT 1
           FROM protected_relations AS relation
           CROSS JOIN LATERAL pg_catalog.unnest(ARRAY[
               'SELECT', 'INSERT', 'UPDATE', 'DELETE',
               'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN'
           ]::pg_catalog.text[]) AS privilege(name)
           WHERE relation.relkind <> 'S'
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
                                 'memory_spaces', 'memory_scopes',
                                 'memory_threads', 'memory_facts',
                                 'memory_fact_versions', 'memory_source_refs',
                                 'memory_documents', 'memory_chunks',
                                 'memory_fact_operation_receipts',
                                 'memory_idempotency_records', 'memory_outbox'
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
                         AND relation.relname IN (
                             'memory_scopes', 'memory_threads', 'memory_facts',
                             'memory_fact_versions', 'memory_source_refs',
                             'memory_documents', 'memory_chunks',
                             'memory_fact_operation_receipts',
                             'memory_idempotency_records', 'memory_outbox'
                         ))
                     OR ($1 = 'infinity_context_strict_v4_registrar'
                         AND relation.relname =
                             'memory_cleanup_v3_context_authorities')
                     OR ($1 = 'infinity_context_strict_v4_sealer'
                         AND relation.relname =
                             'memory_comparison_strict_v4_preparations')
                 WHEN privilege.name = 'DELETE' THEN
                     $1 = 'infinity_context_canonical_writer'
                     AND relation.relname = 'memory_source_refs'
                 ELSE FALSE
             END
       ) AS has_exact_effective_relation_acl
       , NOT EXISTS (
           SELECT 1
           FROM protected_relations AS relation
           CROSS JOIN LATERAL pg_catalog.unnest(
               ARRAY['SELECT', 'USAGE', 'UPDATE']::pg_catalog.text[]
           ) AS privilege(name)
           WHERE relation.relkind = 'S'
             AND pg_catalog.has_sequence_privilege(
                 role.oid,
                 relation.oid,
                 privilege.name
             ) IS DISTINCT FROM (
                 ($1 = 'infinity_context_canonical_writer'
                  AND relation.relname IN (
                      'memory_source_refs_id_seq',
                      'memory_fact_versions_id_seq',
                      'memory_outbox_id_seq',
                      'memory_idempotency_records_id_seq',
                      'memory_locator_commit_watermark_seq'
                  ))
                 AND privilege.name = 'USAGE'
             )
       ) AS has_exact_effective_sequence_acl
       , expected_function.oid IS NOT NULL
         AND NOT EXISTS (
           SELECT 1
           FROM protected_functions AS procedure
           WHERE pg_catalog.has_function_privilege(
               role.oid,
               procedure.oid,
               'EXECUTE'
           ) IS DISTINCT FROM (procedure.oid=expected_function.oid)
       ) AS has_exact_effective_function_acl
FROM pg_catalog.pg_roles AS role
CROSS JOIN pg_catalog.pg_roles AS capability
CROSS JOIN expected_function
WHERE role.rolname=current_user
  AND capability.rolname=$1
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
        list(STRICT_V4_PROTECTED_FUNCTIONS),
        list(STRICT_V4_REQUIRED_FUNCTION_SIGNATURES),
        list(STRICT_V4_PROTECTED_SEQUENCES),
    )
    if row is None or not all(
        row.get(field) is True
        for field in (
            "direct_login",
            "is_login",
            "role_member",
            "no_other_membership",
            "not_superuser",
            "no_bypass_rls",
            "no_createdb",
            "no_createrole",
            "no_replication",
            "capability_role_safe",
            "has_exact_relation_inventory",
            "has_required_function_inventory",
            "owns_no_protected_relation",
            "owns_no_protected_schema",
            "can_use_protected_schema",
            "cannot_create_in_protected_schema",
            "owns_no_protected_function",
            "has_no_direct_relation_acl",
            "has_no_direct_schema_acl",
            "has_exact_capability_schema_acl",
            "has_no_direct_function_acl",
            "has_no_public_relation_acl",
            "has_no_public_function_acl",
            "has_no_direct_column_acl",
            "has_no_capability_column_acl",
            "has_no_public_column_acl",
            "has_no_grant_options",
            "has_exact_effective_relation_acl",
            "has_exact_effective_sequence_acl",
            "has_exact_effective_function_acl",
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
    "STRICT_V4_PROTECTED_FUNCTIONS",
    "STRICT_V4_PROTECTED_SEQUENCES",
    "STRICT_V4_REQUIRED_FUNCTION_SIGNATURES",
    "assert_strict_v4_runtime_capability",
)
