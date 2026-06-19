from datetime import UTC, datetime

from infinity_context_core.application.anchor_extraction import (
    structured_anchor_metadata_for_label,
)
from infinity_context_core.application.use_cases.anchors import _merge_score
from infinity_context_core.domain.entities import (
    Confidence,
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryScopeId,
    SpaceId,
)


def test_event_merge_policy_rejects_same_participant_different_relative_time() -> None:
    score, reasons, metadata = _merge_score(
        _event_anchor("anchor_call_two_hours", "Call with Alex 2 hours ago"),
        _event_anchor("anchor_call_three_hours", "Call with Alex 3 hours ago"),
    )

    assert score == 0.0
    assert reasons == []
    assert metadata["event_identity_conflict"] == "temporal_mismatch"


def test_event_merge_policy_allows_equivalent_relative_time_variants() -> None:
    score, reasons, metadata = _merge_score(
        _event_anchor("anchor_chat_an_hour", "Chat with Alex an hour ago"),
        _event_anchor("anchor_chat_hour", "Chat with Alex hour ago"),
    )

    assert score >= 86
    assert reasons == ["event identity similarity"]
    assert metadata["event_identity"]["source"]["temporal"] == "hours_ago:1:hour"
    assert metadata["event_identity"]["target"]["temporal"] == "hours_ago:1:hour"


def _event_anchor(anchor_id: str, label: str) -> MemoryAnchor:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    return MemoryAnchor.create(
        anchor_id=MemoryAnchorId(anchor_id),
        space_id=SpaceId("space_event_policy"),
        memory_scope_id=MemoryScopeId("memory_scope_event_policy"),
        kind=MemoryAnchorKind.EVENT,
        normalized_key=label.casefold(),
        label=label,
        aliases=(),
        confidence=Confidence.MEDIUM,
        metadata=structured_anchor_metadata_for_label(MemoryAnchorKind.EVENT, label),
        now=now,
    )
