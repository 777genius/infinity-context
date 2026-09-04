"""Trusted static descriptors and queries for locator catalog attestation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final


@dataclass(frozen=True, slots=True)
class _IndexSpec:
    table: str
    unique: bool
    keys: tuple[str, ...]
    opclasses: tuple[str, ...]
    collation_columns: tuple[str | None, ...]
    predicate: str


@dataclass(frozen=True, slots=True)
class _ConstraintSpec:
    table: str
    constraint_type: str
    validated: bool
    columns: tuple[str, ...]
    definition: str
    referenced_table: str | None = None


@dataclass(frozen=True, slots=True)
class _TriggerSpec:
    table: str
    function: str
    trigger_type: int
    definition: str


@dataclass(frozen=True, slots=True)
class _ColumnSpec:
    table: str
    data_type: str
    nullable: bool
    default: str


@dataclass(frozen=True, slots=True)
class _FunctionSpec:
    owner_table: str
    security_definer: bool
    public_execute: bool
    body: str


_SCHEMA: Final = "public"
_SAFE_SEARCH_PATH: Final = ("search_path=pg_catalog, public, pg_temp",)
_MIGRATIONS_DIRECTORY: Final = Path(__file__).with_name("migrations")


def _trusted_migration_sql(name: str) -> str:
    return (_MIGRATIONS_DIRECTORY / name).read_text(encoding="utf-8")


_TRUSTED_0059_SQL: Final = _trusted_migration_sql("0059_locator_parent_lifecycle.sql")
_TRUSTED_0040_SQL: Final = _trusted_migration_sql("0040_locator_profile_lifecycle.sql")

_DOCUMENT_CHANGE_TERMS: Final = (
    "OLD.status::text IS DISTINCT FROM NEW.status::text",
    "OLD.classification::text IS DISTINCT FROM NEW.classification::text",
    "OLD.retrieval_projected IS DISTINCT FROM NEW.retrieval_projected",
    "OLD.space_id::text IS DISTINCT FROM NEW.space_id::text",
    "OLD.memory_scope_id::text IS DISTINCT FROM NEW.memory_scope_id::text",
    "OLD.thread_id::text IS DISTINCT FROM NEW.thread_id::text",
    "OLD.source_type::text IS DISTINCT FROM NEW.source_type::text",
    "OLD.source_external_id::text IS DISTINCT FROM NEW.source_external_id::text",
)


def _canonical_document_update_trigger(
    name: str,
    *,
    timing: str,
    function: str,
    retrieval_guard: bool,
    include_id: bool,
) -> str:
    """Describe the fixed pg_get_triggerdef form of a trusted 0059 predicate."""

    changes = " OR ".join(_DOCUMENT_CHANGE_TERMS)
    if retrieval_guard:
        changes = f"(OLD.retrieval_projected OR NEW.retrieval_projected) AND ({changes})"
    if include_id:
        changes = f"OLD.id::text IS DISTINCT FROM NEW.id::text OR {changes}"
    return (
        f"CREATE TRIGGER {name} {timing} UPDATE ON public.memory_documents "
        f"FOR EACH ROW WHEN ({changes}) EXECUTE FUNCTION public.{function}()"
    )


_CANONICAL_TRUSTED_TRIGGER_DEFINITIONS: Final = {
    # PostgreSQL reports trigger events in its fixed INSERT, DELETE, UPDATE order.
    "trg_memory_chunk_locator_profile_events_v2": (
        "CREATE TRIGGER trg_memory_chunk_locator_profile_events_v2 "
        "AFTER INSERT OR DELETE OR UPDATE ON public.memory_chunks FOR EACH ROW "
        "EXECUTE FUNCTION public.memory_chunk_locator_profile_events_v2()"
    ),
    # PostgreSQL expands these trusted ROW(...) IS DISTINCT FROM ROW(...)
    # predicates into complete per-column comparisons.  varchar columns receive
    # ::text casts; the boolean retrieval_projected column deliberately does not.
    "trg_00_document_locator_profile_evidence_update": (
        _canonical_document_update_trigger(
            "trg_00_document_locator_profile_evidence_update",
            timing="BEFORE",
            function="memory_locator_profile_invalidate_evidence_v1",
            retrieval_guard=True,
            include_id=False,
        )
    ),
    "trg_01_document_locator_parent_lock_update": _canonical_document_update_trigger(
        "trg_01_document_locator_parent_lock_update",
        timing="BEFORE",
        function="memory_document_lock_locator_parent_v1",
        retrieval_guard=True,
        include_id=True,
    ),
    "trg_document_invalidate_locator_children_update": (
        _canonical_document_update_trigger(
            "trg_document_invalidate_locator_children_update",
            timing="AFTER",
            function="memory_document_invalidate_locator_children_v1",
            retrieval_guard=False,
            include_id=True,
        )
    ),
}


def _trusted_function_body(function_name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{re.escape(function_name)}\(\).*?"
        r"\bAS \$\$(.*?)\$\$;",
        _TRUSTED_0059_SQL,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError(f"Trusted 0059 function missing: {function_name}")
    return match.group(1)


def _trusted_trigger_definition(trigger_name: str, migration_sql: str) -> str:
    match = re.search(
        rf"CREATE TRIGGER {re.escape(trigger_name)}\b(.*?);",
        migration_sql,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError(f"Trusted migration trigger missing: {trigger_name}")
    canonical = _CANONICAL_TRUSTED_TRIGGER_DEFINITIONS.get(trigger_name)
    if canonical is not None:
        return canonical
    return f"CREATE TRIGGER {trigger_name}{match.group(1)}"


_COLUMNS: Final = {
    "memory_locator_runtime_incarnations.locator_parent_capability": _ColumnSpec(
        "memory_locator_runtime_incarnations", "bigint", False, "0"
    ),
    "memory_chunks.retrieval_parent_version": _ColumnSpec("memory_chunks", "bigint", False, "1"),
}

_FUNCTIONS: Final = {
    name: _FunctionSpec(
        owner_table=owner_table,
        security_definer=security_definer,
        public_execute=not security_definer,
        body=_trusted_function_body(name),
    )
    for name, owner_table, security_definer in (
        (
            "memory_locator_require_parent_capability_v1",
            "memory_locator_runtime_incarnations",
            False,
        ),
        ("memory_chunk_retrieval_fence_v2", "memory_chunks", False),
        ("memory_chunk_require_locator_parent_v1", "memory_chunks", False),
        ("memory_document_lock_locator_parent_v1", "memory_documents", False),
        ("memory_chunk_locator_profile_events_v2", "memory_chunks", False),
        ("memory_document_invalidate_locator_children_v1", "memory_documents", True),
    )
}
_INDEXES: Final = {
    "uq_memory_chunks_retrieval_locator_owner": _IndexSpec(
        "memory_chunks",
        True,
        ("space_id", "memory_scope_id", "retrieval_locator"),
        ("pg_catalog.text_ops",) * 3,
        ("space_id", "memory_scope_id", "retrieval_locator"),
        "retrieval_locator IS NOT NULL",
    ),
    "uq_memory_chunks_retrieval_active_ordinal_owner": _IndexSpec(
        "memory_chunks",
        True,
        (
            "space_id",
            "memory_scope_id",
            "COALESCE(thread_id, ''::character varying)",
            "retrieval_source_key",
            "retrieval_projection_generation",
            "retrieval_sequence_ordinal",
        ),
        ("pg_catalog.text_ops",) * 5 + ("pg_catalog.int4_ops",),
        (
            "space_id",
            "memory_scope_id",
            "thread_id",
            "retrieval_source_key",
            "retrieval_projection_generation",
            None,
        ),
        "retrieval_locator IS NOT NULL AND status::text = 'active'::text "
        "AND (classification::text = ANY "
        "(ARRAY['public'::character varying, 'internal'::character varying]::text[]))",
    ),
    "ix_memory_chunks_locator_retrieval": _IndexSpec(
        "memory_chunks",
        False,
        (
            "space_id",
            "memory_scope_id",
            "status",
            "retrieval_source_key",
            "retrieval_projection_generation",
            "retrieval_sequence_ordinal",
        ),
        ("pg_catalog.text_ops",) * 5 + ("pg_catalog.int4_ops",),
        (
            "space_id",
            "memory_scope_id",
            "status",
            "retrieval_source_key",
            "retrieval_projection_generation",
            None,
        ),
        "retrieval_locator IS NOT NULL",
    ),
}

_CONSTRAINTS: Final = {
    "ck_memory_chunks_retrieval_version_positive": _ConstraintSpec(
        "memory_chunks",
        "c",
        False,
        ("retrieval_version",),
        "CHECK (retrieval_version >= 1 AND "
        "retrieval_version <= '9007199254740991'::bigint) NOT VALID",
    ),
    "ck_memory_chunks_retrieval_parent_version_positive": _ConstraintSpec(
        "memory_chunks",
        "c",
        True,
        ("retrieval_parent_version",),
        "CHECK (retrieval_parent_version >= 1 AND "
        "retrieval_parent_version <= '9007199254740991'::bigint)",
    ),
    "ck_locator_runtime_parent_capability": _ConstraintSpec(
        "memory_locator_runtime_incarnations",
        "c",
        True,
        ("locator_parent_capability",),
        "CHECK (locator_parent_capability = ANY (ARRAY[0::bigint, 1::bigint]))",
    ),
    "ck_memory_chunks_retrieval_coordinates_complete": _ConstraintSpec(
        "memory_chunks",
        "c",
        False,
        (
            "retrieval_locator",
            "retrieval_source_key",
            "retrieval_projection_generation",
            "retrieval_sequence_ordinal",
            "retrieval_kind",
            "retrieval_category",
        ),
        """CHECK (retrieval_locator IS NULL AND retrieval_source_key IS NULL
          AND retrieval_projection_generation IS NULL AND retrieval_sequence_ordinal IS NULL
          AND retrieval_kind IS NULL AND retrieval_category IS NULL OR
          retrieval_locator IS NOT NULL AND retrieval_source_key IS NOT NULL
          AND retrieval_projection_generation IS NOT NULL
          AND retrieval_sequence_ordinal IS NOT NULL AND retrieval_kind IS NOT NULL
          AND retrieval_category IS NOT NULL) NOT VALID""",
    ),
    "ck_memory_chunks_retrieval_ordinal_range": _ConstraintSpec(
        "memory_chunks",
        "c",
        False,
        ("retrieval_sequence_ordinal",),
        "CHECK (retrieval_sequence_ordinal IS NULL OR "
        "retrieval_sequence_ordinal >= 0 AND "
        "retrieval_sequence_ordinal <= 2147483647) NOT VALID",
    ),
    "ck_memory_chunks_retrieval_time_complete": _ConstraintSpec(
        "memory_chunks",
        "c",
        False,
        ("retrieval_start_at", "retrieval_end_at"),
        "CHECK ((retrieval_start_at IS NULL) = (retrieval_end_at IS NULL)) NOT VALID",
    ),
    "ck_memory_chunks_retrieval_time_ordered": _ConstraintSpec(
        "memory_chunks",
        "c",
        False,
        ("retrieval_start_at", "retrieval_end_at"),
        "CHECK (retrieval_start_at IS NULL OR retrieval_start_at <= retrieval_end_at) NOT VALID",
    ),
    "ck_memory_chunks_retrieval_relative_time_complete": _ConstraintSpec(
        "memory_chunks",
        "c",
        False,
        ("retrieval_relative_start_ms", "retrieval_relative_end_ms"),
        "CHECK ((retrieval_relative_start_ms IS NULL) = "
        "(retrieval_relative_end_ms IS NULL)) NOT VALID",
    ),
    "ck_memory_chunks_retrieval_relative_time_range": _ConstraintSpec(
        "memory_chunks",
        "c",
        False,
        ("retrieval_relative_start_ms", "retrieval_relative_end_ms"),
        """CHECK (retrieval_relative_start_ms IS NULL OR
        retrieval_relative_start_ms >= 0 AND
        retrieval_relative_start_ms <= '9007199254740991'::bigint AND
        retrieval_relative_end_ms >= retrieval_relative_start_ms AND
        retrieval_relative_end_ms <= '9007199254740991'::bigint) NOT VALID""",
    ),
    "memory_document_projection_receipts_pkey": _ConstraintSpec(
        "memory_document_projection_receipts",
        "p",
        True,
        ("space_id", "idempotency_key"),
        "PRIMARY KEY (space_id, idempotency_key)",
    ),
    "fk_document_projection_receipt_document": _ConstraintSpec(
        "memory_document_projection_receipts",
        "f",
        True,
        ("document_id",),
        "FOREIGN KEY (document_id) REFERENCES memory_documents(id)",
        "memory_documents",
    ),
    "ck_document_projection_receipt_fingerprint": _ConstraintSpec(
        "memory_document_projection_receipts",
        "c",
        True,
        ("request_fingerprint_sha256",),
        "CHECK (request_fingerprint_sha256 ~ '^[0-9a-f]{64}$'::text)",
    ),
}

_TRIGGERS: Final = {
    "trg_memory_chunk_retrieval_fence_v2": _TriggerSpec(
        "memory_chunks",
        "memory_chunk_retrieval_fence_v2",
        23,
        """CREATE TRIGGER trg_memory_chunk_retrieval_fence_v2
        BEFORE INSERT OR UPDATE ON public.memory_chunks FOR EACH ROW
        EXECUTE FUNCTION memory_chunk_retrieval_fence_v2()""",
    ),
    "trg_00_memory_chunk_require_locator_parent": _TriggerSpec(
        "memory_chunks",
        "memory_chunk_require_locator_parent_v1",
        23,
        """CREATE TRIGGER trg_00_memory_chunk_require_locator_parent
        BEFORE INSERT OR UPDATE ON public.memory_chunks FOR EACH ROW
        EXECUTE FUNCTION memory_chunk_require_locator_parent_v1()""",
    ),
    "trg_00_locator_runtime_parent_capability": _TriggerSpec(
        "memory_locator_runtime_incarnations",
        "memory_locator_require_parent_capability_v1",
        23,
        """CREATE TRIGGER trg_00_locator_runtime_parent_capability
        BEFORE INSERT OR UPDATE ON public.memory_locator_runtime_incarnations FOR EACH ROW
        EXECUTE FUNCTION memory_locator_require_parent_capability_v1()""",
    ),
    "trg_00_memory_chunks_benchmark_document_child_lock": _TriggerSpec(
        "memory_chunks",
        "memory_comparison_lock_benchmark_document_child_target",
        31,
        """CREATE TRIGGER trg_00_memory_chunks_benchmark_document_child_lock
        BEFORE INSERT OR DELETE OR UPDATE OF id, space_id, memory_scope_id, thread_id,
        document_id, episode_id, source_type, source_external_id, source_hash, kind, text,
        normalized_text, status, sequence, char_start, char_end, token_estimate,
        classification, created_at, updated_at, metadata_json, retrieval_locator,
        retrieval_source_key, retrieval_projection_generation, retrieval_sequence_ordinal,
        retrieval_kind, retrieval_version, retrieval_actor_keys_json, retrieval_start_at,
        retrieval_end_at, retrieval_relative_start_ms, retrieval_relative_end_ms,
        retrieval_category, retrieval_tags_json, retrieval_commit_watermark
        ON public.memory_chunks FOR EACH ROW EXECUTE FUNCTION
        memory_comparison_lock_benchmark_document_child_target()""",
    ),
    "trg_memory_chunks_benchmark_document_child_fence": _TriggerSpec(
        "memory_chunks",
        "memory_comparison_enforce_benchmark_document_child_fence",
        31,
        """CREATE TRIGGER trg_memory_chunks_benchmark_document_child_fence
        BEFORE INSERT OR DELETE OR UPDATE OF id, space_id, memory_scope_id, thread_id,
        document_id, episode_id, source_type, source_external_id, source_hash, kind, text,
        normalized_text, status, sequence, char_start, char_end, token_estimate,
        classification, created_at, updated_at, metadata_json, retrieval_locator,
        retrieval_source_key, retrieval_projection_generation, retrieval_sequence_ordinal,
        retrieval_kind, retrieval_version, retrieval_actor_keys_json, retrieval_start_at,
        retrieval_end_at, retrieval_relative_start_ms, retrieval_relative_end_ms,
        retrieval_category, retrieval_tags_json, retrieval_commit_watermark
        ON public.memory_chunks FOR EACH ROW EXECUTE FUNCTION
        memory_comparison_enforce_benchmark_document_child_fence()""",
    ),
    "trg_memory_chunk_locator_profile_events_v2": _TriggerSpec(
        "memory_chunks",
        "memory_chunk_locator_profile_events_v2",
        29,
        _trusted_trigger_definition(
            "trg_memory_chunk_locator_profile_events_v2", _TRUSTED_0040_SQL
        ),
    ),
    **{
        name: _TriggerSpec(
            "memory_documents",
            function,
            trigger_type,
            _trusted_trigger_definition(name, _TRUSTED_0059_SQL),
        )
        for name, function, trigger_type in (
            (
                "trg_00_document_locator_profile_evidence_insert",
                "memory_locator_profile_invalidate_evidence_v1",
                7,
            ),
            (
                "trg_00_document_locator_profile_evidence_update",
                "memory_locator_profile_invalidate_evidence_v1",
                19,
            ),
            (
                "trg_00_document_locator_profile_evidence_delete",
                "memory_locator_profile_invalidate_evidence_v1",
                11,
            ),
            (
                "trg_01_document_locator_parent_lock_insert",
                "memory_document_lock_locator_parent_v1",
                7,
            ),
            (
                "trg_01_document_locator_parent_lock_update",
                "memory_document_lock_locator_parent_v1",
                19,
            ),
            (
                "trg_01_document_locator_parent_lock_delete",
                "memory_document_lock_locator_parent_v1",
                11,
            ),
            (
                "trg_document_invalidate_locator_children_insert",
                "memory_document_invalidate_locator_children_v1",
                5,
            ),
            (
                "trg_document_invalidate_locator_children_update",
                "memory_document_invalidate_locator_children_v1",
                17,
            ),
            (
                "trg_document_invalidate_locator_children_delete",
                "memory_document_invalidate_locator_children_v1",
                9,
            ),
        )
    },
}


_COLUMN_CATALOG_SQL = """
SELECT namespace.nspname AS namespace, relation.relname AS table_name,
       attribute.attname AS column_name,
       pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) AS data_type,
       attribute.attnotnull AS not_null,
       pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid, true)
           AS default_expression,
       attribute.attidentity AS identity_kind,
       attribute.attgenerated AS generated_kind
