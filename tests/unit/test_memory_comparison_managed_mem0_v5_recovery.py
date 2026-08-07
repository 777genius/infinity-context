from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_checkpoint as checkpoint_module,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    AtomicJsonManagedMem0V5CheckpointStore,
    HmacSha256ManagedMem0V5CheckpointSigner,
    ManagedMem0V5Checkpoint,
    ManagedMem0V5CheckpointError,
    ManagedMem0V5CheckpointPhase,
    ManagedMem0V5RunPhase,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
    ManagedMem0V5LaneCoordinator,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_progress import (
    ManagedMem0V5CheckpointProgress,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
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
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import Mem0OssFullRunService
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    cleanup_request_commitment,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _authority(*, unit_count: int = 1):
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
                "source_alias": f"memory-{index + 1:06d}",
                "speaker": "Alice",
                "session_date": "2024-03-10",
                "text": f"Alice fact {index + 1}.",
                "timestamp": index + 1,
            }
            for index in range(unit_count)
        ],
        "documents": [],
        "conversations": [],
    }
    case = ManagedRunCase("case-1", corpus_id, record)
    return ManagedMem0V5ManifestProjector().project((case,), current_date="2026-08-07")


class _ReceiptPort:
    def mark_outcome_unknown(self, *, context) -> None:
        assert context.readback_only is False

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
            stored_identity_sha256=payload.storage_commitment_sha256,
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
    def __init__(
        self,
        *,
        dispatch_fail_once=False,
        inspect_fail_once=False,
        zero_record_sequences: tuple[int, ...] = (),
        cleanup_fail_once: bool = False,
        cleanup_fail_before_commit_once: bool = False,
        cleanup_hook=None,
    ) -> None:
        self.dispatch_fail_once = dispatch_fail_once
        self.inspect_fail_once = inspect_fail_once
        self.zero_record_sequences = zero_record_sequences
        self.cleanup_fail_once = cleanup_fail_once
        self.cleanup_fail_before_commit_once = cleanup_fail_before_commit_once
        self.cleanup_hook = cleanup_hook
        self.cleanup_commits = 0
        self.calls: list[str] = []
        self.storage_issuer, _ = create_managed_mem0_v5_storage_witness_authority()

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
        record_ids = () if unit.sequence in self.zero_record_sequences else ("opaque-record-1",)
        return self.storage_issuer.issue_authenticated_storage(
            operation_id_sha256=kwargs["operation_id_sha256"],
            unit_identity_sha256=unit.unit_identity_sha256,
            storage_commitment_sha256=_sha("storage"),
            created_record_ids=record_ids,
            source_pairs=((unit.source_id, unit.source_sha256),),
        )

    def cleanup(self, **kwargs):
        self.calls.append("cleanup")
        if self.cleanup_fail_before_commit_once:
            self.cleanup_fail_before_commit_once = False
            raise RuntimeError("crash before cleanup request")
        if self.cleanup_commits == 0:
            self.cleanup_commits = 1
        if self.cleanup_hook is not None:
            self.cleanup_hook()
        if self.cleanup_fail_once:
            self.cleanup_fail_once = False
            raise RuntimeError("lost cleanup response")
        return {"cleanup": kwargs["aborting"]}


class _Head:
    def __init__(self) -> None:
        self.value: str | None = None
        self.fail_next_cas = False

    def load_head(self, **_kwargs) -> str | None:
        return self.value

    def compare_and_swap_head(
        self,
        *,
        expected_commitment_sha256: str | None,
        next_commitment_sha256: str,
        **_kwargs,
    ) -> None:
        if self.value != expected_commitment_sha256:
            raise RuntimeError("simulated checkpoint head conflict")
        if self.fail_next_cas:
            self.fail_next_cas = False
            raise RuntimeError("simulated checkpoint head crash")
        self.value = next_commitment_sha256


