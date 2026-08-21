"""Exact abort-cleanup material for a known failed Mem0 extraction."""

from __future__ import annotations

from dataclasses import asdict

from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    CleanupVerificationContext,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssRunSeal,
    operation_root,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanupReceipt,
)

from .contracts import (
    FreshChainCallFailure,
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainCleanupResult,
)
from .ledger_models import FreshChainFailureDisposition
from .mem0_operation_evidence import operation_evidence

_EMPTY_ROOT_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def cleanup_successful_extraction(
    *,
    lane: ManagedMem0V5HttpLane,
    admission: Mem0OssFullRunAdmission,
    manifest: ManagedMem0V5ManifestAuthority,
    unit: ManagedMem0V5SourceUnit,
    operation_id_sha256: str,
    namespace_id: str,
    namespace_commitment_sha256: str,
    source_commitment_sha256: str,
    source_projection_commitment_sha256: str,
    extraction: FreshChainCallResult,
    storage: ManagedMem0V5AuthenticatedStorageWitness,
    aborting: bool,
    journal: object,
) -> FreshChainCleanupResult:
    """Durably clean one authenticated successful extraction, with or without retrieval."""

    evidence = operation_evidence(
        unit=unit,
        operation_id_sha256=operation_id_sha256,
        extraction=extraction,
        storage=storage,
    )
    root = operation_root((evidence,))
    seal = Mem0OssRunSeal(
        admission_commitment_sha256=admission.commitment_sha256,
        operation_count=1,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        operation_root_sha256=root,
        provider_observed_extraction_calls=1,
        provider_observed_request_tokens=extraction.usage.prompt_tokens,
        provider_observed_response_tokens=extraction.usage.completion_tokens,
    )
    cleanup_seal = None if aborting else seal
    context = CleanupVerificationContext(
        admission_commitment_sha256=admission.commitment_sha256,
        seal_commitment_sha256=None if cleanup_seal is None else cleanup_seal.commitment_sha256,
        operation_root_sha256=None if cleanup_seal is None else root,
        operation_inventory_root_sha256=canonical_sha256({"operations": [evidence.payload()]}),
        expected_operation_count=1,
        aborting=aborting,
    )
    intent = {
        "admission_commitment_sha256": admission.commitment_sha256,
        "cleanup_context": asdict(context),
        "namespace_commitment_sha256": namespace_commitment_sha256,
        "namespace_id": namespace_id,
        "operation_evidence": evidence.payload(),
        "operation_id_sha256": operation_id_sha256,
        "seal": None if cleanup_seal is None else asdict(cleanup_seal),
        "source_commitment_sha256": source_commitment_sha256,
        "source_projection_commitment_sha256": source_projection_commitment_sha256,
    }
    terminal = journal.begin_cleanup(intent)
    if terminal is not None:
        return terminal
    receipt = lane.cleanup(
        admission=admission,
        seal=cleanup_seal,
        aborting=aborting,
        context=context,
    )
    if (
        type(receipt) is not Mem0V5CleanupReceipt
        or receipt.admission_commitment_sha256 != admission.commitment_sha256
        or receipt.seal_commitment_sha256 != context.seal_commitment_sha256
        or receipt.operation_root_sha256 != context.operation_root_sha256
        or receipt.operation_inventory_root_sha256 != context.operation_inventory_root_sha256
        or receipt.deleted_operation_count != 1
        or receipt.residual_record_count != 0
        or receipt.residual_root_sha256 != _EMPTY_ROOT_SHA256
    ):
        _fail("fresh_chain_mem0_cleanup_receipt_invalid")
    receipt_sha256 = canonical_sha256(asdict(receipt))
    result = FreshChainCleanupResult(
        namespace_commitment_sha256=namespace_commitment_sha256,
        cleanup_authority_sha256=canonical_sha256(asdict(context)),
        receipt_id=f"mem0-cleanup:{receipt_sha256}",
        receipt_sha256=receipt_sha256,
        outcome_sha256=canonical_sha256(
            {"deleted": True, "receipt_sha256": receipt_sha256, "residual_count": 0}
        ),
        deleted=True,
        operation_count=1,
        residual_count=0,
    )
    return journal.record_cleanup_terminal(cleanup_intent=intent, result=result)


