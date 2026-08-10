"""Authenticated async PostgreSQL inventory for managed cleanup v3.

The boundary is deliberately async and does not claim the core sync Protocol.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    commitment,
    digest,
)
from infinity_context_core.ports.managed_cleanup_v3_inventory_verifier import (
    ManagedCleanupV3InventoryStreamVerifier,
)
from infinity_context_core.ports.managed_cleanup_v3_recovery import (
    INVENTORY_KINDS,
    INVENTORY_PAGE_SIZE,
    ManagedCleanupV3InventoryCursor,
    ManagedCleanupV3InventoryKindReceipt,
    ManagedCleanupV3InventoryPage,
    ManagedCleanupV3InventoryTerminal,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_inventory_codec import (
    InventorySummary,
    authenticate_rows,
    authenticate_summaries,
    build_core_cursor,
    build_core_page,
    inventory_mac,
    page_root,
)

SUMMARY_SQL: Final = """
SELECT kind, expected_count, ordered_rows_root_sha256, row_mac_sha256
FROM memory_cleanup_inventory_materializations
WHERE run_id_sha256 = $1 AND context_sha256 = $2
  AND cleanup_receipt_sha256 = $3 AND authority_terminal_sha256 = $4
  AND complete IS TRUE
ORDER BY kind
"""
PAGE_SQL: Final = """
SELECT canonical_key_sha256, locator_json, locator_sha256, row_sha256, row_mac_sha256
FROM memory_cleanup_inventory_keys
WHERE run_id_sha256 = $1 AND context_sha256 = $2
  AND cleanup_receipt_sha256 = $3 AND kind = $4
  AND canonical_key_sha256 > $5
