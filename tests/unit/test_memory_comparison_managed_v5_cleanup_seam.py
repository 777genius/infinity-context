from __future__ import annotations

import threading

import pytest
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_production_lifecycle as subject,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_cleanup_readback import (
    validate_managed_mem0_v5_cleanup_readback_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5ProductionLifecycleAdapter,
    ManagedMem0V5ProductionLifecycleError,
)
from infinity_context_server.memory_comparison_managed_v5_live_private_dependencies import (
    ManagedMem0V5OperationReceiptAuthority,
)
from infinity_context_server.resumable_operation_journal.domain import (
    LogicalOperationIdentity,
    OperationManifest,
)
from test_memory_comparison_managed_mem0_v5_paired_bridge import _terminal
from test_memory_comparison_managed_mem0_v5_runner_foundation import _authority_and_case


class _Witness:
    def public_payload(self) -> dict[str, object]:
        return {
            "residual_record_count": 0,
            "residual_root_sha256": "0" * 64,
        }


class _Lifecycle:
    def __init__(self, terminal: object) -> None:
        self.terminal = terminal
        self.pass_one_calls = 0
        self.pass_two_calls = 0
        self.request = None

    def cleanup_pass1(self) -> object:
        self.pass_one_calls += 1
        if self.pass_one_calls == 1:
            raise RuntimeError("provider-secret")
        return self.terminal

    def cleanup_pass2(self, *, request: object) -> object:
        self.pass_two_calls += 1
        self.request = request
        validate_managed_mem0_v5_cleanup_readback_authority(
            request=request,
            terminal=self.terminal,
        )
        if self.pass_two_calls == 1:
            raise RuntimeError("readback-secret")
        return _Witness()


class _InvalidResultLifecycle:
    def __init__(self, terminal: object, *, invalid_pass: int) -> None:
        self.terminal = terminal
        self.invalid_pass = invalid_pass
        self.pass_one_calls = 0
        self.pass_two_calls = 0

    def cleanup_pass1(self) -> object:
        self.pass_one_calls += 1
        return object() if self.invalid_pass == 1 else self.terminal

    def cleanup_pass2(self, *, request: object) -> object:
        del request
        self.pass_two_calls += 1
        return object() if self.invalid_pass == 2 else _Witness()


def _facade(
    monkeypatch: pytest.MonkeyPatch,
    lifecycle: object,
    *,
    journal_snapshots: list[object] | None = None,
) -> tuple[ManagedMem0V5ProductionLifecycleAdapter, list[subject._LifecycleState]]:
    adapter = object.__new__(ManagedMem0V5ProductionLifecycleAdapter)
    operation_manifest = OperationManifest(
        (
            LogicalOperationIdentity(
                run_id="managed-v5-cleanup-seam",
                operation_key="cleanup-seam-operation",
                operation_kind="managed_mem0_v5_extraction",
                ordinal=0,
                authority_commitment_sha256="a" * 64,
            ),
        )
    )
    operation_receipt_authority = ManagedMem0V5OperationReceiptAuthority(
        key=b"c" * 32,
        key_id="cleanup-seam-receipt-v1",
        manifest=operation_manifest,
    )
    states = [
        subject._LifecycleState(
            descriptor=object(),
            binding=object(),
            composition=object(),
            paired_runtime_bundle=object(),
            lifecycle=lifecycle,
            evidence=object(),
            journal=object(),
            journal_identity=object(),
            operation_manifest=operation_manifest,
            operation_receipt_authority=operation_receipt_authority,
            receipt_authority=object(),
            phase="ready",
            receipts=(),
            snapshot=object(),
            cleanup_terminal=None,
            cleanup_request=None,
            integrity_mac=b"",
        )
    ]
    lock = threading.RLock()
    journal_snapshot = object()

    def snapshot(_state: object) -> object:
        if journal_snapshots:
            return journal_snapshots.pop(0)
        return journal_snapshot

    def state(_adapter: object) -> subject._LifecycleState:
        return states[0]

    def require(
        _adapter: object,
        allowed: set[str],
        suffix: str,
    ) -> subject._LifecycleState:
        if states[0].phase not in allowed:
            raise ManagedMem0V5ProductionLifecycleError(suffix)
        return states[0]

    def store(_adapter: object, value: subject._LifecycleState) -> None:
        states[0] = value

    monkeypatch.setattr(subject, "_instance_lock", lambda _adapter: lock)
    monkeypatch.setattr(subject, "_state", state)
    monkeypatch.setattr(subject, "_require_phase", require)
    monkeypatch.setattr(subject, "_store", store)
    monkeypatch.setattr(
        subject,
        "_validated_cleanup_journal_snapshot",
        snapshot,
    )
    monkeypatch.setattr(subject, "ManagedMem0V5CleanupReadbackWitness", _Witness)
    return adapter, states


