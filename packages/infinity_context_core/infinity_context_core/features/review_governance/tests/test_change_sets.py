"""Logical changeset review and optimistic-apply contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from infinity_context_core.features.review_governance.public import (
    ChangeSetEvidenceRef,
    ChangeSetScope,
    LegacySuggestionOperation,
    MemoryChangeSet,
    MemoryChangeSetState,
    ProposedOperation,
    ProposedOperationState,
    SelectChangeSetOperationsCommand,
    SelectChangeSetOperationsHandler,
    legacy_suggestion_as_change_set,
)

NOW = datetime(2026, 8, 5, tzinfo=UTC)
EVIDENCE = (ChangeSetEvidenceRef("capture", "capture-1", 2, "user statement"),)


def test_selective_review_preserves_rejected_operation_and_optimistic_guards() -> None:
    change_set = MemoryChangeSet.draft(
        change_set_id="change-1",
        scope=ChangeSetScope("space-1", "scope-1", repository_id="repo-1"),
        base_revision=12,
        operations=(
            ProposedOperation(
                operation_id="add-1",
                operation_type="add",
                candidate_text="Use Postgres",
                evidence_refs=EVIDENCE,
            ),
            ProposedOperation(
                operation_id="delete-1",
                operation_type="delete",
                target_fact_id="fact-old",
                expected_version=4,
                evidence_refs=EVIDENCE,
            ),
        ),
        created_by="reviewer-1",
        now=NOW,
    ).submit(expected_version=1, now=NOW + timedelta(seconds=1))

    reviewed = change_set.review(
        expected_version=2,
        approved_operation_ids=("add-1",),
        reason="accept addition, retain old evidence",
        now=NOW + timedelta(seconds=2),
    )

    assert reviewed.state is MemoryChangeSetState.PARTIALLY_APPROVED
    assert tuple(item.state for item in reviewed.operations) == (
        ProposedOperationState.APPROVED,
        ProposedOperationState.REJECTED,
    )
    result = SelectChangeSetOperationsHandler().execute(
        SelectChangeSetOperationsCommand(reviewed, 3, 12)
    )
    assert tuple(item.operation_id for item in result.operations) == ("add-1",)
    with pytest.raises(ValueError, match="base revision is stale"):
        SelectChangeSetOperationsHandler().execute(
            SelectChangeSetOperationsCommand(reviewed, 3, 11)
        )


def test_apply_results_are_auditable_and_conflicts_do_not_look_applied() -> None:
    change_set = _approved_change_set()

    conflicted = change_set.record_result(
        expected_version=3,
        operation_id="update-1",
        applied_fact_id=None,
        conflict_reason="fact version advanced",
        now=NOW + timedelta(seconds=3),
    )

    assert conflicted.state is MemoryChangeSetState.PARTIALLY_APPLIED
    assert conflicted.operations[0].state is ProposedOperationState.CONFLICTED
    assert conflicted.operations[0].conflict_reason == "fact version advanced"
    assert conflicted.operations[0].expected_version == 7


def test_legacy_suggestion_is_only_a_one_operation_compatibility_view() -> None:
    change_set = legacy_suggestion_as_change_set(
        LegacySuggestionOperation(
            suggestion_id="suggestion-1",
            operation="update",
            candidate_text="Use PostgreSQL 18",
            target_fact_id="fact-1",
            target_fact_version=7,
            evidence_refs=EVIDENCE,
            reason_code="new_architecture_decision",
        ),
        scope=ChangeSetScope("space-1", "scope-1"),
        base_revision=20,
        created_by="compatibility-adapter",
        now=NOW,
    )

    assert change_set.change_set_id == "suggestion-change-set:suggestion-1"
    assert len(change_set.operations) == 1
    assert change_set.operations[0].expected_version == 7
    assert change_set.operations[0].candidate_text == "Use PostgreSQL 18"


@pytest.mark.parametrize(
    ("target_fact_id", "target_fact_version", "expected_operation"),
    ((None, None, "add"), ("fact-1", 7, "update")),
)
def test_legacy_review_suggestion_maps_to_a_reviewable_logical_write(
    target_fact_id: str | None,
    target_fact_version: int | None,
    expected_operation: str,
) -> None:
    change_set = legacy_suggestion_as_change_set(
        LegacySuggestionOperation(
            suggestion_id="suggestion-review",
            operation="review",
            candidate_text="Use PostgreSQL 18",
            target_fact_id=target_fact_id,
            target_fact_version=target_fact_version,
            evidence_refs=EVIDENCE,
            reason_code="manual_review_required",
        ),
        scope=ChangeSetScope("space-1", "scope-1"),
        base_revision=20,
        created_by="compatibility-adapter",
        now=NOW,
    )

    assert change_set.operations[0].operation_type == expected_operation


def _approved_change_set() -> MemoryChangeSet:
    draft = MemoryChangeSet.draft(
        change_set_id="change-2",
        scope=ChangeSetScope("space-1", "scope-1"),
        base_revision=12,
        operations=(
            ProposedOperation(
                operation_id="update-1",
                operation_type="update",
                target_fact_id="fact-1",
                expected_version=7,
                candidate_text="Use PostgreSQL 18",
                evidence_refs=EVIDENCE,
            ),
        ),
        created_by="reviewer-1",
        now=NOW,
    )
    submitted = draft.submit(expected_version=1, now=NOW + timedelta(seconds=1))
    return submitted.review(
        expected_version=2,
        approved_operation_ids=("update-1",),
        reason="approved",
        now=NOW + timedelta(seconds=2),
    )
