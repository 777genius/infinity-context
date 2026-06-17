from dataclasses import replace
from datetime import UTC, datetime

from memo_stack_core.domain.assets import (
    MAX_CONTEXT_LINK_REVIEW_EVENTS,
    MemoryContextLinkSuggestion,
    MemoryContextLinkSuggestionId,
)
from memo_stack_core.domain.entities import MemoryScopeId, SpaceId


def test_context_link_suggestion_review_events_are_bounded_for_legacy_metadata() -> None:
    now = datetime(2026, 6, 17, tzinfo=UTC)
    suggestion = MemoryContextLinkSuggestion.create(
        suggestion_id=MemoryContextLinkSuggestionId("ctxlinksug_1"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("memory_scope_1"),
        source_type="capture",
        source_id="capture_1",
        target_type="fact",
        target_id="fact_1",
        relation_type="related_to",
        confidence="medium",
        reason="same evidence",
        score=88.0,
        now=now,
        metadata={"suggestion_policy_version": "context-link-policy-v1"},
    )
    suggestion = replace(
        suggestion,
        metadata={
            **dict(suggestion.metadata),
            "review_events": [
                {"suggestion_id": f"ctxlinksug_old_{index}", "action": "reject"}
                for index in range(MAX_CONTEXT_LINK_REVIEW_EVENTS + 5)
            ],
        },
    )

    approved = suggestion.approve(now=now, reason="confirmed")
    review_events = approved.metadata["review_events"]

    assert len(review_events) == MAX_CONTEXT_LINK_REVIEW_EVENTS
    assert review_events[0]["suggestion_id"] == "ctxlinksug_old_6"
    assert review_events[-1]["suggestion_id"] == "ctxlinksug_1"
    assert review_events[-1]["action"] == "approve"
    assert review_events[-1]["reason"] == "confirmed"


def test_context_link_review_audit_reason_redacts_obvious_secret_markers() -> None:
    now = datetime(2026, 6, 17, tzinfo=UTC)
    suggestion = MemoryContextLinkSuggestion.create(
        suggestion_id=MemoryContextLinkSuggestionId("ctxlinksug_secret"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("memory_scope_1"),
        source_type="capture",
        source_id="capture_1",
        target_type="fact",
        target_id="fact_1",
        relation_type="related_to",
        confidence="medium",
        reason="same evidence",
        score=88.0,
        now=now,
    )

    approved = suggestion.approve(
        now=now,
        reason="Authorization: Bearer sk-proj-review-secret-value",
    )
    review_event = approved.metadata["review_events"][-1]

    assert approved.review_reason == "Authorization: Bearer sk-proj-review-secret-value"
    assert review_event["reason"] == "[redacted]"