FROM pg_catalog.pg_attribute AS attribute
JOIN pg_catalog.pg_class AS relation ON relation.oid=attribute.attrelid
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=relation.relnamespace
LEFT JOIN pg_catalog.pg_attrdef AS default_value
  ON default_value.adrelid=attribute.attrelid
 AND default_value.adnum=attribute.attnum
WHERE namespace.nspname='public'
  AND relation.relname=ANY(:tables)
  AND attribute.attname=ANY(:columns)
  AND attribute.attnum>0
  AND NOT attribute.attisdropped
"""

_TABLE_OWNER_SQL = """
SELECT relation.relname AS table_name, owner.rolname AS owner_name
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=relation.relnamespace
JOIN pg_catalog.pg_roles AS owner ON owner.oid=relation.relowner
WHERE namespace.nspname='public' AND relation.relname=ANY(:tables)
"""

_FUNCTION_CATALOG_SQL = """
SELECT procedure.proname AS object_name, namespace.nspname AS namespace,
       procedure.prokind AS function_kind, language.lanname AS language_name,
       pg_catalog.format_type(procedure.prorettype, NULL) AS return_type,
       pg_catalog.pg_get_function_identity_arguments(procedure.oid) AS identity_arguments,
       procedure.provolatile AS volatility,
       procedure.prosecdef AS security_definer,
       procedure.proconfig AS configuration,
       procedure.prosrc AS implementation,
       owner.rolname AS owner_name,
       ARRAY(
           SELECT CASE
                    WHEN acl.grantee=procedure.proowner THEN '<owner>'
                    WHEN acl.grantee=0 THEN 'PUBLIC'
                    ELSE grantee.rolname
                  END || ':' || acl.privilege_type || ':' ||
                  pg_catalog.lower(acl.is_grantable::pg_catalog.text)
           FROM pg_catalog.aclexplode(
               COALESCE(
                   procedure.proacl,
                   pg_catalog.acldefault('f', procedure.proowner)
               )
           ) AS acl
           LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid=acl.grantee
           ORDER BY 1
       ) AS effective_acl
