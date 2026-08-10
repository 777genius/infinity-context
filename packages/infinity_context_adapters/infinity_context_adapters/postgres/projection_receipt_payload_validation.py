"""Exact production-outbox payload validation for projection receipts."""

from __future__ import annotations

from datetime import UTC, datetime

from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptError,
    ProjectionResultReceipt,
)

from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow
from infinity_context_adapters.qdrant.identity_evidence import qdrant_point_id_for_chunk


def _normalized_occurred_at(value: object, created_at: datetime) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProjectionReceiptError("projection_receipt.outbox_payload_divergent")
    try:
        observed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ProjectionReceiptError("projection_receipt.outbox_payload_divergent") from exc
    expected = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    if observed.tzinfo is None or observed.astimezone(UTC) != expected.astimezone(UTC):
        raise ProjectionReceiptError("projection_receipt.outbox_payload_divergent")
    return value


def validate_production_payload(outbox: MemoryOutboxRow, receipt: ProjectionResultReceipt) -> None:
    binding = receipt.binding
    payload = outbox.payload_json
    sources = sorted(item.identity.canonical_source_id for item in receipt.identities)
    expected = {
        ("upsert", "qdrant"): {"chunk_id": binding.aggregate_id},
        ("upsert", "graphiti"): {
            "message_id": outbox.message_key,
            "fact_id": binding.aggregate_id,
            "version": binding.aggregate_version,
            "space_id": binding.space_id,
            "memory_scope_id": binding.memory_scope_id,
            "thread_id": binding.thread_id,
            "occurred_at": _normalized_occurred_at(payload.get("occurred_at"), outbox.created_at),
        },
        ("delete", "qdrant"): {
            "chunk_ids": sources,
            "space_id": binding.space_id,
            "cleanup_run_id_sha256": binding.run_id_sha256,
        },
        ("delete", "graphiti"): {
            "fact_id": binding.aggregate_id,
            "space_id": binding.space_id,
            "cleanup_run_id_sha256": binding.run_id_sha256,
        },
    }[(receipt.operation, binding.lane)]
    if payload != expected:
        raise ProjectionReceiptError("projection_receipt.outbox_payload_divergent")
    if receipt.operation == "delete":
        if binding.lane == "qdrant" and any(
            item.identity.physical_identity
            != qdrant_point_id_for_chunk(item.identity.canonical_source_id)
            for item in receipt.identities
        ):
            raise ProjectionReceiptError("projection_receipt.physical_mapping_divergent")
        if binding.lane == "graphiti" and any(
            item.identity.canonical_source_id != binding.aggregate_id for item in receipt.identities
        ):
            raise ProjectionReceiptError("projection_receipt.delete_membership_divergent")


__all__ = ("validate_production_payload",)
