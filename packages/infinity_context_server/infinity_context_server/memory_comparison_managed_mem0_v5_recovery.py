"""Restore-only Mem0 v5 recovery policy with no dispatch capability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    ManagedMem0V5Checkpoint,
    ManagedMem0V5RunPhase,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssTerminalCleanupEvidence,
)


class ManagedMem0V5RecoveryError(RuntimeError):
    """Stable recovery failure without provider or secret material."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ManagedMem0V5RecoveryCoordinatorPort(Protocol):
    def restore(self, *, authority: object, request: object, budget_policy: object) -> object: ...
    def abort(self) -> object: ...
    def seal_restored_completed(self) -> object: ...
    def cleanup(self) -> object: ...

    @property
    def terminal_evidence(self) -> object: ...


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5RecoveryResult:
    checkpoint_phase: str
    action: str
    terminal: Mem0OssTerminalCleanupEvidence | None

    def __post_init__(self) -> None:
        if (
            self.checkpoint_phase
            not in {phase.value for phase in ManagedMem0V5RunPhase} | {"missing"}
            or self.action
            not in {
                "missing_pre_execution",
                "active_aborted",
                "sealed_cleaned",
                "cleanup_resumed",
                "terminal_authenticated",
            }
            or (
                self.action == "missing_pre_execution"
                and (self.checkpoint_phase != "missing" or self.terminal is not None)
            )
            or (
                self.action != "missing_pre_execution"
                and type(self.terminal) is not Mem0OssTerminalCleanupEvidence
            )
        ):
            _fail("managed_mem0_v5_recovery_result_invalid")


def recover_managed_mem0_v5(
    *,
    coordinator: ManagedMem0V5RecoveryCoordinatorPort,
    authority: object,
    request: object,
    budget_policy: object,
    execution_started: bool,
) -> ManagedMem0V5RecoveryResult:
    """Restore a fresh coordinator and terminalize without ever dispatching."""

    if type(execution_started) is not bool or not callable(getattr(coordinator, "restore", None)):
        _fail("managed_mem0_v5_recovery_inputs_invalid")
    try:
        checkpoint = coordinator.restore(
            authority=authority,
            request=request,
            budget_policy=budget_policy,
        )
    except FileNotFoundError:
        return ManagedMem0V5RecoveryResult("missing", "missing_pre_execution", None)
    except ManagedMem0V5RecoveryError:
        raise
    except Exception as error:
        _fail(
            "managed_mem0_v5_recovery_restore_transient"
            if _transient(error)
            else "managed_mem0_v5_recovery_restore_failed"
        )
    if type(checkpoint) is not ManagedMem0V5Checkpoint:
        _fail("managed_mem0_v5_recovery_checkpoint_invalid")
    phase = checkpoint.run_phase
    try:
        if phase is ManagedMem0V5RunPhase.ACTIVE:
            terminal = coordinator.abort()
            action = "active_aborted"
        elif phase is ManagedMem0V5RunPhase.SEALED:
            coordinator.seal_restored_completed()
            terminal = coordinator.cleanup()
            action = "sealed_cleaned"
        elif phase is ManagedMem0V5RunPhase.CLEANUP_ATTEMPTED:
            terminal = coordinator.terminal_evidence
            action = "cleanup_resumed"
        elif phase is ManagedMem0V5RunPhase.TERMINAL:
            terminal = coordinator.terminal_evidence
            action = "terminal_authenticated"
        else:
            _fail("managed_mem0_v5_recovery_phase_invalid")
        if type(terminal) is not Mem0OssTerminalCleanupEvidence:
            _fail("managed_mem0_v5_recovery_terminal_invalid")
        terminal.__post_init__()
        return ManagedMem0V5RecoveryResult(phase.value, action, terminal)
    except ManagedMem0V5RecoveryError:
        raise
    except Exception as error:
        _fail(
            "managed_mem0_v5_recovery_terminalization_transient"
            if _transient(error)
            else "managed_mem0_v5_recovery_terminalization_failed"
        )


def _transient(error: BaseException) -> bool:
    current: BaseException | None = error
    for _index in range(8):
        if current is None:
            break
        if "mem0_v5_http_remote_failed" in str(current):
            return True
        current = current.__cause__ or current.__context__
    return False


def _fail(code: str) -> None:
    raise ManagedMem0V5RecoveryError(code)


__all__ = (
    "ManagedMem0V5RecoveryCoordinatorPort",
    "ManagedMem0V5RecoveryError",
    "ManagedMem0V5RecoveryResult",
    "recover_managed_mem0_v5",
)
