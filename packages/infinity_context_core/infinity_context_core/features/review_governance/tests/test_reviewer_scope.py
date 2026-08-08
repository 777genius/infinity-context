"""Reviewer authorization is exact across memory and repository code scopes."""

from infinity_context_core.features.review_governance.public import SuggestionReviewScope


def test_repository_reviewer_requires_exact_code_scope() -> None:
    reviewer = SuggestionReviewScope(
        space_id="space-1",
        memory_scope_ids=("scope-1",),
        repository_id="repo-1",
        code_scope_id="branch-main",
    )

    assert reviewer.allows(
        space_id="space-1",
        memory_scope_id="scope-1",
        repository_id="repo-1",
        code_scope_id="branch-main",
    )
    assert not reviewer.allows(
        space_id="space-1",
        memory_scope_id="scope-1",
        repository_id="repo-1",
        code_scope_id=None,
    )
    assert not reviewer.allows(
        space_id="space-1",
        memory_scope_id="scope-2",
        repository_id="repo-1",
        code_scope_id="branch-main",
    )
