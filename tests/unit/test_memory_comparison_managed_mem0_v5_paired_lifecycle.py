from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    ManagedMem0V5RunPhase,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import Mem0OssFullRunState
from test_memory_comparison_managed_mem0_v5_paired_bridge import (
    _checkpoint,
    _run,
    _sha,
    _terminal,
)


def test_cleanup_rejects_foreign_terminal() -> None:
    authority, coordinator, run = _run()
    run.start()
    foreign = replace(
        _terminal(authority, coordinator.admission),
        admission_commitment_sha256=_sha("foreign"),
    )
    coordinator.cleanup = lambda: foreign  # type: ignore[method-assign]
    with pytest.raises(ManagedRunError, match="terminal binding differs"):
        run.cleanup()


def test_cleanup_failure_retries_without_reopening_run() -> None:
    _authority_value, coordinator, run = _run()
    run.start()
    coordinator.cleanup_failures = 1
    with pytest.raises(RuntimeError, match="cleanup failed"):
        run.cleanup()
    terminal = run.cleanup()
    assert terminal.terminal_state == Mem0OssFullRunState.DELETED.value
    assert coordinator.cleanup_calls == 2
    assert coordinator.admit_calls == coordinator.dispatch_calls == 1


def test_cached_deleted_cleanup_revalidates_mutated_terminal() -> None:
    _authority_value, _coordinator, run = _run()
    run.start()
    terminal = run.cleanup()
    object.__setattr__(terminal, "operation_root_sha256", _sha("mutated-root"))
    with pytest.raises(ManagedRunError, match="terminal binding differs"):
        run.cleanup()


def test_abort_failure_has_explicit_retry_without_redispatch() -> None:
    _authority_value, coordinator, run = _run()
    coordinator.dispatch_failures = coordinator.abort_failures = 1
    with pytest.raises(RuntimeError, match="dispatch failed"):
        run.start()
    terminal = run.retry_abort()
    assert terminal.terminal_state == Mem0OssFullRunState.ABORTED.value
    assert coordinator.abort_calls == 2
    assert coordinator.admit_calls == coordinator.dispatch_calls == 1


def test_successful_start_abort_is_not_cached_as_deleted_cleanup() -> None:
    _authority_value, coordinator, run = _run()
    coordinator.dispatch_failures = 1
    with pytest.raises(RuntimeError, match="dispatch failed"):
        run.start()
    with pytest.raises(ManagedRunError, match="cleanup terminal is not deleted"):
        run.cleanup()
    assert coordinator.abort_calls == 1


def test_cached_aborted_cleanup_cannot_be_mutated_into_deleted() -> None:
    _authority_value, coordinator, run = _run()
    coordinator.dispatch_failures = 1
    with pytest.raises(RuntimeError, match="dispatch failed"):
        run.start()
    terminal = coordinator.terminal_evidence
    object.__setattr__(terminal, "terminal_state", Mem0OssFullRunState.DELETED.value)
    object.__setattr__(run, "_terminal", terminal)
    with pytest.raises(ManagedRunError, match="terminal binding differs"):
        run.cleanup()


def test_active_restore_dispatch_failure_retries_only_abort() -> None:
    _authority_value, coordinator, run = _run()
    coordinator.restore_phase = ManagedMem0V5RunPhase.ACTIVE
    coordinator.dispatch_failures = coordinator.abort_failures = 1
    with pytest.raises(RuntimeError, match="dispatch failed"):
        run.restore()
    terminal = run.retry_abort()
    assert terminal.terminal_state == Mem0OssFullRunState.ABORTED.value
    assert coordinator.restore_calls == coordinator.dispatch_calls == 1
    assert coordinator.abort_calls == 2


def test_restore_revalidates_forged_exact_checkpoint_dto() -> None:
    authority, coordinator, run = _run()
    checkpoint = _checkpoint(authority, coordinator.admission, ManagedMem0V5RunPhase.SEALED)
    object.__setattr__(checkpoint, "units", ())
    coordinator.restore = lambda **kwargs: checkpoint  # type: ignore[method-assign]
    with pytest.raises(ManagedRunError, match="checkpoint binding differs"):
        run.restore()


def test_cleanup_rejects_divergent_seal_or_residual_terminal() -> None:
    authority, coordinator, run = _run()
    run.start()
    terminal = _terminal(authority, coordinator.admission)
    object.__setattr__(terminal, "seal_commitment_sha256", _sha("divergent-seal"))
    object.__setattr__(terminal, "operation_root_sha256", _sha("divergent-root"))
    coordinator.cleanup = lambda: terminal  # type: ignore[method-assign]
    with pytest.raises(ManagedRunError, match="terminal binding differs"):
        run.cleanup()

    _authority_value, coordinator, run = _run()
    run.start()
    residual = _terminal(authority, coordinator.admission)
    object.__setattr__(residual, "residual_record_count", 1)
    object.__setattr__(residual, "residual_root_sha256", _sha("residual"))
    coordinator.cleanup = lambda: residual  # type: ignore[method-assign]
    with pytest.raises(ManagedRunError, match="terminal binding differs"):
        run.cleanup()


def test_two_thread_start_dispatches_once() -> None:
    _authority_value, coordinator, run = _run()
    coordinator.start_gate = threading.Event()
    coordinator.release_gate = threading.Event()
    outcomes: list[type[BaseException] | str] = []

    def start() -> None:
        try:
            run.start()
            outcomes.append("sealed")
        except BaseException as error:
            outcomes.append(type(error))

    first = threading.Thread(target=start)
    second = threading.Thread(target=start)
    first.start()
    assert coordinator.start_gate.wait(timeout=2)
    second.start()
    coordinator.release_gate.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert sorted(str(item) for item in outcomes) == sorted(("sealed", str(ManagedRunError)))
    assert coordinator.admit_calls == coordinator.dispatch_calls == 1


def test_search_and_cleanup_are_serialized() -> None:
    authority, coordinator, run = _run()
    run.start()
    coordinator.start_gate = threading.Event()
    coordinator.release_gate = threading.Event()
    order: list[str] = []

    def search() -> None:
        run.search(corpus_id=authority.units[0].corpus_id, query="query", top_k=1)
        order.append("search")

    def cleanup() -> None:
        run.cleanup()
        order.append("cleanup")

    search_thread = threading.Thread(target=search)
    cleanup_thread = threading.Thread(target=cleanup)
    search_thread.start()
    assert coordinator.start_gate.wait(timeout=2)
    cleanup_thread.start()
    coordinator.release_gate.set()
    search_thread.join(timeout=2)
    cleanup_thread.join(timeout=2)
    assert order == ["search", "cleanup"]
    assert coordinator.search_calls == [1]
    assert coordinator.cleanup_calls == 1
