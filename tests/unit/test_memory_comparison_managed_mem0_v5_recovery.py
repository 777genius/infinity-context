from __future__ import annotations

import hashlib

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
    ManagedMem0V5LaneCoordinator,
    ManagedMem0V5SourcePair,
    ManagedMem0V5StorageObservation,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    CleanupVerificationContext,
    CleanupVerificationResult,
    Mem0OssAdmissionRequest,
    Mem0OssFullRunError,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationResult,
    StorageVerificationContext,
    StorageVerificationResult,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import Mem0OssFullRunService


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
                "text": "Alice likes tea.",
                "timestamp": 1,
            }
        ],
        "documents": [],
        "conversations": [],
    }
    case = ManagedRunCase("case-1", corpus_id, record)
    return ManagedMem0V5ManifestProjector().project((case,), current_date="2026-08-07")


class _ReceiptPort:
    @staticmethod
    def _result(context: RuntimeReceiptVerificationContext) -> RuntimeReceiptVerificationResult:
        return RuntimeReceiptVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            operation_id_sha256=context.operation_id_sha256,
            unit_identity_sha256=context.unit_identity_sha256,
            unit_sha256=context.unit_sha256,
            route_sha256=context.route_sha256,
            scope_sha256=context.scope_sha256,
            provider_receipt_sha256=_sha("receipt"),
            disposition=Mem0OssReceiptDisposition.COMPLETED,
            extraction_calls=1,
            retry_count=0,
            request_tokens=1,
            response_tokens=1,
        )

    def verify_dispatch_receipt(self, *, payload, context):
        assert payload == {"receipt": "dispatch"}
        return self._result(context)

    def verify_status_readback(self, *, payload, context):
        assert payload == {"receipt": "status"}
        return self._result(context)


class _StoragePort:
    def __init__(self, *, reject_once: bool = False) -> None:
        self.reject_once = reject_once

    def verify(self, *, payload, context: StorageVerificationContext):
        if self.reject_once:
            self.reject_once = False
            raise ValueError("simulated verifier crash")
        return StorageVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            operation_id_sha256=context.operation_id_sha256,
            unit_identity_sha256=context.unit_identity_sha256,
            unit_sha256=context.unit_sha256,
            route_sha256=context.route_sha256,
            scope_sha256=context.scope_sha256,
            provider_receipt_sha256=context.provider_receipt_sha256,
            stored_identity_sha256=payload.evidence_commitment_sha256,
            stored_record_count=len(payload.created_record_ids),
        )


class _CleanupPort:
    def verify(self, *, payload, context: CleanupVerificationContext):
        assert payload == {"cleanup": context.aborting}
        return CleanupVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            seal_commitment_sha256=context.seal_commitment_sha256,
            operation_root_sha256=context.operation_root_sha256,
            operation_inventory_root_sha256=context.operation_inventory_root_sha256,
            deleted_operation_count=context.expected_operation_count,
            residual_record_count=0,
            residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
        )


class _Lane:
    def __init__(self, *, dispatch_fail_once=False, inspect_fail_once=False) -> None:
        self.dispatch_fail_once = dispatch_fail_once
        self.inspect_fail_once = inspect_fail_once
        self.calls: list[str] = []

    def admit(self, **kwargs) -> None:
        del kwargs

    def dispatch(self, **kwargs):
        del kwargs
        self.calls.append("dispatch")
        if self.dispatch_fail_once:
            self.dispatch_fail_once = False
            raise RuntimeError("lost dispatch response")
        return {"receipt": "dispatch"}

    def status(self, **kwargs):
        del kwargs
        self.calls.append("status")
        return {"receipt": "status"}

    def inspect_storage(self, **kwargs):
        self.calls.append("storage")
        if self.inspect_fail_once:
            self.inspect_fail_once = False
            raise RuntimeError("storage inspection crash")
        unit = kwargs["unit"]
        return ManagedMem0V5StorageObservation.create(
            operation_id_sha256=kwargs["operation_id_sha256"],
            unit_identity_sha256=unit.unit_identity_sha256,
            created_record_ids=("opaque-record-1",),
            source_pairs=(ManagedMem0V5SourcePair(unit.source_id, unit.source_sha256),),
        )

    def cleanup(self, **kwargs):
        self.calls.append("cleanup")
        return {"cleanup": kwargs["aborting"]}


