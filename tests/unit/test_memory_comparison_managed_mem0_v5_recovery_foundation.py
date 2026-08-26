from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    ManagedMem0V5Checkpoint,
    ManagedMem0V5RunPhase,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_recovery import (
    ManagedMem0V5RecoveryError,
    recover_managed_mem0_v5,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_recovery_cleanup_readback import (
    ManagedMem0V5RecoveryCleanupReadback,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    CleanupVerificationContext,
    CleanupVerificationResult,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssTerminalCleanupEvidence,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanupReceipt,
    Mem0V5CleanupRequest,
    Mem0V5HttpError,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    cleanup_request_commitment,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _terminal(*, aborted: bool, deleted: int = 0) -> Mem0OssTerminalCleanupEvidence:
    return Mem0OssTerminalCleanupEvidence(
        terminal_state="aborted" if aborted else "deleted",
        admission_commitment_sha256=_sha("admission"),
        seal_commitment_sha256=None if aborted else _sha("seal"),
        operation_root_sha256=None if aborted else _sha("operations"),
        operation_inventory_root_sha256=_sha("inventory"),
        deleted_operation_count=deleted,
        residual_record_count=0,
        residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
        provider_observed_extraction_calls=0,
        provider_observed_request_tokens=0,
        provider_observed_response_tokens=0,
        failed_receipts=(),
    )


def _checkpoint(phase: ManagedMem0V5RunPhase) -> ManagedMem0V5Checkpoint:
    checkpoint = object.__new__(ManagedMem0V5Checkpoint)
    object.__setattr__(checkpoint, "run_phase", phase)
    return checkpoint


class _Coordinator:
    def __init__(self, phase: ManagedMem0V5RunPhase) -> None:
        self.phase = phase
        self.calls: list[str] = []
        self._terminal = _terminal(
            aborted=phase is ManagedMem0V5RunPhase.ACTIVE,
            deleted=0 if phase is ManagedMem0V5RunPhase.ACTIVE else 2,
        )

    def restore(self, **_kwargs: object) -> ManagedMem0V5Checkpoint:
        self.calls.append("restore")
        return _checkpoint(self.phase)

    def abort(self) -> Mem0OssTerminalCleanupEvidence:
        self.calls.append("abort")
        return self._terminal

    def seal_restored_completed(self) -> object:
        self.calls.append("seal_restored_completed")
        return object()

    def cleanup(self) -> Mem0OssTerminalCleanupEvidence:
        self.calls.append("cleanup")
        return self._terminal

    @property
    def terminal_evidence(self) -> Mem0OssTerminalCleanupEvidence:
        self.calls.append("terminal_evidence")
        return self._terminal

    def dispatch_pending(self) -> None:
        raise AssertionError("dispatch is forbidden during recovery")


@pytest.mark.parametrize(
    ("phase", "calls", "action"),
    (
        (ManagedMem0V5RunPhase.ACTIVE, ["restore", "abort"], "active_aborted"),
        (
            ManagedMem0V5RunPhase.SEALED,
            ["restore", "seal_restored_completed", "cleanup"],
            "sealed_cleaned",
        ),
        (
            ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED,
            ["restore", "terminal_evidence"],
            "cleanup_resumed",
        ),
        (
            ManagedMem0V5RunPhase.TERMINAL,
            ["restore", "terminal_evidence"],
            "terminal_authenticated",
        ),
    ),
)
def test_restore_states_never_dispatch(
    phase: ManagedMem0V5RunPhase, calls: list[str], action: str
) -> None:
    coordinator = _Coordinator(phase)
    result = recover_managed_mem0_v5(
        coordinator=coordinator,
        authority=object(),
        request=object(),
        budget_policy=object(),
        execution_started=True,
    )
    assert result.action == action
    assert coordinator.calls == calls


def test_missing_checkpoint_is_returned_for_upper_absence_policy() -> None:
    class Missing(_Coordinator):
        def restore(self, **_kwargs: object) -> ManagedMem0V5Checkpoint:
            raise FileNotFoundError

    allowed = recover_managed_mem0_v5(
        coordinator=Missing(ManagedMem0V5RunPhase.ACTIVE),
        authority=object(),
        request=object(),
        budget_policy=object(),
        execution_started=False,
    )
    assert allowed.action == "missing_pre_execution"
    marked = recover_managed_mem0_v5(
        coordinator=Missing(ManagedMem0V5RunPhase.ACTIVE),
        authority=object(),
        request=object(),
        budget_policy=object(),
        execution_started=True,
    )
    assert marked.action == "missing_pre_execution"


@pytest.mark.parametrize(
    ("code", "expected"),
    (
        ("mem0_v5_http_remote_failed", "restore_transient"),
        ("mem0_v5_http_response_rejected", "restore_failed"),
        ("mem0_v5_http_response_invalid", "restore_failed"),
    ),
)
def test_restore_transport_classification_is_stable(code: str, expected: str) -> None:
    class Failed(_Coordinator):
        def restore(self, **_kwargs: object) -> ManagedMem0V5Checkpoint:
            raise Mem0V5HttpError(code)

    with pytest.raises(ManagedMem0V5RecoveryError, match=expected):
        recover_managed_mem0_v5(
            coordinator=Failed(ManagedMem0V5RunPhase.ACTIVE),
            authority=object(),
            request=object(),
            budget_policy=object(),
            execution_started=True,
        )


def _cleanup_authority(*, aborted: bool, deleted: int):
    context = CleanupVerificationContext(
        _sha("admission"),
        None if aborted else _sha("seal"),
        None if aborted else _sha("operations"),
        _sha("inventory"),
        4,
        aborted,
    )
    request = Mem0V5CleanupRequest(
        context.admission_commitment_sha256,
        context.seal_commitment_sha256,
        context.operation_root_sha256,
        context.operation_inventory_root_sha256,
        context.expected_operation_count,
        context.aborting,
        canonical_sha256({"kind": "cleanup", "binding": cleanup_request_commitment(context)}),
    )
    result = CleanupVerificationResult(
        context.admission_commitment_sha256,
        context.seal_commitment_sha256,
        context.operation_root_sha256,
        context.operation_inventory_root_sha256,
        deleted,
        0,
        MEM0_OSS_EMPTY_ROOT_SHA256,
    )
    receipt = Mem0V5CleanupReceipt(
        result.admission_commitment_sha256,
        result.seal_commitment_sha256,
        result.operation_root_sha256,
        result.operation_inventory_root_sha256,
        result.deleted_operation_count,
        result.residual_record_count,
        result.residual_root_sha256,
    )
    terminal = _terminal(aborted=aborted, deleted=deleted)
    return request, result, receipt, terminal


@pytest.mark.parametrize(("aborted", "deleted"), ((True, 0), (False, 0), (False, 4)))
def test_recovery_pass_two_allows_bounded_zero_delete_and_empty_residual(
    aborted: bool, deleted: int
) -> None:
    request, result, receipt, terminal = _cleanup_authority(aborted=aborted, deleted=deleted)
    cleanup = SimpleNamespace(cleanup=lambda actual: receipt if actual is request else None)
    verifier = SimpleNamespace(verify=lambda **_kwargs: result)
    adapter = ManagedMem0V5RecoveryCleanupReadback(
        cleanup_port=cleanup,
        verification_port=verifier,
        hmac_secret=b"r" * 64,
    )
    witness = adapter.readback(request=request, terminal=terminal)
    assert witness.aborting is aborted
    assert witness.deleted_operation_count == deleted
    assert witness.residual_record_count == 0
    assert adapter.authenticate(witness)
    with pytest.raises(Exception, match="replayed"):
        adapter.readback(request=request, terminal=terminal)


@pytest.mark.parametrize(
    "terminal",
    (
        replace(_terminal(aborted=True), deleted_operation_count=5),
        replace(_terminal(aborted=True), provider_observed_extraction_calls=5),
    ),
)
def test_recovery_pass_two_rejects_unbounded_terminal_counts(
    terminal: Mem0OssTerminalCleanupEvidence,
) -> None:
    request, result, receipt, _valid_terminal = _cleanup_authority(aborted=True, deleted=0)
    adapter = ManagedMem0V5RecoveryCleanupReadback(
        cleanup_port=SimpleNamespace(cleanup=lambda _actual: receipt),
        verification_port=SimpleNamespace(verify=lambda **_kwargs: result),
        hmac_secret=b"r" * 64,
    )
    with pytest.raises(Exception, match="authority_mismatch"):
        adapter.readback(request=request, terminal=terminal)
