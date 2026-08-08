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


def test_split_cleanup_retries_without_journal_change_or_new_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _case = _authority_and_case()
    terminal = _terminal(authority, "a" * 64)
    lifecycle = _Lifecycle(terminal)
    adapter = object.__new__(ManagedMem0V5ProductionLifecycleAdapter)
    current = subject._LifecycleState(
        descriptor=object(),
        binding=object(),
        composition=object(),
        paired_runtime_bundle=object(),
        lifecycle=lifecycle,
        evidence=object(),
        journal=object(),
        journal_identity=object(),
        operation_manifest=object(),
        receipt_authority=object(),
        phase="ready",
        receipts=(),
        snapshot=object(),
        cleanup_terminal=None,
        cleanup_request=None,
        integrity_mac=b"",
    )
    lock = threading.RLock()
    journal_snapshot = object()

    def state(_adapter: object):
        return current

    def require(_adapter: object, allowed: set[str], suffix: str):
        if current.phase not in allowed:
            raise ManagedMem0V5ProductionLifecycleError(suffix)
        return current

    def store(_adapter: object, value: object) -> None:
        nonlocal current
        current = value

    monkeypatch.setattr(subject, "_instance_lock", lambda _adapter: lock)
    monkeypatch.setattr(subject, "_state", state)
    monkeypatch.setattr(subject, "_require_phase", require)
    monkeypatch.setattr(subject, "_store", store)
    monkeypatch.setattr(
        subject,
        "_validated_cleanup_journal_snapshot",
        lambda _state: journal_snapshot,
    )
    monkeypatch.setattr(subject, "ManagedMem0V5CleanupReadbackWitness", _Witness)

    with pytest.raises(ManagedMem0V5ProductionLifecycleError, match="pass_one_failed"):
        adapter.cleanup_pass_one()
    assert current.phase == "cleanup_retry"
    assert adapter.cleanup_pass_one() is terminal
    retained_request = current.cleanup_request
    assert retained_request is not None

    with pytest.raises(ManagedMem0V5ProductionLifecycleError, match="pass_two_failed"):
        adapter.cleanup_pass_two()
    assert current.phase == "cleanup_pass_two_retry"
    assert current.cleanup_request is retained_request
    assert type(adapter.cleanup_pass_two()) is _Witness
    assert current.phase == "terminal"
    assert lifecycle.pass_one_calls == 2
    assert lifecycle.pass_two_calls == 2
    assert lifecycle.request is retained_request