def _coordinator(lane: _Lane, storage: _StoragePort):
    authority = _authority()
    service = Mem0OssFullRunService(
        manifest_port=ManagedMem0V5ManifestProjector(),
        receipt_port=_ReceiptPort(),
        storage_port=storage,
        cleanup_port=_CleanupPort(),
    )
    coordinator = ManagedMem0V5LaneCoordinator(service=service, lane_port=lane)
    request = Mem0OssAdmissionRequest(
        run_id="managed-v5-recovery",
        route_sha256=_sha("route"),
        credential_binding_sha256=_sha("credential"),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="source-r1",
        runtime_source_sha256=_sha("source"),
        runtime_base_sha256=_sha("base"),
        expected_operation_count=1,
    )
    coordinator.admit(
        authority=authority,
        request=request,
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )
    return authority, service, coordinator


def _seal_and_cleanup(coordinator: ManagedMem0V5LaneCoordinator) -> None:
    assert coordinator.dispatch_pending().operation_count == 1
    assert coordinator.cleanup().residual_record_count == 0


def test_recovery_after_receipt_skips_status_and_redispatch() -> None:
    lane = _Lane(inspect_fail_once=True)
    _, _, coordinator = _coordinator(lane, _StoragePort())
    with pytest.raises(RuntimeError, match="inspection crash"):
        coordinator.dispatch_pending()

    coordinator.reconcile_after_crash()
    _seal_and_cleanup(coordinator)
    assert lane.calls.count("dispatch") == 1
    assert lane.calls.count("status") == 0


def test_recovery_during_storage_verifier_skips_status_and_reauthenticates() -> None:
    lane = _Lane()
    _, _, coordinator = _coordinator(lane, _StoragePort(reject_once=True))
    with pytest.raises(Mem0OssFullRunError, match="storage_verification_failed"):
        coordinator.dispatch_pending()
    assert coordinator.storage_observations == ()

    coordinator.reconcile_after_crash()
    _seal_and_cleanup(coordinator)
    assert lane.calls.count("dispatch") == 1
    assert lane.calls.count("status") == 0
    assert lane.calls.count("storage") == 2


def test_recovery_after_storage_verification_commits_without_status_or_redispatch() -> None:
    lane = _Lane()
    authority, service, coordinator = _coordinator(lane, _StoragePort())
    operation_id = service.reserve(unit_index=0)
    coordinator._operation_ids[0] = operation_id
    service.record_dispatched(unit_index=0)
    coordinator._dispatched.add(0)
    receipt = lane.dispatch()
    service.verify_dispatch_receipt(unit_index=0, receipt_payload=receipt)
    observation = lane.inspect_storage(
        unit=authority.units[0],
        operation_id_sha256=operation_id,
    )
    service.verify_storage(unit_index=0, storage_payload=observation)

    coordinator.reconcile_after_crash()
    _seal_and_cleanup(coordinator)
    assert lane.calls.count("dispatch") == 1
    assert lane.calls.count("status") == 0


def test_receipt_unknown_uses_status_exactly_once_and_never_redispatches() -> None:
    lane = _Lane(dispatch_fail_once=True)
    _, _, coordinator = _coordinator(lane, _StoragePort())
    with pytest.raises(RuntimeError, match="lost dispatch"):
        coordinator.dispatch_pending()

    coordinator.reconcile_after_crash()
    _seal_and_cleanup(coordinator)
    assert lane.calls.count("dispatch") == 1
    assert lane.calls.count("status") == 1
