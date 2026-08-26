"""Exact PostgreSQL catalog attestation for the Retrieval canonical schema."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from sqlalchemy import text


@dataclass(frozen=True, slots=True)
class CatalogMismatch:
    object_kind: str
    object_name: str
    property_name: str
    expected: object
    observed: object


@dataclass(frozen=True, slots=True)
class LocatorCatalogAttestation:
    mismatches: tuple[CatalogMismatch, ...]

    @property
    def qualified(self) -> bool:
        return not self.mismatches

    def require_qualified(self) -> None:
        if self.mismatches:
            mismatch = self.mismatches[0]
            raise RuntimeError(
                "Retrieval PostgreSQL catalog is not exact: "
                f"{mismatch.object_kind} {mismatch.object_name} "
                f"has mismatched {mismatch.property_name}"
            )


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


_SCHEMA: Final = "public"
LOCATOR_CATALOG_MAINTENANCE_LOCK_ID: Final = 4_916_625_310_112_023_309
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
}


async def attest_locator_retrieval_catalog(connection) -> LocatorCatalogAttestation:
    """Compare every safety-bearing Retrieval object with its exact catalog shape."""

    mismatches: list[CatalogMismatch] = []
    index_rows = {
        row["object_name"]: row
        for row in (
            await connection.execute(text(_INDEX_CATALOG_SQL), {"names": list(_INDEXES)})
        ).mappings()
    }
    collations = await _column_collations(connection)
    for name, spec in _INDEXES.items():
        row = index_rows.get(name)
        if row is None:
            _missing(mismatches, "index", name)
            continue
        expected = {
            "namespace": _SCHEMA,
            "table_namespace": _SCHEMA,
            "table": spec.table,
            "relation_kind": "i",
            "access_method": "btree",
            "unique": spec.unique,
            "valid": True,
            "ready": True,
            "live": True,
            "constraint_owned": False,
            "keys": tuple(_normalize_sql(value) for value in spec.keys),
            "opclasses": spec.opclasses,
            "collations": tuple(
                collations.get((spec.table, column)) if column else None
                for column in spec.collation_columns
            ),
            "options": (0,) * len(spec.keys),
            "key_count": len(spec.keys),
            "attribute_count": len(spec.keys),
            "predicate": _definition_signature(spec.predicate),
        }
        observed = {
            "namespace": row["namespace"],
            "table_namespace": row["table_namespace"],
            "table": row["table_name"],
            "relation_kind": _catalog_char(row["relation_kind"]),
            "access_method": row["access_method"],
            "unique": row["is_unique"],
            "valid": row["is_valid"],
            "ready": row["is_ready"],
            "live": row["is_live"],
            "constraint_owned": row["constraint_owned"],
            "keys": tuple(_normalize_sql(value) for value in row["keys"] or ()),
            "opclasses": tuple(row["opclasses"] or ()),
            "collations": tuple(row["collations"] or ()),
            "options": tuple(row["options"] or ()),
            "key_count": row["key_count"],
            "attribute_count": row["attribute_count"],
            "predicate": _definition_signature(row["predicate"] or ""),
        }
        _compare(mismatches, "index", name, expected, observed)

    constraint_rows = {
        row["object_name"]: row
        for row in (
            await connection.execute(text(_CONSTRAINT_CATALOG_SQL), {"names": list(_CONSTRAINTS)})
        ).mappings()
    }
    for name, spec in _CONSTRAINTS.items():
        row = constraint_rows.get(name)
        if row is None:
            _missing(mismatches, "constraint", name)
            continue
        expected = {
            "namespace": _SCHEMA,
            "table_namespace": _SCHEMA,
            "table": spec.table,
            "type": spec.constraint_type,
            "validated": spec.validated,
            "deferrable": False,
            "deferred": False,
            "columns": spec.columns,
            "referenced_namespace": _SCHEMA if spec.referenced_table else None,
            "referenced_table": spec.referenced_table,
            "definition": _definition_signature(spec.definition),
        }
        observed = {
            "namespace": row["namespace"],
            "table_namespace": row["table_namespace"],
            "table": row["table_name"],
            "type": _catalog_char(row["constraint_type"]),
            "validated": row["validated"],
            "deferrable": row["deferrable"],
            "deferred": row["deferred"],
            "columns": tuple(row["columns"] or ()),
            "referenced_namespace": row["referenced_namespace"],
            "referenced_table": row["referenced_table"],
            "definition": _definition_signature(row["definition"] or ""),
        }
        if spec.constraint_type == "f":
            expected.update(foreign_update="a", foreign_delete="a", foreign_match="s")
            observed.update(
                foreign_update=_catalog_char(row["foreign_update"]),
                foreign_delete=_catalog_char(row["foreign_delete"]),
                foreign_match=_catalog_char(row["foreign_match"]),
            )
        _compare(mismatches, "constraint", name, expected, observed)

    trigger_rows = {
        row["object_name"]: row
        for row in (
            await connection.execute(text(_TRIGGER_CATALOG_SQL), {"names": list(_TRIGGERS)})
        ).mappings()
    }
    for name, spec in _TRIGGERS.items():
        row = trigger_rows.get(name)
        if row is None:
            _missing(mismatches, "trigger", name)
            continue
        expected = {
            "namespace": _SCHEMA,
            "table_namespace": _SCHEMA,
            "table": spec.table,
            "function_namespace": _SCHEMA,
            "function": spec.function,
            "type": spec.trigger_type,
            "enabled": "O",
            "internal": False,
            "arguments": b"",
            "definition": _trigger_signature(spec.definition),
        }
        observed = {
            "namespace": row["namespace"],
            "table_namespace": row["table_namespace"],
            "table": row["table_name"],
            "function_namespace": row["function_namespace"],
            "function": row["function_name"],
            "type": row["trigger_type"],
            "enabled": _catalog_char(row["enabled"]),
            "internal": row["internal"],
            "arguments": row["arguments"],
            "definition": _trigger_signature(row["definition"] or ""),
        }
        _compare(mismatches, "trigger", name, expected, observed)
    return LocatorCatalogAttestation(tuple(mismatches))


async def lock_and_attest_locator_retrieval_catalog(connection) -> None:
    """Fence schema DDL for a projected write and fail closed on catalog drift."""

    await connection.execute(
        text(f"SELECT pg_advisory_xact_lock_shared({LOCATOR_CATALOG_MAINTENANCE_LOCK_ID})")
    )
    await connection.execute(
        text(
            "LOCK TABLE public.memory_chunks, "
            "public.memory_document_projection_receipts IN ROW EXCLUSIVE MODE"
        )
    )
    (await attest_locator_retrieval_catalog(connection)).require_qualified()


async def _column_collations(connection) -> dict[tuple[str, str], str | None]:
    rows = (
        await connection.execute(
            text(
                """SELECT c.relname AS table_name, a.attname AS column_name,
                CASE WHEN a.attcollation = 0 THEN NULL
                     ELSE cn.nspname || '.' || co.collname END AS collation
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
                LEFT JOIN pg_catalog.pg_collation co ON co.oid = a.attcollation
                LEFT JOIN pg_catalog.pg_namespace cn ON cn.oid = co.collnamespace
                WHERE n.nspname = :schema AND c.relname = ANY(:tables)
                  AND a.attnum > 0 AND NOT a.attisdropped"""
            ),
            {"schema": _SCHEMA, "tables": sorted({spec.table for spec in _INDEXES.values()})},
        )
    ).mappings()
    return {(row["table_name"], row["column_name"]): row["collation"] for row in rows}


def _compare(mismatches, kind, name, expected, observed) -> None:
    for property_name, expected_value in expected.items():
        observed_value = observed[property_name]
        if observed_value != expected_value:
            mismatches.append(
                CatalogMismatch(kind, name, property_name, expected_value, observed_value)
            )


def _missing(mismatches, kind: str, name: str) -> None:
    mismatches.append(CatalogMismatch(kind, name, "presence", True, False))


def _catalog_char(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii")
    return value


def _normalize_sql(value: str) -> str:
    value = value.strip().lower().replace("execute procedure", "execute function")
    value = re.sub(r'"([a-z_][a-z0-9_]*)"', r"\1", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*([(),])\s*", r"\1", value)
    value = re.sub(r"\(([^(),]+)\)::", r"\1::", value)
    return value


def _definition_signature(value: str) -> str:
    """Normalize formatting while preserving the complete deparsed definition."""

    return _normalize_sql(value)


def _trigger_signature(value: str) -> str:
    return _normalize_sql(value).replace("public.", "")


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


__all__ = (
    "CatalogMismatch",
    "LOCATOR_CATALOG_MAINTENANCE_LOCK_ID",
    "LocatorCatalogAttestation",
    "attest_locator_retrieval_catalog",
    "lock_and_attest_locator_retrieval_catalog",
)
