"""Compatibility mapping from one legacy suggestion to one logical operation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.features.review_governance.domain import (
    ChangeSetEvidenceRef,
    ChangeSetScope,
    MemoryChangeSet,
    ProposedOperation,
    ProposedOperationType,
)


@dataclass(frozen=True, slots=True)
class LegacySuggestionOperation:
    suggestion_id: str
    operation: str
    candidate_text: str
    target_fact_id: str | None
    target_fact_version: int | None
    evidence_refs: tuple[ChangeSetEvidenceRef, ...]
    reason_code: str


def legacy_suggestion_as_change_set(
    suggestion: LegacySuggestionOperation,
    *,
    scope: ChangeSetScope,
    base_revision: int,
    created_by: str,
    now: datetime,
) -> MemoryChangeSet:
    """Keep legacy MemorySuggestion as a one-operation compatibility view."""

    operation_type = _legacy_operation_type(suggestion)
    candidate_text = (
        suggestion.candidate_text
        if operation_type in {ProposedOperationType.ADD, ProposedOperationType.UPDATE}
        else None
    )
    operation = ProposedOperation(
        operation_id=f"suggestion:{suggestion.suggestion_id}",
        operation_type=operation_type,
        target_fact_id=suggestion.target_fact_id,
        expected_version=suggestion.target_fact_version,
        candidate_text=candidate_text,
        evidence_refs=suggestion.evidence_refs,
        reason_code=suggestion.reason_code,
    )
    return MemoryChangeSet.draft(
        change_set_id=f"suggestion-change-set:{suggestion.suggestion_id}",
        scope=scope,
        base_revision=base_revision,
        operations=(operation,),
        created_by=created_by,
        now=now,
    )


def _legacy_operation_type(
    suggestion: LegacySuggestionOperation,
) -> ProposedOperationType:
    if suggestion.operation != "review":
        return ProposedOperationType(suggestion.operation)
    if suggestion.target_fact_id is None:
        if suggestion.target_fact_version is not None:
            raise ValueError("Untargeted review suggestion cannot carry target version")
        return ProposedOperationType.ADD
    if suggestion.target_fact_version is None:
        raise ValueError("Targeted review suggestion requires target version")
    return ProposedOperationType.UPDATE


__all__ = ("LegacySuggestionOperation", "legacy_suggestion_as_change_set")