FROM pg_catalog.pg_proc AS procedure
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=procedure.pronamespace
JOIN pg_catalog.pg_language AS language ON language.oid=procedure.prolang
JOIN pg_catalog.pg_roles AS owner ON owner.oid=procedure.proowner
WHERE namespace.nspname='public'
  AND procedure.proname=ANY(:names)
  AND procedure.pronargs=0
"""


_INDEX_CATALOG_SQL = """
SELECT ic.relname AS object_name, ins.nspname AS namespace,
       tc.relname AS table_name, tns.nspname AS table_namespace,
       ic.relkind AS relation_kind, am.amname AS access_method,
       i.indisunique AS is_unique, i.indisvalid AS is_valid,
       i.indisready AS is_ready, i.indislive AS is_live,
       EXISTS (SELECT 1 FROM pg_catalog.pg_constraint x WHERE x.conindid = ic.oid)
           AS constraint_owned,
       ARRAY(SELECT pg_catalog.pg_get_indexdef(ic.oid, position, true)
             FROM generate_series(1, i.indnkeyatts) AS position ORDER BY position) AS keys,
       ARRAY(SELECT opns.nspname || '.' || opc.opcname
             FROM unnest(i.indclass::oid[]) WITH ORDINALITY
                  AS key(opcoid, position)
             JOIN pg_catalog.pg_opclass opc ON opc.oid = key.opcoid
             JOIN pg_catalog.pg_namespace opns ON opns.oid = opc.opcnamespace
             WHERE key.position <= i.indnkeyatts ORDER BY key.position) AS opclasses,
       ARRAY(SELECT CASE WHEN key.colloid = 0 THEN NULL
                         ELSE cns.nspname || '.' || co.collname END
             FROM unnest(i.indcollation::oid[]) WITH ORDINALITY AS key(colloid, position)
             LEFT JOIN pg_catalog.pg_collation co ON co.oid = key.colloid
             LEFT JOIN pg_catalog.pg_namespace cns ON cns.oid = co.collnamespace
             WHERE key.position <= i.indnkeyatts ORDER BY key.position) AS collations,
       ARRAY(SELECT option_value FROM unnest(i.indoption::int2[]) WITH ORDINALITY
             AS key(option_value, position) WHERE position <= i.indnkeyatts
             ORDER BY position) AS options,
       i.indnkeyatts AS key_count, i.indnatts AS attribute_count,
       pg_catalog.pg_get_expr(i.indpred, i.indrelid, true) AS predicate
