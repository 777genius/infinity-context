"""Paged inventory and two-pass absence contracts for future cleanup v3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol, final

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Error,
    commitment,
    digest,
    exact_int,
    profile_oracle,
)

INVENTORY_PAGE_SIZE: Final = 512
INVENTORY_CURSOR_SCHEMA: Final = "memory-comparison-paged-cleanup-inventory-cursor.v3"
INVENTORY_PAGE_SCHEMA: Final = "memory-comparison-paged-cleanup-inventory-page.v3"
INVENTORY_TERMINAL_SCHEMA: Final = "memory-comparison-paged-cleanup-inventory-terminal.v3"
ABSENCE_PASS_SCHEMA: Final = "memory-comparison-paged-cleanup-absence-pass.v3"
DELETION_RECEIPT_SCHEMA: Final = "memory-comparison-paged-cleanup-deletion-receipt.v3"
TERMINAL_EVIDENCE_SCHEMA: Final = "memory-comparison-paged-cleanup-terminal-evidence.v3"
EMPTY_EXHAUSTIVE_SCAN_ROOT_SHA256: Final = commitment("absence-empty-scan/v3", [])
EMPTY_GLOBAL_READBACK_ROOT_SHA256: Final = commitment("absence-empty-global/v3", [])
INVENTORY_KINDS: Final = (
    "memory_scopes",
    "memory_threads",
    "facts",
    "fact_source_refs",
    "documents",
    "chunks",
    "qdrant_target_identities",
    "graphiti_target_names",
    "graphiti_target_uuids",
    "qdrant_upsert_jobs",
    "qdrant_delete_jobs",
    "graphiti_upsert_jobs",
    "graphiti_delete_jobs",
    "cleanup_outbox_receipts",
    "unsupported_rows",
)


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3InventoryCursor:
    snapshot_sha256: str
    kind: str
    last_canonical_key_sha256: str | None
    page_index: int
    cursor_sha256: str
    schema_version: str = INVENTORY_CURSOR_SCHEMA

    def __post_init__(self) -> None:
        digest(self.snapshot_sha256)
        exact_int(self.page_index)
        if self.last_canonical_key_sha256 is not None:
            digest(self.last_canonical_key_sha256)
        body = {
            "schema_version": self.schema_version,
            "snapshot_sha256": self.snapshot_sha256,
            "kind": self.kind,
            "last_canonical_key_sha256": self.last_canonical_key_sha256,
            "page_index": self.page_index,
        }
        if (
            self.schema_version != INVENTORY_CURSOR_SCHEMA
            or self.kind not in INVENTORY_KINDS
            or self.cursor_sha256 != commitment("inventory-cursor/v3", body)
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_cursor_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3InventoryPage:
    authority_terminal_sha256: str
    snapshot_sha256: str
    kind: str
    page_index: int
    input_cursor_sha256: str | None
    output_cursor: ManagedCleanupV3InventoryCursor | None
    ordered_canonical_key_sha256: tuple[str, ...]
    ordered_row_sha256: tuple[str, ...]
    ordered_primary_target_identity_sha256: tuple[str, ...]
    ordered_secondary_target_identity_sha256: tuple[str, ...]
    exhausted: bool
    page_sha256: str
    schema_version: str = INVENTORY_PAGE_SCHEMA

    def __post_init__(self) -> None:
        digest(self.authority_terminal_sha256)
        digest(self.snapshot_sha256)
        exact_int(self.page_index)
        if self.output_cursor is not None:
            if type(self.output_cursor) is not ManagedCleanupV3InventoryCursor:
                raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_page_invalid")
            self.output_cursor.__post_init__()
        if self.input_cursor_sha256 is not None:
            digest(self.input_cursor_sha256)
        keys, rows = self.ordered_canonical_key_sha256, self.ordered_row_sha256
        primary = self.ordered_primary_target_identity_sha256
        secondary = self.ordered_secondary_target_identity_sha256
        if any(type(value) is not tuple for value in (keys, rows, primary, secondary)):
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_page_invalid")
        for value in (*keys, *rows, *primary, *secondary):
            digest(value)
        body = {
            "schema_version": self.schema_version,
            "authority_terminal_sha256": self.authority_terminal_sha256,
            "snapshot_sha256": self.snapshot_sha256,
            "kind": self.kind,
            "page_index": self.page_index,
            "input_cursor_sha256": self.input_cursor_sha256,
            "output_cursor_sha256": None
            if self.output_cursor is None
            else self.output_cursor.cursor_sha256,
            "ordered_canonical_key_sha256": list(keys),
            "ordered_row_sha256": list(rows),
            "ordered_primary_target_identity_sha256": list(primary),
            "ordered_secondary_target_identity_sha256": list(secondary),
            "exhausted": self.exhausted,
        }
        if (
            self.schema_version != INVENTORY_PAGE_SCHEMA
            or self.kind not in INVENTORY_KINDS
            or len(keys) != len(rows)
            or (
                self.kind
                in {
                    "qdrant_target_identities",
                    "graphiti_target_names",
                    "graphiti_target_uuids",
                }
                and rows != keys
            )
            or primary
            or secondary
            or len(keys) > INVENTORY_PAGE_SIZE
            or len(set(keys)) != len(keys)
            or tuple(sorted(keys)) != keys
            or type(self.exhausted) is not bool
            or (self.exhausted != (self.output_cursor is None))
            or (not self.exhausted and not keys)
            or (
                self.output_cursor is not None
                and (
                    self.output_cursor.snapshot_sha256 != self.snapshot_sha256
                    or self.output_cursor.kind != self.kind
                    or self.output_cursor.page_index != self.page_index + 1
                    or self.output_cursor.last_canonical_key_sha256 != keys[-1]
                )
            )
            or self.page_sha256 != commitment("inventory-page/v3", body)
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_page_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3InventoryKindReceipt:
    kind: str
    row_count: int
    page_count: int
    ordered_rows_root_sha256: str

    def __post_init__(self) -> None:
        exact_int(self.row_count)
        exact_int(self.page_count, minimum=1)
        digest(self.ordered_rows_root_sha256)
        if self.kind not in INVENTORY_KINDS:
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_kind_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedCleanupV3InventoryTerminal:
    profile_id: str
    context_sha256: str
    authority_terminal_sha256: str
    cleanup_receipt_sha256: str
    snapshot_sha256: str
    repeatable_read: bool
    first_page_minimum_proven: bool
    kind_receipts: tuple[ManagedCleanupV3InventoryKindReceipt, ...]
    expected_qdrant_identity_root_sha256: str
    expected_qdrant_identity_count: int
    expected_graphiti_name_root_sha256: str
    expected_graphiti_uuid_root_sha256: str
    expected_graphiti_identity_count: int
    terminal_sha256: str
    schema_version: str = INVENTORY_TERMINAL_SCHEMA

    def __post_init__(self) -> None:
        for value in (
            self.context_sha256,
            self.authority_terminal_sha256,
            self.cleanup_receipt_sha256,
            self.snapshot_sha256,
            self.expected_qdrant_identity_root_sha256,
            self.expected_graphiti_name_root_sha256,
            self.expected_graphiti_uuid_root_sha256,
        ):
            digest(value)
        for value in (self.expected_qdrant_identity_count, self.expected_graphiti_identity_count):
            exact_int(value)
        receipts = self.kind_receipts
        if (
            type(receipts) is not tuple
            or tuple(
                item.kind for item in receipts if type(item) is ManagedCleanupV3InventoryKindReceipt
            )
            != INVENTORY_KINDS
            or any(type(item) is not ManagedCleanupV3InventoryKindReceipt for item in receipts)
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_terminal_invalid")
        for item in receipts:
            item.__post_init__()
        oracle = profile_oracle(self.profile_id)
        facts = int(oracle["operation_count"]) if oracle["lane"] == "fact" else 0
        documents = int(oracle["operation_count"]) if oracle["lane"] == "document" else 0
        chunks = int(oracle["fragment_count"])
        expected_counts = (
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
        body = self.payload(False)
        if (
            self.schema_version != INVENTORY_TERMINAL_SCHEMA
            or self.repeatable_read is not True
            or self.first_page_minimum_proven is not True
            or tuple(item.row_count for item in receipts) != expected_counts
            or self.expected_qdrant_identity_count != chunks
            or self.expected_graphiti_identity_count != facts
            or self.terminal_sha256 != commitment("inventory-terminal/v3", body)
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_terminal_invalid")

    def payload(self, include_commitment: bool = True) -> dict[str, object]:
        value = {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "context_sha256": self.context_sha256,
            "authority_terminal_sha256": self.authority_terminal_sha256,
            "cleanup_receipt_sha256": self.cleanup_receipt_sha256,
            "snapshot_sha256": self.snapshot_sha256,
            "repeatable_read": self.repeatable_read,
            "first_page_minimum_proven": self.first_page_minimum_proven,
            "kind_receipts": [
                item.__dict__
                if hasattr(item, "__dict__")
                else {name: getattr(item, name) for name in item.__dataclass_fields__}
                for item in self.kind_receipts
            ],
            "expected_qdrant_identity_root_sha256": self.expected_qdrant_identity_root_sha256,
            "expected_qdrant_identity_count": self.expected_qdrant_identity_count,
            "expected_graphiti_name_root_sha256": self.expected_graphiti_name_root_sha256,
            "expected_graphiti_uuid_root_sha256": self.expected_graphiti_uuid_root_sha256,
            "expected_graphiti_identity_count": self.expected_graphiti_identity_count,
        }
        if include_commitment:
            value["terminal_sha256"] = self.terminal_sha256
        return value


class ManagedCleanupV3InventorySnapshotPort(Protocol):
    def first(self, *, kind: str, limit: int) -> ManagedCleanupV3InventoryPage: ...
    def next(
        self, cursor: ManagedCleanupV3InventoryCursor, *, limit: int
    ) -> ManagedCleanupV3InventoryPage: ...
    def finalize(self) -> ManagedCleanupV3InventoryTerminal: ...
    def abort(self) -> None: ...


class ManagedCleanupV3InventoryPort(Protocol):
    def begin_repeatable_read(
        self, *, authority_terminal_sha256: str, cleanup_receipt_sha256: str
    ) -> ManagedCleanupV3InventorySnapshotPort: ...


__all__ = tuple(
    name
    for name in globals()
    if name.startswith("ManagedCleanupV3") or name in {"INVENTORY_KINDS", "INVENTORY_PAGE_SIZE"}
)