def cleanup_failed_extraction(
    *,
    lane: ManagedMem0V5HttpLane,
    admission: Mem0OssFullRunAdmission,
    unit: ManagedMem0V5SourceUnit,
    operation_id_sha256: str,
    namespace_id: str,
    namespace_commitment_sha256: str,
    source_commitment_sha256: str,
    source_projection_commitment_sha256: str,
    failure: FreshChainCallFailure,
    journal: object,
) -> FreshChainCleanupResult:
    if (
        type(failure) is not FreshChainCallFailure
        or failure.stage != "mem0_extraction"
        or failure.ordinal != 0
        or type(failure.provider_disposition) is not FreshChainFailureDisposition
    ):
        _fail("fresh_chain_mem0_abort_failure_invalid")
    inventory = {
        "operation_id_sha256": operation_id_sha256,
        "unit_index": 0,
        "unit_identity_sha256": unit.unit_identity_sha256,
        "unit_sha256": unit.unit_sha256,
        "scope_sha256": unit.scope_sha256,
        "provider_receipt_sha256": failure.physical_receipt_sha256,
        "disposition": failure.provider_disposition.value,
        "extraction_calls": 1,
        "retry_count": 0,
        "request_tokens": failure.usage.prompt_tokens,
        "response_tokens": failure.usage.completion_tokens,
        "stored_identity_sha256": None,
        "stored_record_count": 0,
    }
    context = CleanupVerificationContext(
        admission_commitment_sha256=admission.commitment_sha256,
        seal_commitment_sha256=None,
        operation_root_sha256=None,
        operation_inventory_root_sha256=canonical_sha256({"operations": [inventory]}),
        expected_operation_count=1,
        aborting=True,
    )
    failure_material = failure.material()
    failure_material.pop("transport_dispatched")
    intent = {
        "admission_commitment_sha256": admission.commitment_sha256,
        "cleanup_context": asdict(context),
        "failure": failure_material,
        "namespace_commitment_sha256": namespace_commitment_sha256,
        "namespace_id": namespace_id,
        "operation_inventory": inventory,
        "operation_id_sha256": operation_id_sha256,
        "seal": None,
        "source_commitment_sha256": source_commitment_sha256,
        "source_projection_commitment_sha256": source_projection_commitment_sha256,
    }
    terminal = journal.begin_cleanup(intent)
    if terminal is not None:
        return terminal
    receipt = lane.cleanup(
        admission=admission,
        seal=None,
        aborting=True,
        context=context,
    )
    if (
        type(receipt) is not Mem0V5CleanupReceipt
        or receipt.admission_commitment_sha256 != admission.commitment_sha256
        or receipt.seal_commitment_sha256 is not None
        or receipt.operation_root_sha256 is not None
        or receipt.operation_inventory_root_sha256 != context.operation_inventory_root_sha256
        or not 0 <= receipt.deleted_operation_count <= 1
        or receipt.residual_record_count != 0
        or receipt.residual_root_sha256 != _EMPTY_ROOT_SHA256
    ):
        _fail("fresh_chain_mem0_abort_cleanup_receipt_invalid")
    receipt_sha256 = canonical_sha256(asdict(receipt))
    result = FreshChainCleanupResult(
        namespace_commitment_sha256=namespace_commitment_sha256,
        cleanup_authority_sha256=canonical_sha256(asdict(context)),
        receipt_id=f"mem0-cleanup:{receipt_sha256}",
        receipt_sha256=receipt_sha256,
        outcome_sha256=canonical_sha256(
            {
                "deleted": True,
                "receipt_sha256": receipt_sha256,
                "residual_count": 0,
            }
        ),
        deleted=True,
        operation_count=1,
        residual_count=0,
    )
    return journal.record_cleanup_terminal(cleanup_intent=intent, result=result)


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = ("cleanup_failed_extraction", "cleanup_successful_extraction")