FROM pg_catalog.pg_class ic
JOIN pg_catalog.pg_namespace ins ON ins.oid = ic.relnamespace
LEFT JOIN pg_catalog.pg_index i ON i.indexrelid = ic.oid
LEFT JOIN pg_catalog.pg_class tc ON tc.oid = i.indrelid
LEFT JOIN pg_catalog.pg_namespace tns ON tns.oid = tc.relnamespace
LEFT JOIN pg_catalog.pg_am am ON am.oid = ic.relam
WHERE ins.nspname = 'public' AND ic.relname = ANY(:names)
"""

_CONSTRAINT_CATALOG_SQL = """
SELECT con.conname AS object_name, cns.nspname AS namespace,
       tc.relname AS table_name, tns.nspname AS table_namespace,
       con.contype AS constraint_type, con.convalidated AS validated,
       con.condeferrable AS deferrable, con.condeferred AS deferred,
       ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY AS key(attnum, position)
             JOIN pg_catalog.pg_attribute a ON a.attrelid = con.conrelid
                                             AND a.attnum = key.attnum
             ORDER BY key.position) AS columns,
       rtns.nspname AS referenced_namespace, rt.relname AS referenced_table,
       con.confupdtype AS foreign_update, con.confdeltype AS foreign_delete,
       con.confmatchtype AS foreign_match,
       pg_catalog.pg_get_constraintdef(con.oid, true) AS definition