class _FailBeforeTerminalSave:
    def __init__(self, inner: ManagedMem0V5CheckpointProgress) -> None:
        self.inner = inner

    def initialize(self, **kwargs):
        return self.inner.initialize(**kwargs)

    def load(self, **kwargs):
        return self.inner.load(**kwargs)

    def advance(self, **kwargs):
        return self.inner.advance(**kwargs)

    def record_seal(self, **kwargs):
        return self.inner.record_seal(**kwargs)

    def record_cleanup_attempt(self, **kwargs):
        return self.inner.record_cleanup_attempt(**kwargs)

    def record_terminal(self, **_kwargs):
        raise RuntimeError("crash before terminal save")


def _request(expected_operation_count: int = 1) -> Mem0OssAdmissionRequest:
    return Mem0OssAdmissionRequest(
        run_id="managed-v5-recovery",
        route_sha256=_sha("route"),
        credential_binding_sha256=_sha("credential"),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="source-r1",
        runtime_source_sha256=_sha("source"),
        runtime_base_sha256=_sha("base"),
        expected_operation_count=expected_operation_count,
    )


def _service(storage: _StoragePort) -> Mem0OssFullRunService:
    return Mem0OssFullRunService(
        manifest_port=ManagedMem0V5ManifestProjector(),
        receipt_port=_ReceiptPort(),
        storage_port=storage,
        cleanup_port=_CleanupPort(),
    )


def _admitted_service(authority) -> Mem0OssFullRunService:
    service = _service(_StoragePort())
    service.admit(
        _request(authority.operation_count),
        manifest_authority_payload=authority,
    )
    service.activate(admission_commitment_sha256=service.admission.commitment_sha256)
    return service


def _progress(path: Path, head: _Head) -> ManagedMem0V5CheckpointProgress:
    os.chmod(path.parent, 0o700)
    signer = HmacSha256ManagedMem0V5CheckpointSigner(key=b"checkpoint-test-key" * 2)
    return ManagedMem0V5CheckpointProgress(
        store=AtomicJsonManagedMem0V5CheckpointStore(path=path, signer=signer),
        signer=signer,
        head=head,
    )


