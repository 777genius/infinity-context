from datetime import UTC, datetime

from infinity_context_core.application.anchor_extraction import (
    structured_anchor_metadata_for_label,
)
from infinity_context_core.application.context_query_intent import (
    build_query_anchor_intent,
    match_query_anchor_intent,
)
from infinity_context_core.domain.entities import (
    Confidence,
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryScopeId,
    SpaceId,
)


def _anchor(
    *,
    kind: MemoryAnchorKind,
    label: str,
    anchor_id: str = "anchor_test",
) -> MemoryAnchor:
    now = datetime(2026, 6, 20, tzinfo=UTC)
    return MemoryAnchor.create(
        anchor_id=MemoryAnchorId(anchor_id),
        space_id=SpaceId("space_context_query_intent"),
        memory_scope_id=MemoryScopeId("memory_scope_context_query_intent"),
        kind=kind,
        normalized_key=label.casefold(),
        label=label,
        confidence=Confidence.HIGH,
        metadata=structured_anchor_metadata_for_label(kind, label),
        now=now,
    )


def test_query_anchor_intent_extracts_lowercase_ru_event_hints() -> None:
    intent = build_query_anchor_intent("созвон с алексом в атласе час назад")

    assert intent.diagnostics()["query_anchor_hint_count"] == 5
    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks"}
    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert intent.temporal_keys() == {"hours_ago", "hours_ago:1:hour"}


def test_query_anchor_intent_matches_cross_language_event_identity() -> None:
    intent = build_query_anchor_intent("созвон с алексом в атласе час назад")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Call with Alex about Atlas 1 hour ago",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert match is not None
    assert match.score_boost == 0.09
    assert match.reasons == (
        "query_event_participant_match",
        "query_event_project_match",
        "query_event_temporal_match",
    )
    assert set(match.matched_keys) >= {"aleks", "atlas", "hours_ago:1:hour"}


def test_query_anchor_intent_matches_lowercase_direct_event_actor() -> None:
    intent = build_query_anchor_intent("call alex about atlas last week")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Call with Alex about Atlas last week",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks"}
    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert intent.temporal_keys() == {"last_week", "last_week:1:week"}
    assert match is not None
    assert match.reasons == (
        "query_event_identity_match",
        "query_event_participant_match",
        "query_event_project_match",
        "query_event_temporal_match",
    )
    assert set(match.matched_keys) >= {"aleks", "atlas", "last_week:1:week"}


def test_query_anchor_intent_matches_lowercase_actor_before_message_event() -> None:
    intent = build_query_anchor_intent("alex wrote about atlas hour ago")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Wrote with Alex about Atlas hour ago",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks"}
    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert intent.temporal_keys() == {"hours_ago", "hours_ago:1:hour"}
    assert match is not None
    assert match.reasons == (
        "query_event_identity_match",
        "query_event_participant_match",
        "query_event_project_match",
        "query_event_temporal_match",
    )


def test_query_anchor_intent_rejects_wrong_event_participant() -> None:
    intent = build_query_anchor_intent("созвон с алексом в атласе час назад")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Call with Sam about Atlas 1 hour ago",
    )

    assert match_query_anchor_intent(intent, anchor) is None


def test_query_anchor_intent_rejects_wrong_project_anchor() -> None:
    intent = build_query_anchor_intent("what did Alex say about project Apollo")
    atlas = _anchor(kind=MemoryAnchorKind.PROJECT, label="Project Atlas")
    apollo = _anchor(
        kind=MemoryAnchorKind.PROJECT,
        label="Project Apollo",
        anchor_id="anchor_apollo",
    )

    assert match_query_anchor_intent(intent, atlas) is None
    match = match_query_anchor_intent(intent, apollo)
    assert match is not None
    assert match.reasons == ("query_project_identity_match",)
