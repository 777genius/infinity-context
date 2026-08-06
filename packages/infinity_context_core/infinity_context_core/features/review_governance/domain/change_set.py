"""Logical, reviewable changes without physical memory branches."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class MemoryChangeSetState(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PARTIALLY_APPROVED = "partially_approved"
    APPROVED = "approved"
    PARTIALLY_APPLIED = "partially_applied"
    APPLIED = "applied"
    REJECTED = "rejected"


class ProposedOperationType(StrEnum):
    ADD = "add"
    UPDATE = "update"
    SUPERSEDE = "supersede"
    DISPUTE = "dispute"
    DELETE = "delete"


class ProposedOperationState(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    CONFLICTED = "conflicted"


@dataclass(frozen=True, slots=True)
class ChangeSetScope:
    space_id: str
    memory_scope_id: str
    repository_id: str | None = None
    code_scope_id: str | None = None

    def __post_init__(self) -> None:
        _require_text("space_id", self.space_id)
        _require_text("memory_scope_id", self.memory_scope_id)
        if self.repository_id is not None:
            _require_text("repository_id", self.repository_id)
        if self.code_scope_id is not None:
            _require_text("code_scope_id", self.code_scope_id)
            if self.repository_id is None:
                raise ValueError("ChangeSet code_scope_id requires repository_id")


@dataclass(frozen=True, slots=True)
class ChangeSetEvidenceRef:
    source_type: str
    source_id: str
    source_version: int | None = None
    citation: str | None = None

    def __post_init__(self) -> None:
        _require_text("source_type", self.source_type)
        _require_text("source_id", self.source_id)
        if self.source_version is not None and self.source_version < 1:
            raise ValueError("ChangeSet source_version must be positive")
        if self.citation is not None:
            _require_text("citation", self.citation)


@dataclass(frozen=True, slots=True)
class ProposedOperation:
    operation_id: str
    operation_type: ProposedOperationType
    evidence_refs: tuple[ChangeSetEvidenceRef, ...]
    state: ProposedOperationState = ProposedOperationState.PROPOSED
    target_fact_id: str | None = None
    expected_version: int | None = None
    secondary_fact_id: str | None = None
    secondary_expected_version: int | None = None
    candidate_text: str | None = None
    reason_code: str = "review_proposal"
    applied_fact_id: str | None = None
    conflict_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_type", ProposedOperationType(self.operation_type))
        object.__setattr__(self, "state", ProposedOperationState(self.state))
        _require_text("operation_id", self.operation_id)
        _require_text("reason_code", self.reason_code)
        if not self.evidence_refs:
            raise ValueError("Proposed operation requires evidence_refs")
        targeted = self.operation_type is not ProposedOperationType.ADD
        if targeted and (self.target_fact_id is None or self.expected_version is None):
            raise ValueError("Targeted operation requires target_fact_id and expected_version")
        if not targeted and (self.target_fact_id is not None or self.expected_version is not None):
            raise ValueError("Add operation cannot target an existing fact")
        if self.expected_version is not None and self.expected_version < 1:
            raise ValueError("Operation expected_version must be positive")
        if self.operation_type is ProposedOperationType.SUPERSEDE:
            if self.secondary_fact_id is None or self.secondary_expected_version is None:
                raise ValueError("Supersede operation requires a successor and version")
        elif self.secondary_fact_id is not None or self.secondary_expected_version is not None:
            raise ValueError("Secondary fact is valid only for supersede")
        if self.secondary_expected_version is not None and self.secondary_expected_version < 1:
            raise ValueError("Operation secondary_expected_version must be positive")
        if self.operation_type in {ProposedOperationType.ADD, ProposedOperationType.UPDATE}:
            if self.candidate_text is None or not self.candidate_text.strip():
                raise ValueError("Add/update operation requires candidate_text")
        elif self.candidate_text is not None:
            raise ValueError("candidate_text is valid only for add/update")
        if self.state is ProposedOperationState.APPLIED and self.applied_fact_id is None:
            raise ValueError("Applied operation requires applied_fact_id")
        if self.state is ProposedOperationState.CONFLICTED and self.conflict_reason is None:
            raise ValueError("Conflicted operation requires conflict_reason")


@dataclass(frozen=True, slots=True)
class MemoryChangeSet:
    change_set_id: str
    scope: ChangeSetScope
    base_revision: int
    operations: tuple[ProposedOperation, ...]
    state: MemoryChangeSetState
    version: int
    created_at: datetime
    updated_at: datetime
    created_by: str
    review_reason: str | None = None

    @classmethod
    def draft(
        cls,
        *,
        change_set_id: str,
        scope: ChangeSetScope,
        base_revision: int,
        operations: tuple[ProposedOperation, ...],
        created_by: str,
        now: datetime,
    ) -> MemoryChangeSet:
        return cls(
            change_set_id=change_set_id,
            scope=scope,
            base_revision=base_revision,
            operations=operations,
            state=MemoryChangeSetState.DRAFT,
            version=1,
            created_at=now,
            updated_at=now,
            created_by=created_by,
        )

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", MemoryChangeSetState(self.state))
        _require_text("change_set_id", self.change_set_id)
        _require_text("created_by", self.created_by)
        if self.base_revision < 0:
            raise ValueError("ChangeSet base_revision cannot be negative")
        if self.version < 1:
            raise ValueError("ChangeSet version must be positive")
        if not self.operations:
            raise ValueError("ChangeSet requires proposed operations")
        operation_ids = tuple(item.operation_id for item in self.operations)
        if len(set(operation_ids)) != len(operation_ids):
            raise ValueError("ChangeSet operation ids must be unique")
        _require_aware("created_at", self.created_at)
        _require_aware("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("ChangeSet updated_at cannot precede created_at")

    def submit(self, *, expected_version: int, now: datetime) -> MemoryChangeSet:
        self._require_version(expected_version)
        if self.state is not MemoryChangeSetState.DRAFT:
            raise ValueError("Only a draft ChangeSet can be submitted")
        return self._advance(state=MemoryChangeSetState.PENDING_REVIEW, now=now)

    def review(
        self,
        *,
        expected_version: int,
        approved_operation_ids: tuple[str, ...],
        reason: str,
        now: datetime,
    ) -> MemoryChangeSet:
        self._require_version(expected_version)
        if self.state is not MemoryChangeSetState.PENDING_REVIEW:
            raise ValueError("Only a pending ChangeSet can be reviewed")
        _require_text("reason", reason)
        approved = set(approved_operation_ids)
        known = {item.operation_id for item in self.operations}
        if not approved <= known:
            raise ValueError("ChangeSet review references an unknown operation")
        operations = tuple(
            replace(
                item,
                state=(
                    ProposedOperationState.APPROVED
                    if item.operation_id in approved
                    else ProposedOperationState.REJECTED
                ),
            )
            for item in self.operations
        )
        state = _reviewed_state(operations)
        return self._advance(
            state=state,
            operations=operations,
            review_reason=reason,
            now=now,
        )

    def record_result(
        self,
        *,
        expected_version: int,
        operation_id: str,
        applied_fact_id: str | None,
        conflict_reason: str | None,
        now: datetime,
    ) -> MemoryChangeSet:
        self._require_version(expected_version)
        target = next(
            (item for item in self.operations if item.operation_id == operation_id),
            None,
        )
        if target is None:
            raise ValueError("Unknown ChangeSet operation")
        if target.state is not ProposedOperationState.APPROVED:
            raise ValueError("Only an approved operation can record an apply result")
        if (applied_fact_id is None) == (conflict_reason is None):
            raise ValueError("Apply result requires exactly one of fact id or conflict")
        next_operation = replace(
            target,
            state=(
                ProposedOperationState.APPLIED
                if applied_fact_id is not None
                else ProposedOperationState.CONFLICTED
            ),
            applied_fact_id=applied_fact_id,
            conflict_reason=conflict_reason,
        )
        operations = tuple(
            next_operation if item.operation_id == operation_id else item
            for item in self.operations
        )
        return self._advance(
            state=_applied_state(operations),
            operations=operations,
            now=now,
        )

    @property
    def approved_operations(self) -> tuple[ProposedOperation, ...]:
        return tuple(
            item for item in self.operations if item.state is ProposedOperationState.APPROVED
        )

    def _advance(
        self,
        *,
        state: MemoryChangeSetState,
        now: datetime,
        operations: tuple[ProposedOperation, ...] | None = None,
        review_reason: str | None = None,
    ) -> MemoryChangeSet:
        _require_aware("now", now)
        if now < self.updated_at:
            raise ValueError("ChangeSet transaction time cannot move backwards")
        return replace(
            self,
            state=state,
            operations=operations or self.operations,
            review_reason=review_reason or self.review_reason,
            version=self.version + 1,
            updated_at=now,
        )

    def _require_version(self, expected_version: int) -> None:
        if self.version != expected_version:
            raise ValueError(
                f"ChangeSet version conflict: expected {expected_version}, actual {self.version}"
            )


def _reviewed_state(operations: tuple[ProposedOperation, ...]) -> MemoryChangeSetState:
    approved = sum(item.state is ProposedOperationState.APPROVED for item in operations)
    if approved == 0:
        return MemoryChangeSetState.REJECTED
    if approved == len(operations):
        return MemoryChangeSetState.APPROVED
    return MemoryChangeSetState.PARTIALLY_APPROVED


def _applied_state(operations: tuple[ProposedOperation, ...]) -> MemoryChangeSetState:
    actionable = tuple(
        item for item in operations if item.state is not ProposedOperationState.REJECTED
    )
    if actionable and all(item.state is ProposedOperationState.APPLIED for item in actionable):
        return MemoryChangeSetState.APPLIED
    return MemoryChangeSetState.PARTIALLY_APPLIED


def _require_text(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = (
    "ChangeSetEvidenceRef",
    "ChangeSetScope",
    "MemoryChangeSet",
    "MemoryChangeSetState",
    "ProposedOperation",
    "ProposedOperationState",
    "ProposedOperationType",
)