def _coordinator(
    lane: _Lane,
    storage: _StoragePort,
    *,
    progress: ManagedMem0V5CheckpointProgress | None = None,
):
    authority = _authority()
    service = _service(storage)
    coordinator = ManagedMem0V5LaneCoordinator(
        service=service,
        lane_port=lane,
        progress_port=progress,
    )
    coordinator.admit(
        authority=authority,
        request=_request(),
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


def test_fresh_service_restores_attempted_dispatch_without_redispatch(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    head = _Head()
    lane = _Lane(dispatch_fail_once=True)
    first_progress = _progress(checkpoint_path, head)
    authority, first_service, first = _coordinator(
        lane,
        _StoragePort(),
        progress=first_progress,
    )

    with pytest.raises(RuntimeError, match="lost dispatch"):
        first.dispatch_pending()
    persisted = first_progress.load(authority=authority, admission=first_service.admission)
    assert persisted.units[0].phase is ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED

    restored_service = _service(_StoragePort())
    restored_progress = _progress(checkpoint_path, head)
    restored = ManagedMem0V5LaneCoordinator(
        service=restored_service,
        lane_port=lane,
        progress_port=restored_progress,
    )
    loaded = restored.restore(
        authority=authority,
        request=_request(),
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )

    assert loaded.units[0].phase is ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED
    dispatch_calls = lane.calls.count("dispatch")
    seal = restored.seal_restored_completed()
    assert seal.operation_count == 1
    assert lane.calls.count("dispatch") == dispatch_calls
    restored.cleanup()
    assert lane.calls.count("dispatch") == 1
    assert lane.calls.count("status") == 1
    assert lane.calls.count("storage") == 1
    final = restored_progress.load(authority=authority, admission=restored_service.admission)
    assert final.units[0].phase is ManagedMem0V5CheckpointPhase.COMMITTED


def test_progress_adopts_generation_zero_after_head_cas_crash(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    authority = _authority()
    service = _admitted_service(authority)
    head = _Head()
    head.fail_next_cas = True

    with pytest.raises(RuntimeError, match="head crash"):
        _progress(checkpoint_path, head).initialize(
            authority=authority,
            admission=service.admission,
        )

    recovered = _progress(checkpoint_path, head).initialize(
        authority=authority,
        admission=service.admission,
    )
    assert recovered.generation == 0
    assert head.value == recovered.checkpoint_commitment_sha256


def test_progress_adopts_single_successor_after_head_cas_crash(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    authority = _authority()
    service = _admitted_service(authority)
    head = _Head()
    progress = _progress(checkpoint_path, head)
    initial = progress.initialize(authority=authority, admission=service.admission)
    head.fail_next_cas = True

    with pytest.raises(RuntimeError, match="head crash"):
        progress.advance(
            authority=authority,
            admission=service.admission,
            unit_index=0,
            phase=ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED,
        )

    recovered = _progress(checkpoint_path, head).load(
        authority=authority,
        admission=service.admission,
    )
    assert recovered.generation == initial.generation + 1
    assert recovered.previous_checkpoint_commitment_sha256 == initial.checkpoint_commitment_sha256
    assert head.value == recovered.checkpoint_commitment_sha256


def test_progress_rejects_head_that_is_not_current_or_direct_parent(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    authority = _authority()
    service = _admitted_service(authority)
    head = _Head()
    progress = _progress(checkpoint_path, head)
    progress.initialize(authority=authority, admission=service.admission)
    head.value = _sha("unrelated-checkpoint-head")

    with pytest.raises(ManagedRunError, match="progress head differs"):
        progress.load(authority=authority, admission=service.admission)


def test_fresh_restore_keeps_reserved_unit_dispatchable_in_mixed_checkpoint(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    authority = _authority(unit_count=2)
    head = _Head()
    lane = _Lane(zero_record_sequences=(0,))
    service = _service(_StoragePort())
    progress = _progress(checkpoint_path, head)
    coordinator = ManagedMem0V5LaneCoordinator(
        service=service,
        lane_port=lane,
        progress_port=progress,
    )
    coordinator.admit(
        authority=authority,
        request=_request(2),
        budget_policy=ManagedMem0V5BudgetPolicy(6),
    )

    operation_id = service.reserve(unit_index=0)
    coordinator._operation_ids[0] = operation_id
    coordinator._advance(0, ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED)
    service.record_dispatched(unit_index=0)
    coordinator._dispatched.add(0)
    receipt = lane.dispatch(
        authority=authority,
        unit=authority.units[0],
        operation_id_sha256=operation_id,
        admission=service.admission,
    )
    service.verify_dispatch_receipt(unit_index=0, receipt_payload=receipt)
    coordinator._advance_receipt(0)
    coordinator._finish_storage(0, authority.units[0], operation_id)

    fresh_service = _service(_StoragePort())
    fresh_progress = _progress(checkpoint_path, head)
    restored = ManagedMem0V5LaneCoordinator(
        service=fresh_service,
        lane_port=lane,
        progress_port=fresh_progress,
    )
    restored.restore(
        authority=authority,
        request=_request(2),
        budget_policy=ManagedMem0V5BudgetPolicy(6),
    )
    seal = restored.dispatch_pending()

    assert seal.operation_count == 2
    assert lane.calls.count("dispatch") == 2
    assert lane.calls.count("status") == 1
    assert restored.storage_observations[0].created_record_ids == ()
    assert restored.cleanup().residual_record_count == 0
    final = fresh_progress.load(authority=authority, admission=fresh_service.admission)
    assert all(unit.phase is ManagedMem0V5CheckpointPhase.COMMITTED for unit in final.units)


def test_cleanup_response_loss_retries_cleanup_without_status_and_terminal_restart_is_http_free(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    head = _Head()
    lane = _Lane(cleanup_fail_once=True, zero_record_sequences=(0,))
    progress = _progress(checkpoint_path, head)
    authority, service, first = _coordinator(lane, _StoragePort(), progress=progress)
    first.dispatch_pending()

    with pytest.raises(RuntimeError, match="lost cleanup response"):
        first.cleanup()
    attempted = progress.load(authority=authority, admission=service.admission)
    assert attempted.run_phase is ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED
    assert (
        progress.record_cleanup_attempt(
            authority=authority,
            admission=service.admission,
            cleanup_context=attempted.cleanup_context,
            cleanup_request_commitment_sha256=attempted.cleanup_request_commitment_sha256,
            terminal_basis=attempted.terminal_basis,
        )
        == attempted
    )

    signer = HmacSha256ManagedMem0V5CheckpointSigner(key=b"checkpoint-test-key" * 2)
    mutated = ManagedMem0V5Checkpoint.create(
        authority_commitment_sha256=attempted.authority_commitment_sha256,
        admission_commitment_sha256=attempted.admission_commitment_sha256,
        generation=attempted.generation + 1,
        previous_checkpoint_commitment_sha256=attempted.checkpoint_commitment_sha256,
        units=(replace(attempted.units[0], record_ids=("late-record",)),),
        run_phase=ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED,
        seal=attempted.seal,
        cleanup_context=attempted.cleanup_context,
        cleanup_request_commitment_sha256=attempted.cleanup_request_commitment_sha256,
        terminal_basis=attempted.terminal_basis,
        signer=signer,
    )
    with pytest.raises(ManagedMem0V5CheckpointError, match="regression"):
        AtomicJsonManagedMem0V5CheckpointStore(path=checkpoint_path, signer=signer).save(
            mutated,
            expected_previous_commitment_sha256=attempted.checkpoint_commitment_sha256,
        )

    fresh_service = _service(_StoragePort())
    fresh_progress = _progress(checkpoint_path, head)
    fresh = ManagedMem0V5LaneCoordinator(
        service=fresh_service, lane_port=lane, progress_port=fresh_progress
    )
    fresh.restore(
        authority=authority,
        request=_request(),
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )
    terminal = fresh.terminal_evidence
    assert terminal.residual_record_count == 0
    assert lane.cleanup_commits == 1
    assert lane.calls.count("cleanup") == 2
    assert lane.calls.count("status") == 0

    calls = tuple(lane.calls)
    terminal_service = _service(_StoragePort())
    terminal_restart = ManagedMem0V5LaneCoordinator(
        service=terminal_service,
        lane_port=lane,
        progress_port=_progress(checkpoint_path, head),
    )
    terminal_restart.restore(
        authority=authority,
        request=_request(),
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )
    assert terminal_restart.terminal_evidence == terminal
    assert terminal_restart.cleanup() == terminal
    with pytest.raises(ManagedRunError, match="lane is terminal"):
        terminal_restart.dispatch_pending()
    assert tuple(lane.calls) == calls


def test_terminal_checkpoint_saved_before_head_cas_is_adopted_without_cleanup_replay(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    head = _Head()

    def fail_terminal_head() -> None:
        head.fail_next_cas = True

    lane = _Lane(cleanup_hook=fail_terminal_head)
    progress = _progress(checkpoint_path, head)
    authority, service, first = _coordinator(lane, _StoragePort(), progress=progress)
    first.dispatch_pending()
    with pytest.raises(RuntimeError, match="head crash"):
        first.cleanup()

    fresh_service = _service(_StoragePort())
    fresh = ManagedMem0V5LaneCoordinator(
        service=fresh_service,
        lane_port=lane,
        progress_port=_progress(checkpoint_path, head),
    )
    cleanup_calls = lane.calls.count("cleanup")
    fresh.restore(
        authority=authority,
        request=_request(),
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )
    assert fresh.terminal_evidence.residual_record_count == 0
    assert lane.calls.count("cleanup") == cleanup_calls
    assert lane.calls.count("status") == 0


def test_abort_cleanup_response_loss_restarts_without_operation_status(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    head = _Head()
    lane = _Lane(cleanup_fail_once=True)
    progress = _progress(checkpoint_path, head)
    authority, _, first = _coordinator(lane, _StoragePort(), progress=progress)
    with pytest.raises(RuntimeError, match="lost cleanup response"):
        first.abort()

    fresh_service = _service(_StoragePort())
    fresh = ManagedMem0V5LaneCoordinator(
        service=fresh_service,
        lane_port=lane,
        progress_port=_progress(checkpoint_path, head),
    )
    fresh.restore(
        authority=authority,
        request=_request(),
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )
    assert fresh.terminal_evidence.terminal_state == "aborted"
    assert lane.calls.count("cleanup") == 2
    assert lane.calls.count("status") == 0


def test_cleanup_response_verified_before_terminal_save_replays_cleanup_on_restart(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    head = _Head()
    lane = _Lane()
    durable = _progress(checkpoint_path, head)
    authority = _authority()
    service = _service(_StoragePort())
    first = ManagedMem0V5LaneCoordinator(
        service=service,
        lane_port=lane,
        progress_port=_FailBeforeTerminalSave(durable),
    )
    first.admit(
        authority=authority,
        request=_request(),
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )
    first.dispatch_pending()
    with pytest.raises(RuntimeError, match="before terminal save"):
        first.cleanup()
    assert durable.load(authority=authority, admission=service.admission).run_phase is (
        ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED
    )

    fresh_service = _service(_StoragePort())
    fresh = ManagedMem0V5LaneCoordinator(
        service=fresh_service,
        lane_port=lane,
        progress_port=_progress(checkpoint_path, head),
    )
    fresh.restore(
        authority=authority,
        request=_request(),
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )
    assert fresh.terminal_evidence.residual_record_count == 0
    assert lane.calls.count("cleanup") == 2
    assert lane.cleanup_commits == 1
    assert lane.calls.count("status") == 0


def test_cleanup_attempt_checkpoint_precedes_remote_call(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    head = _Head()
    lane = _Lane(cleanup_fail_before_commit_once=True)
    progress = _progress(checkpoint_path, head)
    authority, service, first = _coordinator(lane, _StoragePort(), progress=progress)
    first.dispatch_pending()
    with pytest.raises(RuntimeError, match="before cleanup request"):
        first.cleanup()
    assert lane.cleanup_commits == 0
    assert progress.load(authority=authority, admission=service.admission).run_phase is (
        ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED
    )

    fresh_service = _service(_StoragePort())
    fresh = ManagedMem0V5LaneCoordinator(
        service=fresh_service,
        lane_port=lane,
        progress_port=_progress(checkpoint_path, head),
    )
    fresh.restore(
        authority=authority,
        request=_request(),
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )
    assert fresh.terminal_evidence.residual_record_count == 0
    assert lane.cleanup_commits == 1
    assert lane.calls.count("cleanup") == 2
    assert lane.calls.count("status") == 0


def test_sealed_progress_freezes_units_and_exact_record_seal_is_idempotent(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    head = _Head()
    progress = _progress(checkpoint_path, head)
    authority, service, coordinator = _coordinator(
        _Lane(zero_record_sequences=(0,)),
        _StoragePort(),
        progress=progress,
    )
    seal = coordinator.dispatch_pending()
    sealed = progress.load(authority=authority, admission=service.admission)

    assert (
        progress.record_seal(authority=authority, admission=service.admission, seal=seal) == sealed
    )
    with pytest.raises(ManagedRunError, match="units are sealed"):
        progress.advance(
            authority=authority,
            admission=service.admission,
            unit_index=0,
            phase=ManagedMem0V5CheckpointPhase.COMMITTED,
            provider_receipt_commitment_sha256=sealed.units[0].provider_receipt_commitment_sha256,
            observation_commitment_sha256=sealed.units[0].observation_commitment_sha256,
            record_ids=sealed.units[0].record_ids,
        )
    assert progress.load(authority=authority, admission=service.admission) == sealed


def test_cleanup_attempt_rejects_count_mismatch_before_checkpoint_write(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    head = _Head()
    progress = _progress(checkpoint_path, head)
    authority, service, coordinator = _coordinator(_Lane(), _StoragePort(), progress=progress)
    coordinator.dispatch_pending()
    service.begin_delete()
    context = service.cleanup_verification_context(aborting=False)
    wrong_context = replace(context, expected_operation_count=2)
    wrong_basis = replace(service.terminal_basis(aborting=False), cleanup_context=wrong_context)
    before = progress.load(authority=authority, admission=service.admission)

    with pytest.raises(ManagedRunError, match="cleanup binding differs"):
        progress.record_cleanup_attempt(
            authority=authority,
            admission=service.admission,
            cleanup_context=wrong_context,
            cleanup_request_commitment_sha256=cleanup_request_commitment(wrong_context),
            terminal_basis=wrong_basis,
        )
    wrong_totals = replace(
        service.terminal_basis(aborting=False),
        provider_observed_request_tokens=(
            service.terminal_basis(aborting=False).provider_observed_request_tokens + 1
        ),
    )
    with pytest.raises(ManagedRunError, match="cleanup binding differs"):
        progress.record_cleanup_attempt(
            authority=authority,
            admission=service.admission,
            cleanup_context=context,
            cleanup_request_commitment_sha256=cleanup_request_commitment(context),
            terminal_basis=wrong_totals,
        )
    assert progress.load(authority=authority, admission=service.admission) == before


def test_strict_checkpoint_parser_rejects_signed_cleanup_count_mismatch(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "managed-v5-checkpoint.json"
    head = _Head()
    progress = _progress(checkpoint_path, head)
    authority, service, coordinator = _coordinator(_Lane(), _StoragePort(), progress=progress)
    coordinator.dispatch_pending()
    service.begin_delete()
    context = service.cleanup_verification_context(aborting=False)
    progress.record_cleanup_attempt(
        authority=authority,
        admission=service.admission,
        cleanup_context=context,
        cleanup_request_commitment_sha256=cleanup_request_commitment(context),
        terminal_basis=service.terminal_basis(aborting=False),
    )
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    wrong_context = replace(context, expected_operation_count=2)
    payload["cleanup_context"]["expected_operation_count"] = 2
    payload["terminal_basis"]["cleanup_context"]["expected_operation_count"] = 2
    payload["cleanup_request_commitment_sha256"] = cleanup_request_commitment(wrong_context)
    base = {
        key: value
        for key, value in payload.items()
        if key not in {"checkpoint_commitment_sha256", "checkpoint_hmac_sha256"}
    }
    payload["checkpoint_commitment_sha256"] = canonical_sha256(base)
    signer = HmacSha256ManagedMem0V5CheckpointSigner(key=b"checkpoint-test-key" * 2)
    payload["checkpoint_hmac_sha256"] = signer.sign(
        checkpoint_module._signed_bytes(
            {**base, "checkpoint_commitment_sha256": payload["checkpoint_commitment_sha256"]}
        )
    )
    checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")

    store = AtomicJsonManagedMem0V5CheckpointStore(path=checkpoint_path, signer=signer)
    with pytest.raises(ManagedMem0V5CheckpointError, match="run_invalid"):
        store.load(
            expected_authority_commitment_sha256=authority.authority_commitment_sha256,
            expected_admission_commitment_sha256=service.admission.commitment_sha256,
        )
