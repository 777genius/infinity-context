"""Pure reconstruction of runner-visible operation, inventory, and seal commitments."""

from __future__ import annotations

from dataclasses import dataclass

from .domain import canonical_sha256


@dataclass(frozen=True, slots=True)
class OperationEvidence:
    operation_id_sha256: str
    unit_index: int
    unit_identity_sha256: str
    unit_sha256: str
    scope_sha256: str
    provider_receipt_sha256: str | None = None
    request_tokens: int = 0
    response_tokens: int = 0
    stored_identity_sha256: str | None = None
    stored_record_count: int = 0
    state: str = "reserved"

    def inventory_item(self) -> dict[str, object]:
        receipt = self.provider_receipt_sha256 is not None
        base: dict[str, object] = {
            "operation_id_sha256": self.operation_id_sha256,
            "unit_index": self.unit_index,
            "unit_identity_sha256": self.unit_identity_sha256,
            "unit_sha256": self.unit_sha256,
            "scope_sha256": self.scope_sha256,
            "provider_receipt_sha256": self.provider_receipt_sha256,
            "disposition": "completed" if receipt else None,
            "extraction_calls": 1 if receipt else 0,
            "retry_count": 0,
            "request_tokens": self.request_tokens,
            "response_tokens": self.response_tokens,
            "stored_identity_sha256": self.stored_identity_sha256,
            "stored_record_count": self.stored_record_count,
        }
        commitment = canonical_sha256(base) if self.state == "committed" else None
        return {**base, "state": self.state, "commitment_sha256": commitment}


def reconstruct(
    *,
    admission_commitment_sha256: str,
    ingestion_root_sha256: str,
    operations: tuple[OperationEvidence, ...],
    aborting: bool,
) -> dict[str, object]:
    inventory = [
        item.inventory_item() for item in sorted(operations, key=lambda item: item.unit_index)
    ]
    commitments = [
        str(item["commitment_sha256"])
        for item in inventory
        if item["commitment_sha256"] is not None
    ]
    operation_root = canonical_sha256({"operation_commitments": commitments})
    inventory_root = canonical_sha256({"operations": inventory})
    if aborting:
        return {
            "seal_commitment_sha256": None,
            "operation_root_sha256": None,
            "operation_inventory_root_sha256": inventory_root,
        }
    if len(commitments) != len(inventory):
        raise ValueError("cleanup_evidence_incomplete")
    extraction_calls = sum(int(item["extraction_calls"]) for item in inventory)
    request_tokens = sum(int(item["request_tokens"]) for item in inventory)
    response_tokens = sum(int(item["response_tokens"]) for item in inventory)
    seal = canonical_sha256(
        {
            "admission_commitment_sha256": admission_commitment_sha256,
            "operation_count": len(inventory),
            "ingestion_root_sha256": ingestion_root_sha256,
            "operation_root_sha256": operation_root,
            "provider_observed_extraction_calls": extraction_calls,
            "provider_observed_request_tokens": request_tokens,
            "provider_observed_response_tokens": response_tokens,
        }
    )
    return {
        "seal_commitment_sha256": seal,
        "operation_root_sha256": operation_root,
        "operation_inventory_root_sha256": inventory_root,
    }


def runner_state(local_state: str, *, outcome_unknown: bool) -> str:
    if local_state in {"STORAGE_VERIFIED", "COMMITTED"}:
        return "committed"
    if local_state == "RECEIPT_DURABLE":
        return "receipt_verified"
    if local_state == "DISPATCHED":
        return "reconciliation_required" if outcome_unknown else "dispatched"
    return "reserved"


__all__ = ("OperationEvidence", "reconstruct", "runner_state")
