"""Public recovery DTOs for the trusted Mem0 OSS v5 run service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunError,
    Mem0OssFullRunState,
    Mem0OssOperationState,
    is_sha256,
)


@final
@dataclass(frozen=True, slots=True)
class Mem0OssOperationRecoveryState:
    """Read-only durable operation facts needed to resume without redispatch."""

    unit_index: int
    operation_id_sha256: str
    state: Mem0OssOperationState
    stored_identity_sha256: str | None
    stored_record_count: int

    def __post_init__(self) -> None:
        has_verified_storage = self.state in {
            Mem0OssOperationState.STORAGE_VERIFIED,
            Mem0OssOperationState.COMMITTED,
        }
        if (
            type(self.unit_index) is not int
            or self.unit_index < 0
            or not is_sha256(self.operation_id_sha256)
            or type(self.state) is not Mem0OssOperationState
            or type(self.stored_record_count) is not int
            or self.stored_record_count < 0
            or (has_verified_storage and not is_sha256(self.stored_identity_sha256))
            or (not has_verified_storage and self.stored_identity_sha256 is not None)
        ):
            raise Mem0OssFullRunError("mem0_v5_operation_recovery_state_invalid")


class _RecoveryOperation(Protocol):
    operation_id_sha256: str
    state: Mem0OssOperationState
    stored_identity_sha256: str | None
    stored_record_count: int


def operation_recovery_states(
    run_state: Mem0OssFullRunState,
    operations: Mapping[int, _RecoveryOperation],
) -> tuple[Mem0OssOperationRecoveryState, ...]:
    if run_state not in {
        Mem0OssFullRunState.ACTIVE,
        Mem0OssFullRunState.RECONCILIATION_REQUIRED,
    }:
        raise Mem0OssFullRunError("mem0_v5_recovery_state_invalid")
    return tuple(
        Mem0OssOperationRecoveryState(
            unit_index=index,
            operation_id_sha256=operation.operation_id_sha256,
            state=operation.state,
            stored_identity_sha256=operation.stored_identity_sha256,
            stored_record_count=operation.stored_record_count,
        )
        for index, operation in sorted(operations.items())
    )


__all__ = ("Mem0OssOperationRecoveryState", "operation_recovery_states")
