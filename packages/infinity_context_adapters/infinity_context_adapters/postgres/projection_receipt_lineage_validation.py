"""Canonical lineage and provider-identity validation for projection receipts."""

from __future__ import annotations

from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptError,
    ProjectionResultReceipt,
)

from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryFactRow
from infinity_context_adapters.qdrant.identity_evidence import qdrant_point_id_for_chunk

CanonicalProjectionRows = tuple[MemoryChunkRow, ...] | MemoryChunkRow | MemoryFactRow


def validate_canonical_rows(
    canonical: CanonicalProjectionRows,
    receipt: ProjectionResultReceipt,
) -> None:
    binding = receipt.binding
    rows = canonical if isinstance(canonical, tuple) else (canonical,)
    expected_status = "active" if receipt.operation == "upsert" else "deleted"
    if any(
        row.space_id != binding.space_id
        or row.memory_scope_id != binding.memory_scope_id
        or row.thread_id != binding.thread_id
        or row.status != expected_status
        for row in rows
    ):
        raise ProjectionReceiptError("projection_receipt.canonical_lineage_divergent")
    if (
        isinstance(canonical, MemoryFactRow)
        and receipt.operation == "upsert"
        and canonical.version != binding.aggregate_version
    ):
        raise ProjectionReceiptError("projection_receipt.canonical_version_divergent")


def validate_identity_source_mapping(
    canonical: CanonicalProjectionRows,
    receipt: ProjectionResultReceipt,
) -> None:
    if receipt.binding.lane == "qdrant":
        rows = canonical if isinstance(canonical, tuple) else (canonical,)
        if {item.identity.canonical_source_id for item in receipt.identities} != {
            row.id for row in rows
        } or any(
            item.identity.physical_identity
            != qdrant_point_id_for_chunk(item.identity.canonical_source_id)
            for item in receipt.identities
        ):
            raise ProjectionReceiptError("projection_receipt.physical_mapping_divergent")
    elif any(
        item.identity.canonical_source_id != receipt.binding.aggregate_id
        for item in receipt.identities
    ):
        raise ProjectionReceiptError("projection_receipt.physical_mapping_divergent")


__all__ = ("CanonicalProjectionRows", "validate_canonical_rows", "validate_identity_source_mapping")