FROM pg_catalog.pg_constraint con
JOIN pg_catalog.pg_namespace cns ON cns.oid = con.connamespace
JOIN pg_catalog.pg_class tc ON tc.oid = con.conrelid
JOIN pg_catalog.pg_namespace tns ON tns.oid = tc.relnamespace
LEFT JOIN pg_catalog.pg_class rt ON rt.oid = con.confrelid
LEFT JOIN pg_catalog.pg_namespace rtns ON rtns.oid = rt.relnamespace
WHERE cns.nspname = 'public' AND con.conname = ANY(:names)
"""

_TRIGGER_CATALOG_SQL = """
SELECT tr.tgname AS object_name, tns.nspname AS namespace,
       tc.relname AS table_name, tns.nspname AS table_namespace,
       pns.nspname AS function_namespace, p.proname AS function_name,
       tr.tgtype AS trigger_type, tr.tgenabled AS enabled,
       tr.tgisinternal AS internal, tr.tgargs AS arguments,
       pg_catalog.pg_get_triggerdef(tr.oid, true) AS definition
FROM pg_catalog.pg_trigger tr
JOIN pg_catalog.pg_class tc ON tc.oid = tr.tgrelid
JOIN pg_catalog.pg_namespace tns ON tns.oid = tc.relnamespace
JOIN pg_catalog.pg_proc p ON p.oid = tr.tgfoid
JOIN pg_catalog.pg_namespace pns ON pns.oid = p.pronamespace
WHERE tns.nspname = 'public' AND tr.tgname = ANY(:names)
"""
