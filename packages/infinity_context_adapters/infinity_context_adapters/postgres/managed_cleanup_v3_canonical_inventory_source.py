"""Canonical Postgres source rows for managed cleanup v3 inventory."""

from __future__ import annotations

from typing import Any

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
)
from infinity_context_core.ports.managed_cleanup_v3_recovery import (
    INVENTORY_KINDS,
    INVENTORY_PAGE_SIZE,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_canonical_inventory_sql import (
    IDENTITY_KIND,
    IDENTITY_SQL,
    JOB_KIND,
    JOB_SQL,
    SIMPLE_QUERIES,
    canonical_evidence,
    cleanup_receipts_sql,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_exhaustive_sql import UNSUPPORTED_SQL
from infinity_context_adapters.postgres.managed_cleanup_v3_inventory_materializer import (
    InventorySourcePage,
    InventorySourceRow,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_json import strict_json_object

_json_object = strict_json_object


class AsyncPostgresManagedCleanupV3CanonicalInventorySource:
    """Read bounded keyset pages from canonical rows and authenticated receipts."""

    async def read_page(
        self,
        connection: Any,
        *,
        context: ManagedCleanupV3Context,
        kind: str,
        after: object | None,
        limit: int,
        expected: int | None = None,
    ) -> InventorySourcePage:
        context.__post_init__()
        _validate_request(kind=kind, after=after, limit=limit, expected=expected)
        fetch_limit = limit
        if query := SIMPLE_QUERIES.get(kind):
            cursor = _cursor(after, query.cursor_types)
            rows = await connection.fetch(
                query.sql,
                context.space_id,
                None if cursor is None else cursor[0],
                fetch_limit,
            )
        elif identity := IDENTITY_KIND.get(kind):
            identity_kind, canonical_table = identity
            canonical_row_json, canonical_authority_joins = canonical_evidence(canonical_table)
            cursor = _cursor(after, (str, str))
            rows = await connection.fetch(
                IDENTITY_SQL.format(
                    canonical_table=canonical_table,
                    canonical_row_json=canonical_row_json,
                    canonical_authority_joins=canonical_authority_joins,
                ),
                context.run_id_sha256,
                context.context_sha256,
                context.space_id,
                "qdrant" if kind == "qdrant_target_identities" else "graphiti",
                identity_kind,
                ["vector.upsert_chunk", "vector.upsert_chunks"]
                if kind == "qdrant_target_identities"
                else ["graph.upsert_fact"],
                "chunk" if kind == "qdrant_target_identities" else "fact",
                None if cursor is None else cursor[0],
                None if cursor is None else cursor[1],
                fetch_limit,
            )
        elif job := JOB_KIND.get(kind):
            lane, operation, identity_kind, canonical_table, event_types, aggregate_type = job
            canonical_row_json, canonical_authority_joins = canonical_evidence(canonical_table)
            cursor = _cursor(after, (int, str))
            rows = await connection.fetch(
                JOB_SQL.format(
                    canonical_table=canonical_table,
                    canonical_row_json=canonical_row_json,
                    canonical_authority_joins=canonical_authority_joins,
                ),
                context.run_id_sha256,
                context.context_sha256,
                context.space_id,
                lane,
                operation,
                identity_kind,
                list(event_types),
                aggregate_type,
                None if cursor is None else cursor[0],
                None if cursor is None else cursor[1],
                fetch_limit,
            )
        elif kind == "cleanup_outbox_receipts":
            cursor = _cursor(after, (int, str))
            rows = await connection.fetch(
                cleanup_receipts_sql(),
                context.run_id_sha256,
                context.context_sha256,
                context.space_id,
                None if cursor is None else cursor[0],
                None if cursor is None else cursor[1],
                fetch_limit,
            )
        else:
            cursor = _cursor(after, (str, str))
            rows = await connection.fetch(
                UNSUPPORTED_SQL,
                context.space_id,
                context.run_id_sha256,
                context.context_sha256,
                None if cursor is None else cursor[0],
                None if cursor is None else cursor[1],
                fetch_limit,
            )
        if any(int(row.get("source_proof_count", 1)) != 1 for row in rows):
            raise ManagedCleanupV3Error(
                "managed_cleanup_v3_inventory_source_identity_proof_ambiguous"
            )
        exhausted = len(rows) < limit
        visible = rows
        return InventorySourcePage(
            tuple(
                InventorySourceRow(
                    locator_json=strict_json_object(
                        row["locator_json"],
                        "managed_cleanup_v3_inventory_source_locator_json_invalid",
                    ),
                    row_json=strict_json_object(
                        row["row_json"],
                        "managed_cleanup_v3_inventory_source_row_json_invalid",
                    ),
                    source_cursor=_row_cursor(row, 1 if kind in SIMPLE_QUERIES else 2),
                )
                for row in visible
            ),
            exhausted,
        )


def _validate_request(*, kind: str, after: object | None, limit: int, expected: int | None) -> None:
    if kind not in INVENTORY_KINDS:
        raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_source_kind_invalid")
    if type(limit) is not int or not 1 <= limit <= INVENTORY_PAGE_SIZE:
        raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_source_limit_invalid")
    if expected is not None and (type(expected) is not int or expected < 0):
        raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_source_expected_invalid")


def _cursor(value: object | None, types: tuple[type, ...]) -> tuple[object, ...] | None:
    if value is None:
        return None
    values = value if type(value) is tuple else (value,)
    if len(values) != len(types) or any(
        type(item) is not expected for item, expected in zip(values, types, strict=True)
    ):
        raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_source_cursor_invalid")
    return values


def _row_cursor(row: Any, width: int) -> object:
    values = tuple(row[f"cursor_{index}"] for index in range(1, width + 1))
    return values[0] if width == 1 else values


__all__ = ("AsyncPostgresManagedCleanupV3CanonicalInventorySource",)
