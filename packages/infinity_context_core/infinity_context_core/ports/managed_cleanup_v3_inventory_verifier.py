"""Bounded streaming verification of future cleanup v3 inventory pages."""

from __future__ import annotations

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    commitment,
    merkle_root,
    profile_oracle,
)
from infinity_context_core.ports.managed_cleanup_v3_recovery import (
    INVENTORY_KINDS,
    INVENTORY_PAGE_SIZE,
    ManagedCleanupV3InventoryKindReceipt,
    ManagedCleanupV3InventoryPage,
    ManagedCleanupV3InventoryTerminal,
)


def _root(label: str, pages: list[str]) -> str:
    if not pages:
        return commitment(label, [])
    return merkle_root(tuple(pages))


class ManagedCleanupV3InventoryStreamVerifier:
    """Enforce one exact cursor chain across every kind in one snapshot."""

    __slots__ = (
        "_authority",
        "_cleanup",
        "_context",
        "_cursor_sha",
        "_finished",
        "_expected_counts",
        "_kind_index",
        "_last_key",
        "_page_index",
        "_receipts",
        "_row_count",
        "_row_pages",
        "_snapshot",
        "_target_roots",
    )

    def __init__(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        cleanup_receipt_sha256: str,
        snapshot_sha256: str,
    ) -> None:
        if type(context) is not ManagedCleanupV3Context:
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_verifier_invalid")
        context.__post_init__()
        from infinity_context_core.ports.managed_cleanup_v3_contracts import digest

        self._authority = digest(authority_terminal_sha256)
        self._cleanup = digest(cleanup_receipt_sha256)
        self._snapshot = digest(snapshot_sha256)
        self._context = context
        self._kind_index = 0
        oracle = profile_oracle(context.profile_id)
        facts = int(oracle["operation_count"]) if oracle["lane"] == "fact" else 0
        documents = int(oracle["operation_count"]) if oracle["lane"] == "document" else 0
        chunks = int(oracle["fragment_count"])
        self._expected_counts = (
            int(oracle["corpus_count"]),
            int(oracle["corpus_count"]),
            facts,
            facts,
            documents,
            chunks,
            chunks,
            facts,
            facts,
            chunks,
            chunks,
            facts,
            facts,
            chunks + facts,
            0,
        )
        self._page_index = 0
        self._cursor_sha: str | None = None
        self._last_key: str | None = None
        self._row_count = 0
        self._row_pages: list[str] = []
        self._receipts: list[ManagedCleanupV3InventoryKindReceipt] = []
        self._target_roots: dict[str, str] = {}
        self._finished = False

    def verify_page(self, page: ManagedCleanupV3InventoryPage) -> None:
        if self._finished or type(page) is not ManagedCleanupV3InventoryPage:
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_sequence_invalid")
        page.__post_init__()
        kind = INVENTORY_KINDS[self._kind_index]
        keys = page.ordered_canonical_key_sha256
        expected_count = self._expected_counts[self._kind_index]
        max_pages = max(1, (expected_count + INVENTORY_PAGE_SIZE - 1) // INVENTORY_PAGE_SIZE)
        next_count = self._row_count + len(keys)
        if (
            page.authority_terminal_sha256 != self._authority
            or page.snapshot_sha256 != self._snapshot
            or page.kind != kind
            or page.page_index != self._page_index
            or page.input_cursor_sha256 != self._cursor_sha
            or (self._last_key is not None and keys and keys[0] <= self._last_key)
            or self._page_index >= max_pages
            or next_count > expected_count
            or page.exhausted != (next_count == expected_count)
            or (not page.exhausted and len(keys) != INVENTORY_PAGE_SIZE)
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_sequence_invalid")
        self._row_pages.append(commitment("inventory-row-page/v3", list(page.ordered_row_sha256)))
        self._row_count += len(keys)
        self._last_key = keys[-1] if keys else self._last_key
        self._cursor_sha = None if page.output_cursor is None else page.output_cursor.cursor_sha256
        self._page_index += 1
        if page.exhausted:
            self._finish_kind(kind)

    def _finish_kind(self, kind: str) -> None:
        self._receipts.append(
            ManagedCleanupV3InventoryKindReceipt(
                kind=kind,
                row_count=self._row_count,
                page_count=self._page_index,
                ordered_rows_root_sha256=_root("inventory-empty-rows/v3", self._row_pages),
            )
        )
        if kind == "qdrant_target_identities":
            self._target_roots["qdrant"] = _root("inventory-empty-qdrant/v3", self._row_pages)
        if kind == "graphiti_target_names":
            self._target_roots["graphiti_name"] = _root(
                "inventory-empty-graphiti-name/v3", self._row_pages
            )
        if kind == "graphiti_target_uuids":
            self._target_roots["graphiti_uuid"] = _root(
                "inventory-empty-graphiti-uuid/v3", self._row_pages
            )
        self._kind_index += 1
        self._page_index = self._row_count = 0
        self._cursor_sha = self._last_key = None
        self._row_pages = []
        self._finished = self._kind_index == len(INVENTORY_KINDS)

    def finalize(
        self, terminal: ManagedCleanupV3InventoryTerminal
    ) -> ManagedCleanupV3InventoryTerminal:
        if not self._finished or type(terminal) is not ManagedCleanupV3InventoryTerminal:
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_coverage_incomplete")
        terminal.__post_init__()
        qdrant = self._target_roots.get("qdrant", commitment("inventory-empty-qdrant/v3", []))
        graphiti_name = self._target_roots.get(
            "graphiti_name", commitment("inventory-empty-graphiti-name/v3", [])
        )
        graphiti_uuid = self._target_roots.get(
            "graphiti_uuid", commitment("inventory-empty-graphiti-uuid/v3", [])
        )
        if (
            terminal.profile_id != self._context.profile_id
            or terminal.context_sha256 != self._context.context_sha256
            or terminal.authority_terminal_sha256 != self._authority
            or terminal.cleanup_receipt_sha256 != self._cleanup
            or terminal.snapshot_sha256 != self._snapshot
            or terminal.kind_receipts != tuple(self._receipts)
            or terminal.expected_qdrant_identity_root_sha256 != qdrant
            or terminal.expected_graphiti_name_root_sha256 != graphiti_name
            or terminal.expected_graphiti_uuid_root_sha256 != graphiti_uuid
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_terminal_invalid")
        return terminal


__all__ = ("ManagedCleanupV3InventoryStreamVerifier",)
