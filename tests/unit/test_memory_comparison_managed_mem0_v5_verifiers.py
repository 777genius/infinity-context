from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5SourcePair,
    ManagedMem0V5StorageObservation,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_verifiers import (
    ManagedMem0V5CleanupBridgeVerifier,
    ManagedMem0V5StorageBridgeVerifier,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    CleanupVerificationContext,
    Mem0OssFullRunError,
    StorageVerificationContext,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanupReceipt,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _authority():
    corpus_id = f"locomo-corpus-{'a' * 64}"
    record = {
        "schema_version": "memory-comparison-managed-corpus.v2",
        "benchmark": "locomo",
        "corpus_id": corpus_id,
        "thread_id": f"locomo-thread-{'b' * 64}",
        "memories": [
            {
                "kind": "fact",
                "role": "user",
                "session_alias": "session-0001",
                "source_alias": "memory-000001",
                "speaker": "Alice",
                "session_date": "2024-03-10",
                "text": "Alice fact.",
                "timestamp": 1,
            }
        ],
        "documents": [],
        "conversations": [],
    }
    case = ManagedRunCase("case-1", corpus_id, record)
    return ManagedMem0V5ManifestProjector().project((case,), current_date="2026-08-07")


def _storage_inputs():
    authority = _authority()
    unit = authority.units[0]
    context = StorageVerificationContext(
        admission_commitment_sha256=_sha("admission"),
        operation_id_sha256=_sha("operation"),
        unit_identity_sha256=unit.unit_identity_sha256,
        unit_sha256=unit.unit_sha256,
        route_sha256=_sha("route"),
        scope_sha256=unit.scope_sha256,
        provider_receipt_sha256=_sha("receipt"),
    )
    observation = ManagedMem0V5StorageObservation.create(
        operation_id_sha256=context.operation_id_sha256,
        unit_identity_sha256=context.unit_identity_sha256,
        storage_commitment_sha256=_sha("storage"),
        created_record_ids=("record-1",),
        source_pairs=(ManagedMem0V5SourcePair(unit.source_id, unit.source_sha256),),
    )
    issuer, verifier = create_managed_mem0_v5_storage_witness_authority()
    return authority, context, observation, issuer, verifier


def _witness(issuer, observation: ManagedMem0V5StorageObservation):
    return issuer.issue_authenticated_storage(
        operation_id_sha256=observation.operation_id_sha256,
        unit_identity_sha256=observation.unit_identity_sha256,
        storage_commitment_sha256=observation.storage_commitment_sha256,
        created_record_ids=observation.created_record_ids,
        source_pairs=tuple(
            (pair.source_id, pair.source_sha256) for pair in observation.source_pairs
        ),
    )


def _cleanup_context(*, aborting: bool = False) -> CleanupVerificationContext:
    return CleanupVerificationContext(
        admission_commitment_sha256=_sha("admission"),
        seal_commitment_sha256=None if aborting else _sha("seal"),
        operation_root_sha256=None if aborting else _sha("operation-root"),
        operation_inventory_root_sha256=_sha("inventory"),
        expected_operation_count=3,
        aborting=aborting,
    )


def _cleanup_receipt(
    context: CleanupVerificationContext,
    *,
    deleted: int | None = None,
    residual: int = 0,
    residual_root: str = MEM0_OSS_EMPTY_ROOT_SHA256,
) -> Mem0V5CleanupReceipt:
    return Mem0V5CleanupReceipt(
        admission_commitment_sha256=context.admission_commitment_sha256,
        seal_commitment_sha256=context.seal_commitment_sha256,
        operation_root_sha256=context.operation_root_sha256,
        operation_inventory_root_sha256=context.operation_inventory_root_sha256,
        deleted_operation_count=(context.expected_operation_count if deleted is None else deleted),
        residual_record_count=residual,
        residual_root_sha256=residual_root,
    )


def test_storage_bridge_binds_authenticated_observation_to_sealed_authority() -> None:
    authority, context, observation, issuer, witness_verifier = _storage_inputs()
    witness = _witness(issuer, observation)

    result = ManagedMem0V5StorageBridgeVerifier(
        authority=authority,
        storage_witness_verifier=witness_verifier,
    ).verify(
        payload=witness,
        context=context,
    )

    assert result.operation_id_sha256 == context.operation_id_sha256
    assert result.unit_identity_sha256 == context.unit_identity_sha256
    assert result.unit_sha256 == context.unit_sha256
    assert result.scope_sha256 == context.scope_sha256
    assert result.stored_identity_sha256 == observation.storage_commitment_sha256
    assert result.stored_record_count == 1


@pytest.mark.parametrize("field", ("operation", "unit", "scope", "source"))
def test_storage_bridge_fails_closed_on_each_binding_mismatch(field: str) -> None:
    authority, context, observation, issuer, witness_verifier = _storage_inputs()
    if field == "operation":
        observation = ManagedMem0V5StorageObservation.create(
            operation_id_sha256=_sha("other-operation"),
            unit_identity_sha256=observation.unit_identity_sha256,
            storage_commitment_sha256=observation.storage_commitment_sha256,
            created_record_ids=observation.created_record_ids,
            source_pairs=observation.source_pairs,
        )
    elif field == "unit":
        observation = ManagedMem0V5StorageObservation.create(
            operation_id_sha256=observation.operation_id_sha256,
            unit_identity_sha256=_sha("other-unit"),
            storage_commitment_sha256=observation.storage_commitment_sha256,
            created_record_ids=observation.created_record_ids,
            source_pairs=observation.source_pairs,
        )
    elif field == "scope":
        context = replace(context, scope_sha256=_sha("other-scope"))
    else:
        observation = ManagedMem0V5StorageObservation.create(
            operation_id_sha256=observation.operation_id_sha256,
            unit_identity_sha256=observation.unit_identity_sha256,
            storage_commitment_sha256=observation.storage_commitment_sha256,
            created_record_ids=observation.created_record_ids,
            source_pairs=(ManagedMem0V5SourcePair("other-source", _sha("other-source")),),
        )

    with pytest.raises(Mem0OssFullRunError, match="binding_mismatch"):
        ManagedMem0V5StorageBridgeVerifier(
            authority=authority,
            storage_witness_verifier=witness_verifier,
        ).verify(
            payload=_witness(issuer, observation),
            context=context,
        )


def test_storage_bridge_rejects_raw_and_wrong_authority_witnesses() -> None:
    authority, context, observation, _, witness_verifier = _storage_inputs()
    bridge = ManagedMem0V5StorageBridgeVerifier(
        authority=authority,
        storage_witness_verifier=witness_verifier,
    )
    forged = ManagedMem0V5AuthenticatedStorageWitness(
        operation_id_sha256=observation.operation_id_sha256,
        unit_identity_sha256=observation.unit_identity_sha256,
        storage_commitment_sha256=observation.storage_commitment_sha256,
        created_record_ids=observation.created_record_ids,
        source_pairs=tuple(
            (pair.source_id, pair.source_sha256) for pair in observation.source_pairs
        ),
        evidence_commitment_sha256=observation.evidence_commitment_sha256,
    )
    for raw in (observation, observation.public_payload(), forged):
        with pytest.raises(Mem0OssFullRunError, match="witness_invalid"):
            bridge.verify(payload=raw, context=context)

    other_issuer, _ = create_managed_mem0_v5_storage_witness_authority()
    with pytest.raises(Mem0OssFullRunError, match="witness_invalid"):
        bridge.verify(
            payload=_witness(other_issuer, observation),
            context=context,
        )


def test_cleanup_bridge_accepts_exact_delete_and_partial_abort_receipts() -> None:
    verifier = ManagedMem0V5CleanupBridgeVerifier()
    delete_context = _cleanup_context()
    delete_result = verifier.verify(
        payload=_cleanup_receipt(delete_context),
        context=delete_context,
    )
    assert delete_result.deleted_operation_count == 3
    assert delete_result.residual_record_count == 0

    abort_context = _cleanup_context(aborting=True)
    abort_result = verifier.verify(
        payload=_cleanup_receipt(abort_context, deleted=1),
        context=abort_context,
    )
    assert abort_result.deleted_operation_count == 1


@pytest.mark.parametrize(
    "receipt",
    (
        lambda context: replace(
            _cleanup_receipt(context), admission_commitment_sha256=_sha("other-admission")
        ),
        lambda context: replace(
            _cleanup_receipt(context), seal_commitment_sha256=_sha("other-seal")
        ),
        lambda context: replace(
            _cleanup_receipt(context), operation_root_sha256=_sha("other-root")
        ),
        lambda context: replace(
            _cleanup_receipt(context),
            operation_inventory_root_sha256=_sha("other-inventory"),
        ),
        lambda context: _cleanup_receipt(context, deleted=2),
        lambda context: _cleanup_receipt(context, residual=1),
        lambda context: _cleanup_receipt(context, residual_root=_sha("non-empty")),
    ),
)
def test_cleanup_bridge_fails_closed_on_tuple_count_or_residue(receipt) -> None:
    context = _cleanup_context()
    with pytest.raises(Mem0OssFullRunError, match="binding_mismatch"):
        ManagedMem0V5CleanupBridgeVerifier().verify(
            payload=receipt(context),
            context=context,
        )


def test_cleanup_bridge_rejects_structurally_similar_untyped_payload() -> None:
    context = _cleanup_context()
    with pytest.raises(Mem0OssFullRunError, match="receipt_invalid"):
        ManagedMem0V5CleanupBridgeVerifier().verify(
            payload=_cleanup_receipt(context).__dict__
            if hasattr(_cleanup_receipt(context), "__dict__")
            else {},
            context=context,
        )
