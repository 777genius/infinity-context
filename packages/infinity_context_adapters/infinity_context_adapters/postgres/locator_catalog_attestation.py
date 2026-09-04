"""Exact PostgreSQL catalog attestation for the Retrieval canonical schema."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from sqlalchemy import text

from infinity_context_adapters.postgres.locator_catalog_specification import (
    _COLUMN_CATALOG_SQL,
    _COLUMNS,
    _CONSTRAINT_CATALOG_SQL,
    _CONSTRAINTS,
    _FUNCTION_CATALOG_SQL,
    _FUNCTIONS,
    _INDEX_CATALOG_SQL,
    _INDEXES,
    _SAFE_SEARCH_PATH,
    _SCHEMA,
    _TABLE_OWNER_SQL,
    _TRIGGER_CATALOG_SQL,
    _TRIGGERS,
)


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


LOCATOR_CATALOG_MAINTENANCE_LOCK_ID: Final = 4_916_625_310_112_023_309


async def attest_locator_retrieval_catalog(connection) -> LocatorCatalogAttestation:
    """Compare every safety-bearing Retrieval object with its exact catalog shape."""

    mismatches: list[CatalogMismatch] = []
    column_rows = {
        f"{row['table_name']}.{row['column_name']}": row
        for row in (
            await connection.execute(
                text(_COLUMN_CATALOG_SQL),
                {
                    "tables": sorted({spec.table for spec in _COLUMNS.values()}),
                    "columns": sorted(name.rsplit(".", 1)[1] for name in _COLUMNS),
                },
            )
        ).mappings()
    }
    for name, spec in _COLUMNS.items():
        row = column_rows.get(name)
        if row is None:
            _missing(mismatches, "column", name)
            continue
        expected = {
            "namespace": _SCHEMA,
            "table": spec.table,
            "type": spec.data_type,
            "nullable": spec.nullable,
            "default": _definition_signature(spec.default),
            "identity": "",
            "generated": "",
        }
        observed = {
            "namespace": row["namespace"],
            "table": row["table_name"],
            "type": row["data_type"],
            "nullable": not row["not_null"],
            "default": _definition_signature(row["default_expression"] or ""),
            "identity": _catalog_char(row["identity_kind"]),
            "generated": _catalog_char(row["generated_kind"]),
        }
        _compare(mismatches, "column", name, expected, observed)

    owner_rows = (
        await connection.execute(
            text(_TABLE_OWNER_SQL),
            {"tables": sorted({spec.owner_table for spec in _FUNCTIONS.values()})},
        )
    ).mappings()
    table_owners = {row["table_name"]: row["owner_name"] for row in owner_rows}
    function_rows = {
        row["object_name"]: row
        for row in (
            await connection.execute(
                text(_FUNCTION_CATALOG_SQL),
                {"names": list(_FUNCTIONS)},
            )
        ).mappings()
    }
    for name, spec in _FUNCTIONS.items():
        row = function_rows.get(name)
        if row is None:
            _missing(mismatches, "function", name)
            continue
        expected_acl = ("<owner>:EXECUTE:false",)
        if spec.public_execute:
            expected_acl += ("PUBLIC:EXECUTE:false",)
        expected = {
            "namespace": _SCHEMA,
            "kind": "f",
            "language": "plpgsql",
            "return_type": "trigger",
            "identity_arguments": "",
            "volatility": "v",
            "security_definer": spec.security_definer,
            "search_path": _SAFE_SEARCH_PATH,
            "implementation": spec.body,
            "owner_matches_table": True,
            "effective_acl": tuple(sorted(expected_acl)),
        }
        observed = {
            "namespace": row["namespace"],
            "kind": _catalog_char(row["function_kind"]),
            "language": row["language_name"],
            "return_type": row["return_type"],
            "identity_arguments": row["identity_arguments"],
            "volatility": _catalog_char(row["volatility"]),
            "security_definer": row["security_definer"],
            "search_path": tuple(row["configuration"] or ()),
            "implementation": row["implementation"],
            "owner_matches_table": row["owner_name"] == table_owners.get(spec.owner_table),
            "effective_acl": tuple(row["effective_acl"] or ()),
        }
        _compare(mismatches, "function", name, expected, observed)

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
            "LOCK TABLE public.memory_documents, public.memory_chunks, "
            "public.memory_locator_runtime_incarnations, "
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
        value = value.decode("ascii")
    # PostgreSQL's internal single-byte "char" represents its empty value as
    # a NUL byte.  asyncpg exposes that value as either bytes or a one-character
    # string depending on the result path, while the catalog meaning is "".
    return "" if value == "\x00" else value


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


__all__ = (
    "CatalogMismatch",
    "LOCATOR_CATALOG_MAINTENANCE_LOCK_ID",
    "LocatorCatalogAttestation",
    "attest_locator_retrieval_catalog",
    "lock_and_attest_locator_retrieval_catalog",
)
