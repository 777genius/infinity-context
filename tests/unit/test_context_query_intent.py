from datetime import UTC, datetime

from infinity_context_core.application.anchor_extraction import (
    structured_anchor_metadata_for_label,
)
from infinity_context_core.application.context_query_intent import (
    build_query_anchor_intent,
    match_query_anchor_intent,
    query_anchor_lookup_keys,
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
    assert intent.event_type_keys() == {"group:call", "sozvon"}


def test_query_anchor_lookup_keys_include_storage_and_canonical_variants() -> None:
    intent = build_query_anchor_intent("созвон с алексом в атласе час назад")

    keys = {
        (lookup.kind.value, lookup.normalized_key)
        for lookup in query_anchor_lookup_keys(intent)
    }

    assert ("person", "алекс") in keys
    assert ("person", "aleks") in keys
    assert ("project", "атлас") in keys
    assert ("project", "atlas") in keys
    assert ("event", "созвон с алексом час назад") in keys
    assert ("event", "sozvon s aleks chas nazad") in keys
    assert all("event temporal" not in normalized_key for _, normalized_key in keys)


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
        "query_event_type_match",
        "query_event_temporal_match",
    )
    assert set(match.matched_keys) >= {
        "aleks",
        "atlas",
        "group:call",
        "hours_ago:1:hour",
    }


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
        "query_event_type_match",
        "query_event_temporal_match",
    )
    assert set(match.matched_keys) >= {
        "aleks",
        "atlas",
        "group:call",
        "last_week:1:week",
    }


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
        "query_event_type_match",
        "query_event_temporal_match",
    )


def test_query_anchor_intent_matches_word_number_relative_time() -> None:
    intent = build_query_anchor_intent("alex said about atlas two hours ago")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Told with Alex about Atlas 2 hours ago",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.temporal_keys() == {"hours_ago", "hours_ago:2:hour"}
    assert match is not None
    assert "query_event_temporal_match" in match.reasons
    assert "hours_ago:2:hour" in match.matched_keys


def test_query_anchor_intent_matches_previous_week_temporal_phrase() -> None:
    intent = build_query_anchor_intent("call alex about atlas previous week")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Call with Alex about Atlas last week",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.temporal_keys() == {"last_week", "last_week:1:week"}
    assert match is not None
    assert "query_event_temporal_match" in match.reasons
    assert "last_week:1:week" in match.matched_keys


def test_query_anchor_intent_matches_lowercase_actor_before_said_event() -> None:
    intent = build_query_anchor_intent("alex said about atlas yesterday")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Told with Alex about Atlas yesterday",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks"}
    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert intent.temporal_keys() == {"yesterday", "yesterday:1:day"}
    assert intent.event_type_keys() == {"group:message", "said"}
    assert match is not None
    assert "query_event_type_match" in match.reasons
    assert set(match.matched_keys) >= {"aleks", "atlas", "group:message"}


def test_query_anchor_intent_matches_partial_day_temporal_only_event_query() -> None:
    intent = build_query_anchor_intent("with alex about atlas this morning")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Call with Alex about Atlas this morning",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks"}
    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert intent.temporal_keys() == {"today_morning", "today_morning:0:part_of_day"}
    assert intent.event_type_keys() == frozenset()
    assert match is not None
    assert match.reasons == (
        "query_event_participant_match",
        "query_event_project_match",
        "query_event_temporal_match",
    )
    assert set(match.matched_keys) >= {"aleks", "atlas", "today_morning:0:part_of_day"}


def test_query_anchor_intent_rejects_wrong_event_participant() -> None:
    intent = build_query_anchor_intent("созвон с алексом в атласе час назад")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Call with Sam about Atlas 1 hour ago",
    )

    assert match_query_anchor_intent(intent, anchor) is None


def test_query_anchor_intent_rejects_wrong_explicit_event_type() -> None:
    intent = build_query_anchor_intent("call with alex about atlas last week")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Chat with Alex about Atlas last week",
    )

    assert match_query_anchor_intent(intent, anchor) is None


def test_query_anchor_intent_matches_cross_language_message_event_type() -> None:
    intent = build_query_anchor_intent("переписывался с алексом по атласу час назад")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="DM with Alex about Atlas 1 hour ago",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.event_type_keys() == {"group:message", "perepisyvalsya"}
    assert match is not None
    assert "query_event_type_match" in match.reasons
    assert set(match.matched_keys) >= {"aleks", "atlas", "group:message"}


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