def test_split_cleanup_retries_without_journal_change_or_new_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _case = _authority_and_case()
    terminal = _terminal(authority, "a" * 64)
    lifecycle = _Lifecycle(terminal)
    adapter, states = _facade(monkeypatch, lifecycle)

    with pytest.raises(ManagedMem0V5ProductionLifecycleError, match="pass_one_failed"):
        adapter.cleanup_pass_one()
    assert states[0].phase == "cleanup_retry"
    assert adapter.cleanup_pass_one() is terminal
    retained_request = states[0].cleanup_request
    assert retained_request is not None

    with pytest.raises(ManagedMem0V5ProductionLifecycleError, match="pass_two_failed"):
        adapter.cleanup_pass_two()
    assert states[0].phase == "cleanup_pass_two_retry"
    assert states[0].cleanup_request is retained_request
    assert type(adapter.cleanup_pass_two()) is _Witness
    assert states[0].phase == "terminal"
    assert lifecycle.pass_one_calls == 2
    assert lifecycle.pass_two_calls == 2
    assert lifecycle.request is retained_request


def test_cleanup_pass_one_result_error_terminalizes_integrity_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _case = _authority_and_case()
    terminal = _terminal(authority, "a" * 64)
    lifecycle = _InvalidResultLifecycle(terminal, invalid_pass=1)
    adapter, states = _facade(
        monkeypatch,
        lifecycle,
    )

    with pytest.raises(
        ManagedMem0V5ProductionLifecycleError,
        match="cleanup_pass_one_result_invalid",
    ):
        adapter.cleanup_pass_one()
    assert states[0].phase == "cleanup_integrity_failed"
    with pytest.raises(
        ManagedMem0V5ProductionLifecycleError,
        match="cleanup_pass_one_invalid",
    ):
        adapter.cleanup_pass_one()
    assert lifecycle.pass_one_calls == 1


def test_cleanup_pass_two_result_error_terminalizes_integrity_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _case = _authority_and_case()
    terminal = _terminal(authority, "a" * 64)
    lifecycle = _InvalidResultLifecycle(terminal, invalid_pass=2)
    adapter, states = _facade(
        monkeypatch,
        lifecycle,
    )
    adapter.cleanup_pass_one()

    with pytest.raises(
        ManagedMem0V5ProductionLifecycleError,
        match="cleanup_pass_two_result_invalid",
    ):
        adapter.cleanup_pass_two()
    assert states[0].phase == "cleanup_integrity_failed"
    with pytest.raises(
        ManagedMem0V5ProductionLifecycleError,
        match="cleanup_pass_two_invalid",
    ):
        adapter.cleanup_pass_two()
    assert lifecycle.pass_two_calls == 1


def test_cleanup_pass_one_journal_change_terminalizes_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _case = _authority_and_case()
    terminal = _terminal(authority, "a" * 64)
    lifecycle = _InvalidResultLifecycle(terminal, invalid_pass=0)
    adapter, states = _facade(
        monkeypatch,
        lifecycle,
        journal_snapshots=[object(), object()],
    )

    with pytest.raises(
        ManagedMem0V5ProductionLifecycleError,
        match="cleanup_pass_one_journal_changed",
    ):
        adapter.cleanup_pass_one()
    assert states[0].phase == "cleanup_integrity_failed"
    with pytest.raises(
        ManagedMem0V5ProductionLifecycleError,
        match="cleanup_pass_one_invalid",
    ):
        adapter.cleanup_pass_one()
    assert lifecycle.pass_one_calls == 1


def test_cleanup_pass_two_journal_change_terminalizes_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _case = _authority_and_case()
    terminal = _terminal(authority, "a" * 64)
    lifecycle = _InvalidResultLifecycle(terminal, invalid_pass=0)
    stable = object()
    adapter, states = _facade(
        monkeypatch,
        lifecycle,
        journal_snapshots=[stable, stable, object(), object()],
    )
    adapter.cleanup_pass_one()

    with pytest.raises(
        ManagedMem0V5ProductionLifecycleError,
        match="cleanup_pass_two_journal_changed",
    ):
        adapter.cleanup_pass_two()
    assert states[0].phase == "cleanup_integrity_failed"
    with pytest.raises(
        ManagedMem0V5ProductionLifecycleError,
        match="cleanup_pass_two_invalid",
    ):
        adapter.cleanup_pass_two()
    assert lifecycle.pass_two_calls == 1