ORDER BY canonical_key_sha256
LIMIT $6
"""


@dataclass(frozen=True, slots=True)
class ManagedCleanupV3AsyncInventoryCursor:
    core: ManagedCleanupV3InventoryCursor
    session_nonce: str
    context_sha256: str
    authority_terminal_sha256: str
    cleanup_receipt_sha256: str
    cursor_mac_sha256: str


@dataclass(frozen=True, slots=True)
class ManagedCleanupV3AsyncInventoryPage:
    core: ManagedCleanupV3InventoryPage
    output_cursor: ManagedCleanupV3AsyncInventoryCursor | None


class AsyncPostgresManagedCleanupV3Inventory:
    """Create one-connection, read-only inventory snapshots."""

    def __init__(
        self,
        *,
        connect: Callable[[], Awaitable[Any]],
        hmac_key: bytes,
        statement_timeout_ms: int = 30_000,
        idle_timeout_ms: int = 30_000,
    ) -> None:
        if type(hmac_key) is not bytes or len(hmac_key) < 32:
            raise ValueError("inventory HMAC key must contain at least 32 bytes")
        if (
            type(statement_timeout_ms) is not int
            or statement_timeout_ms <= 0
            or type(idle_timeout_ms) is not int
            or idle_timeout_ms <= 0
        ):
            raise ValueError("inventory timeouts must be positive integers")
        self._connect = connect
        self._key = bytes(hmac_key)
        self._statement_timeout = statement_timeout_ms
        self._idle_timeout = idle_timeout_ms

    async def begin_repeatable_read(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        cleanup_receipt_sha256: str,
    ) -> AsyncPostgresManagedCleanupV3Snapshot:
        context.__post_init__()
        authority = digest(authority_terminal_sha256)
        cleanup = digest(cleanup_receipt_sha256)
        connection = await self._connect()
        transaction = connection.transaction(isolation="repeatable_read", readonly=True)
        try:
            await transaction.start()
            await connection.execute(
                "SELECT set_config('statement_timeout', $1, true), "
                "set_config('idle_in_transaction_session_timeout', $2, true)",
                f"{self._statement_timeout}ms",
                f"{self._idle_timeout}ms",
            )
            pg_snapshot, tx_snapshot = await connection.fetchrow(
                "SELECT pg_export_snapshot(), txid_current_snapshot()::text"
            )
            rows = await connection.fetch(
                SUMMARY_SQL,
                context.run_id_sha256,
                context.context_sha256,
                cleanup,
                authority,
            )
            summaries = authenticate_summaries(
                rows,
                self._key,
                context.run_id_sha256,
                context.context_sha256,
                cleanup,
                authority,
            )
            nonce = secrets.token_hex(32)
            snapshot = commitment(
                "postgres-inventory-snapshot/v4",
                {
                    "session_nonce": nonce,
                    "pg_export_snapshot": pg_snapshot,
                    "txid_snapshot": tx_snapshot,
                    "context_sha256": context.context_sha256,
                    "authority_terminal_sha256": authority,
                    "cleanup_receipt_sha256": cleanup,
                    "summary_roots": [value.root for value in summaries],
                },
            )
            return AsyncPostgresManagedCleanupV3Snapshot(
                connection,
                transaction,
                self._key,
                context,
                authority,
                cleanup,
                snapshot,
                nonce,
                summaries,
            )
        except BaseException:
            await _rollback_close(connection, transaction)
            raise


class AsyncPostgresManagedCleanupV3Snapshot:
    """A session-local cursor chain over one physical RR/RO connection."""

    def __init__(
        self,
        connection: Any,
        transaction: Any,
        key: bytes,
        context: ManagedCleanupV3Context,
        authority: str,
        cleanup: str,
        snapshot: str,
        nonce: str,
        summaries: tuple[InventorySummary, ...],
    ) -> None:
        self._connection, self._transaction = connection, transaction
        self._key, self._context = key, context
        self._authority, self._cleanup = authority, cleanup
        self._snapshot, self._nonce = snapshot, nonce
        self._summaries = summaries
        self._kind_index = self._page_index = self._consumed = 0
        self._issued: str | None = None
        self._page_roots: list[str] = []
        self._receipts: list[ManagedCleanupV3InventoryKindReceipt] = []
        self._targets: dict[str, str] = {}
        self._closed = False
        self._verifier = ManagedCleanupV3InventoryStreamVerifier(
            context=context,
            authority_terminal_sha256=authority,
            cleanup_receipt_sha256=cleanup,
            snapshot_sha256=snapshot,
        )

    @property
    def snapshot_sha256(self) -> str:
        return self._snapshot

    async def first(self, *, kind: str, limit: int) -> ManagedCleanupV3AsyncInventoryPage:
        if (
            self._closed
            or self._kind_index >= len(INVENTORY_KINDS)
            or kind != INVENTORY_KINDS[self._kind_index]
            or limit != INVENTORY_PAGE_SIZE
            or self._page_index != 0
            or self._issued is not None
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_sequence_invalid")
        return await self._read(kind, None, None)

    async def next(
        self,
        cursor: ManagedCleanupV3AsyncInventoryCursor,
        *,
        limit: int,
    ) -> ManagedCleanupV3AsyncInventoryPage:
        if (
            self._closed
            or type(cursor) is not ManagedCleanupV3AsyncInventoryCursor
            or limit != INVENTORY_PAGE_SIZE
            or self._issued is None
            or cursor.core.cursor_sha256 != self._issued
            or cursor.session_nonce != self._nonce
            or cursor.context_sha256 != self._context.context_sha256
            or cursor.authority_terminal_sha256 != self._authority
            or cursor.cleanup_receipt_sha256 != self._cleanup
            or not hmac.compare_digest(cursor.cursor_mac_sha256, self._cursor_mac(cursor.core))
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_cursor_invalid")
        self._issued = None
        return await self._read(
            cursor.core.kind,
            cursor.core.last_canonical_key_sha256,
            cursor.core.cursor_sha256,
        )

    async def _read(
        self,
        kind: str,
        last_key: str | None,
        input_cursor: str | None,
    ) -> ManagedCleanupV3AsyncInventoryPage:
        summary = self._summaries[self._kind_index]
        remaining = summary.count - self._consumed
        page_capacity = min(remaining, INVENTORY_PAGE_SIZE)
        try:
            rows = await self._connection.fetch(
                PAGE_SQL,
                self._context.run_id_sha256,
                self._context.context_sha256,
                self._cleanup,
                kind,
                last_key or "0" * 64,
                page_capacity + 1,
            )
            if len(rows) > page_capacity:
                if remaining <= INVENTORY_PAGE_SIZE or len(rows) != page_capacity + 1:
                    raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_page_invalid")
                rows = rows[:page_capacity]
            keys, row_hashes = authenticate_rows(
                rows,
                self._key,
                self._context.run_id_sha256,
                self._context.context_sha256,
                self._cleanup,
                kind,
                last_key,
            )
            exhausted = self._consumed + len(keys) == summary.count
            output = (
                None
                if exhausted
                else build_core_cursor(self._snapshot, kind, keys[-1], self._page_index + 1)
            )
            page = build_core_page(
                self._authority,
                self._snapshot,
                kind,
                self._page_index,
                input_cursor,
                output,
                keys,
                row_hashes,
                exhausted,
            )
            self._verifier.verify_page(page)
            self._page_roots.append(commitment("inventory-row-page/v4", list(row_hashes)))
            self._consumed += len(keys)
            self._page_index += 1
            wrapped = None if output is None else self._wrap(output)
            self._issued = None if wrapped is None else output.cursor_sha256
            if exhausted:
                self._finish_kind(summary)
            return ManagedCleanupV3AsyncInventoryPage(page, wrapped)
        except BaseException:
            await self.abort()
            raise

    def _finish_kind(self, summary: InventorySummary) -> None:
        root = page_root("inventory-empty-rows/v4", self._page_roots)
        if root != summary.root:
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_page_invalid")
        self._receipts.append(
            ManagedCleanupV3InventoryKindReceipt(
                summary.kind,
                summary.count,
                self._page_index,
                root,
            )
        )
        target_labels = {
            "qdrant_target_identities": ("qdrant", "inventory-empty-qdrant/v4"),
            "graphiti_target_names": ("graphiti_name", "inventory-empty-graphiti-name/v4"),
            "graphiti_target_uuids": ("graphiti_uuid", "inventory-empty-graphiti-uuid/v4"),
        }
        if summary.kind in target_labels:
            name, label = target_labels[summary.kind]
            self._targets[name] = page_root(label, self._page_roots)
        self._kind_index += 1
        self._page_index = self._consumed = 0
        self._page_roots = []

    async def finalize(self) -> ManagedCleanupV3InventoryTerminal:
        if self._closed or self._kind_index != len(INVENTORY_KINDS) or self._issued is not None:
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_coverage_incomplete")
        terminal = _terminal(self)
        self._verifier.finalize(terminal)
        try:
            await self._transaction.commit()
        finally:
            await self._connection.close()
            self._closed = True
        return terminal

    async def abort(self) -> None:
        if not self._closed:
            await _rollback_close(self._connection, self._transaction)
            self._closed = True

    def _wrap(self, core: ManagedCleanupV3InventoryCursor) -> ManagedCleanupV3AsyncInventoryCursor:
        return ManagedCleanupV3AsyncInventoryCursor(
            core,
            self._nonce,
            self._context.context_sha256,
            self._authority,
            self._cleanup,
            self._cursor_mac(core),
        )

    def _cursor_mac(self, core: ManagedCleanupV3InventoryCursor) -> str:
        return inventory_mac(
            self._key,
            "managed-cleanup-v4/inventory-cursor",
            {
                "snapshot_sha256": self._snapshot,
                "session_nonce": self._nonce,
                "context_sha256": self._context.context_sha256,
                "authority_terminal_sha256": self._authority,
                "cleanup_receipt_sha256": self._cleanup,
                "kind": core.kind,
                "page_index": core.page_index,
                "last_canonical_key_sha256": core.last_canonical_key_sha256,
            },
        )


def _terminal(snapshot: AsyncPostgresManagedCleanupV3Snapshot) -> ManagedCleanupV3InventoryTerminal:
    qdrant = snapshot._targets["qdrant"]
    graphiti_name = snapshot._targets["graphiti_name"]
    graphiti_uuid = snapshot._targets["graphiti_uuid"]
    payload = {
        "schema_version": "memory-comparison-paged-cleanup-inventory-terminal.v4",
        "profile_id": snapshot._context.profile_id,
        "context_sha256": snapshot._context.context_sha256,
        "authority_terminal_sha256": snapshot._authority,
        "cleanup_receipt_sha256": snapshot._cleanup,
        "snapshot_sha256": snapshot._snapshot,
        "repeatable_read": True,
        "first_page_minimum_proven": True,
        "kind_receipts": [
            {name: getattr(receipt, name) for name in receipt.__dataclass_fields__}
            for receipt in snapshot._receipts
        ],
        "expected_qdrant_identity_root_sha256": qdrant,
        "expected_qdrant_identity_count": snapshot._summaries[6].count,
        "expected_graphiti_name_root_sha256": graphiti_name,
        "expected_graphiti_uuid_root_sha256": graphiti_uuid,
        "expected_graphiti_identity_count": snapshot._summaries[7].count,
    }
    return ManagedCleanupV3InventoryTerminal(
        snapshot._context.profile_id,
        snapshot._context.context_sha256,
        snapshot._authority,
        snapshot._cleanup,
        snapshot._snapshot,
        True,
        True,
        tuple(snapshot._receipts),
        qdrant,
        snapshot._summaries[6].count,
        graphiti_name,
        graphiti_uuid,
        snapshot._summaries[7].count,
        commitment("inventory-terminal/v4", payload),
    )


async def _rollback_close(connection: Any, transaction: Any) -> None:
    try:
        await transaction.rollback()
    finally:
        await connection.close()


__all__ = (
    "AsyncPostgresManagedCleanupV3Inventory",
    "AsyncPostgresManagedCleanupV3Snapshot",
    "ManagedCleanupV3AsyncInventoryCursor",
    "ManagedCleanupV3AsyncInventoryPage",
    "PAGE_SQL",
    "SUMMARY_SQL",
    "inventory_mac",
)
