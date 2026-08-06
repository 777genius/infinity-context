"""Application policies for selective review and apply planning."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.review_governance.domain import (
    MemoryChangeSet,
    ProposedOperation,
)


@dataclass(frozen=True, slots=True)
class SelectChangeSetOperationsCommand:
    change_set: MemoryChangeSet
    expected_change_set_version: int
    expected_base_revision: int


@dataclass(frozen=True, slots=True)
class SelectChangeSetOperationsResult:
    change_set_id: str
    operations: tuple[ProposedOperation, ...]


@dataclass(frozen=True, slots=True)
class SelectChangeSetOperationsHandler:
    """Expose only reviewed operations with still-current optimistic guards."""

    def execute(
        self,
        command: SelectChangeSetOperationsCommand,
    ) -> SelectChangeSetOperationsResult:
        change_set = command.change_set
        if change_set.version != command.expected_change_set_version:
            raise ValueError("ChangeSet changed after review selection")
        if change_set.base_revision != command.expected_base_revision:
            raise ValueError("ChangeSet base revision is stale")
        operations = change_set.approved_operations
        if not operations:
            raise ValueError("ChangeSet has no approved operations to apply")
        return SelectChangeSetOperationsResult(
            change_set_id=change_set.change_set_id,
            operations=operations,
        )


__all__ = (
    "SelectChangeSetOperationsCommand",
    "SelectChangeSetOperationsHandler",
    "SelectChangeSetOperationsResult",
)
