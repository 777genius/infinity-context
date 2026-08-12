"""Successful one-operation evidence for fresh-chain Mem0 cleanup."""

from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssOperationEvidence,
)

from .contracts import FreshChainCallResult


def operation_evidence(
    *,
    unit: ManagedMem0V5SourceUnit,
    operation_id_sha256: str,
    extraction: FreshChainCallResult,
    storage: ManagedMem0V5AuthenticatedStorageWitness,
) -> Mem0OssOperationEvidence:
    payload = {
        "operation_id_sha256": operation_id_sha256,
        "unit_index": 0,
        "unit_identity_sha256": unit.unit_identity_sha256,
        "unit_sha256": unit.unit_sha256,
        "scope_sha256": unit.scope_sha256,
        "provider_receipt_sha256": extraction.physical_receipt_sha256,
        "disposition": "completed",
        "extraction_calls": 1,
        "retry_count": 0,
        "request_tokens": extraction.usage.prompt_tokens,
        "response_tokens": extraction.usage.completion_tokens,
        "stored_identity_sha256": storage.storage_commitment_sha256,
        "stored_record_count": len(storage.created_record_ids),
    }
    return Mem0OssOperationEvidence(
        **payload,
        state="committed",
        commitment_sha256=canonical_sha256(payload),
    )


__all__ = ("operation_evidence",)
