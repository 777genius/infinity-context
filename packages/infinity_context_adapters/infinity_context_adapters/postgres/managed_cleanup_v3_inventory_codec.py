"""Authentication and core DTO codec for managed cleanup v3 inventory."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Error,
    canonical_bytes,
    commitment,
    digest,
    merkle_root,
)
from infinity_context_core.ports.managed_cleanup_v3_recovery import (
    INVENTORY_KINDS,
    ManagedCleanupV3InventoryCursor,
    ManagedCleanupV3InventoryPage,
)

TARGET_IDENTITY_KINDS = frozenset(
    {
        "qdrant_target_identities",
        "graphiti_target_names",
        "graphiti_target_uuids",
    }
)


def materialized_row_sha(
    kind: str, canonical_key_sha256: str, locator_sha256: str, row: object
) -> str:
    if kind in TARGET_IDENTITY_KINDS:
        return canonical_key_sha256
    return commitment(
        "inventory-row/v4",
        {"kind": kind, "locator_sha256": locator_sha256, "row": row},
    )


def inventory_mac(key: bytes, domain: str, payload: object) -> str:
    message = domain.encode("ascii") + b"\0" + canonical_bytes(payload)
    return hmac.new(key, message, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class InventorySummary:
    kind: str
    count: int
    root: str
    mac: str

    def payload(self, run: str, context: str, cleanup: str, authority: str) -> dict[str, object]:
        return {
            "run_id_sha256": run,
            "context_sha256": context,
            "cleanup_receipt_sha256": cleanup,
            "kind": self.kind,
            "authority_terminal_sha256": authority,
            "expected_count": self.count,
            "ordered_rows_root_sha256": self.root,
            "complete": True,
        }


def authenticate_summaries(
    rows: Any,
    key: bytes,
    run: str,
    context: str,
    cleanup: str,
    authority: str,
) -> tuple[InventorySummary, ...]:
    values = tuple(
        InventorySummary(
            str(row["kind"]),
            int(row["expected_count"]),
            str(row["ordered_rows_root_sha256"]),
            str(row["row_mac_sha256"]),
        )
        for row in rows
    )
    if len(values) != len(INVENTORY_KINDS) or {value.kind for value in values} != set(
        INVENTORY_KINDS
    ):
        raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_terminal_invalid")
    by_kind = {value.kind: value for value in values}
    ordered = tuple(by_kind[kind] for kind in INVENTORY_KINDS)
    for value in ordered:
        digest(value.root)
        expected = inventory_mac(
            key,
            "managed-cleanup-v4/inventory-summary",
            value.payload(run, context, cleanup, authority),
        )
        if value.count < 0 or not hmac.compare_digest(value.mac, expected):
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_terminal_invalid")
    return ordered


def normalize_locator_json(value: object) -> dict[str, object]:
    if type(value) is str:
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_page_invalid") from exc
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_page_invalid")
    canonical_bytes(value)
    return value


def authenticate_rows(
    rows: Any,
    key: bytes,
    run: str,
    context: str,
    cleanup: str,
    kind: str,
    last: str | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    keys, hashes = [], []
    for row in rows:
        canonical_key = digest(str(row["canonical_key_sha256"]))
        row_sha = digest(str(row["row_sha256"]))
        locator_sha = digest(str(row["locator_sha256"]))
        locator_json = normalize_locator_json(row["locator_json"])
        payload = {
            "run_id_sha256": run,
            "context_sha256": context,
            "cleanup_receipt_sha256": cleanup,
            "kind": kind,
            "canonical_key_sha256": canonical_key,
            "locator_json": locator_json,
            "locator_sha256": locator_sha,
            "row_sha256": row_sha,
        }
        if not hmac.compare_digest(
            str(row["row_mac_sha256"]),
            inventory_mac(key, "managed-cleanup-v4/inventory-key", payload),
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_page_invalid")
        keys.append(canonical_key)
        hashes.append(row_sha)
    if keys != sorted(keys) or len(keys) != len(set(keys)) or (last and keys and keys[0] <= last):
        raise ManagedCleanupV3Error("managed_cleanup_v3_inventory_page_invalid")
    return tuple(keys), tuple(hashes)


def build_core_cursor(
    snapshot: str, kind: str, last: str, page: int
) -> ManagedCleanupV3InventoryCursor:
    body = {
        "schema_version": "memory-comparison-paged-cleanup-inventory-cursor.v4",
        "snapshot_sha256": snapshot,
        "kind": kind,
        "last_canonical_key_sha256": last,
        "page_index": page,
    }
    return ManagedCleanupV3InventoryCursor(
        snapshot, kind, last, page, commitment("inventory-cursor/v4", body)
    )


def build_core_page(
    authority: str,
    snapshot: str,
    kind: str,
    page_index: int,
    input_cursor: str | None,
    output_cursor: ManagedCleanupV3InventoryCursor | None,
    keys: tuple[str, ...],
    rows: tuple[str, ...],
    exhausted: bool,
) -> ManagedCleanupV3InventoryPage:
    body = {
        "schema_version": "memory-comparison-paged-cleanup-inventory-page.v4",
        "authority_terminal_sha256": authority,
        "snapshot_sha256": snapshot,
        "kind": kind,
        "page_index": page_index,
        "input_cursor_sha256": input_cursor,
        "output_cursor_sha256": None if output_cursor is None else output_cursor.cursor_sha256,
        "ordered_canonical_key_sha256": list(keys),
        "ordered_row_sha256": list(rows),
        "ordered_primary_target_identity_sha256": [],
        "ordered_secondary_target_identity_sha256": [],
        "exhausted": exhausted,
    }
    return ManagedCleanupV3InventoryPage(
        authority,
        snapshot,
        kind,
        page_index,
        input_cursor,
        output_cursor,
        keys,
        rows,
        (),
        (),
        exhausted,
        commitment("inventory-page/v4", body),
    )


def page_root(label: str, pages: list[str]) -> str:
    return commitment(label, []) if not pages else merkle_root(tuple(pages))


__all__ = (
    "InventorySummary",
    "TARGET_IDENTITY_KINDS",
    "materialized_row_sha",
    "normalize_locator_json",
    "authenticate_rows",
    "authenticate_summaries",
    "build_core_cursor",
    "build_core_page",
    "inventory_mac",
    "page_root",
)
