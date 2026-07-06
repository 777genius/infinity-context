from infinity_context_core.application.context_temporal_query import (
    apply_temporal_query_intent_boosts,
    build_temporal_query_intent,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_recent_event_query_prefers_later_locomo_session_evidence() -> None:
    intent = build_temporal_query_intent("What was the most recent conversation with Sam?")
    older = _item(
        "older",
        text="D4:6 Sam: We talked about the Atlas prototype during the call.",
        score=0.71,
        source_id="locomo:conv-fixture:session_4:D4:6:turn",
    )
    newer = _item(
        "newer",
        text="D20:8 Sam: We talked about the Atlas prototype in the latest call.",
        score=0.7,
        source_id="locomo:conv-fixture:session_20:D20:8:turn",
    )

    boosted = apply_temporal_query_intent_boosts((older, newer), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert intent.requests_recent_event is True
    assert by_id["newer"].score > by_id["older"].score
    assert by_id["newer"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for recent event and item has session-order evidence"
    )
    assert (
        by_id["newer"].diagnostics["score_signals"]["temporal_query_intent_boost"]
        > by_id["older"].diagnostics["score_signals"]["temporal_query_intent_boost"]
    )


def test_recent_event_query_prefers_later_session_when_items_have_temporal_hints() -> None:
    intent = build_temporal_query_intent("What was the latest conversation with Sam?")
    older = _item(
        "older",
        text="D4:6 Sam: We talked about the Atlas prototype during last week's call.",
        score=0.72,
        source_id="locomo:conv-fixture:session_4:D4:6:turn",
        event_temporal_hint_code="last_week",
    )
    newer = _item(
        "newer",
        text="D20:8 Sam: We talked about the Atlas prototype in yesterday's call.",
        score=0.71,
        source_id="locomo:conv-fixture:session_20:D20:8:turn",
        event_temporal_hint_code="yesterday",
    )

    boosted = apply_temporal_query_intent_boosts((older, newer), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert by_id["newer"].score > by_id["older"].score
    assert by_id["newer"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for recent event and item has session-order evidence"
    )
    assert (
        by_id["newer"].diagnostics["score_signals"]["temporal_query_intent_boost"]
        > by_id["older"].diagnostics["score_signals"]["temporal_query_intent_boost"]
    )


def test_recent_event_query_uses_structured_session_order_metadata() -> None:
    intent = build_temporal_query_intent("What was the latest conversation with Sam?")
    older = _item(
        "older",
        text="Sam: We talked about the Atlas prototype during the call.",
        score=0.71,
        source_id="locomo:conv-fixture:turn-older",
        metadata={"session_index": 4},
    )
    newer = _item(
        "newer",
        text="Sam: We talked about the Atlas prototype in the latest call.",
        score=0.7,
        source_id="locomo:conv-fixture:turn-newer",
        metadata={"session_key": "session_20"},
    )

    boosted = apply_temporal_query_intent_boosts((older, newer), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert by_id["newer"].score > by_id["older"].score
    assert by_id["newer"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for recent event and item has session-order evidence"
    )
    assert (
        by_id["newer"].diagnostics["score_signals"]["temporal_query_intent_boost"]
        > by_id["older"].diagnostics["score_signals"]["temporal_query_intent_boost"]
    )


def test_recent_event_query_uses_official_locomo_dia_id_metadata() -> None:
    intent = build_temporal_query_intent("What was the latest conversation with Sam?")
    older = _item(
        "older",
        text="Sam: We talked about the Atlas prototype during the call.",
        score=0.71,
        source_id="locomo:conv-fixture:turn-older",
        metadata={"dia_id": "D4", "turn_id": "6"},
    )
    newer = _item(
        "newer",
        text="Sam: We talked about the Atlas prototype in the latest call.",
        score=0.7,
        source_id="locomo:conv-fixture:turn-newer",
        metadata={"source_dia_id": "D20", "source_turn_index": "8"},
    )

    boosted = apply_temporal_query_intent_boosts((older, newer), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert by_id["newer"].score > by_id["older"].score
    assert by_id["newer"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for recent event and item has session-order evidence"
    )
    assert (
        by_id["newer"].diagnostics["score_signals"]["temporal_query_intent_boost"]
        > by_id["older"].diagnostics["score_signals"]["temporal_query_intent_boost"]
    )


def test_recent_event_query_uses_bare_official_locomo_dia_id_metadata() -> None:
    intent = build_temporal_query_intent("What was the latest conversation with Sam?")
    older = _item(
        "older",
        text="Sam: We talked about the Atlas prototype during the call.",
        score=0.71,
        source_id="locomo:conv-fixture:turn-older",
        metadata={"dia_id": "D4"},
    )
    newer = _item(
        "newer",
        text="Sam: We talked about the Atlas prototype in the latest call.",
        score=0.7,
        source_id="locomo:conv-fixture:turn-newer",
        metadata={"source_dia_id": "D20"},
    )

    boosted = apply_temporal_query_intent_boosts((older, newer), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert by_id["newer"].score > by_id["older"].score
    assert by_id["newer"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for recent event and item has session-order evidence"
    )
    assert (
        by_id["newer"].diagnostics["score_signals"]["temporal_query_intent_boost"]
        > by_id["older"].diagnostics["score_signals"]["temporal_query_intent_boost"]
    )


def test_recent_event_query_uses_session_prefixed_dialogue_metadata() -> None:
    intent = build_temporal_query_intent("What was the latest conversation with Sam?")
    older = _item(
        "older",
        text="Sam: We talked about the Atlas prototype during the call.",
        score=0.71,
        source_id="locomo:conv-fixture:turn-older",
        metadata={"source_dialogue_id": "session_4", "source_turn_index": "6"},
    )
    newer = _item(
        "newer",
        text="Sam: We talked about the Atlas prototype in the latest call.",
        score=0.7,
        source_id="locomo:conv-fixture:turn-newer",
        metadata={"source_dialogue_id": "dialogue_20", "source_turn_index": "8"},
    )

    boosted = apply_temporal_query_intent_boosts((older, newer), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert by_id["newer"].score > by_id["older"].score
    assert by_id["newer"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for recent event and item has session-order evidence"
    )


def test_recent_event_query_uses_hyphenated_dialogue_turn_order() -> None:
    intent = build_temporal_query_intent("What was the latest conversation with Sam?")
    older = _item(
        "older",
        text="D4-6 Sam: We talked about the Atlas prototype during the call.",
        score=0.71,
        source_id="locomo:conv-fixture:turn-older",
    )
    newer = _item(
        "newer",
        text="D20-8 Sam: We talked about the Atlas prototype in the latest call.",
        score=0.7,
        source_id="locomo:conv-fixture:turn-newer",
    )

    boosted = apply_temporal_query_intent_boosts((older, newer), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert by_id["newer"].score > by_id["older"].score
    assert by_id["newer"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for recent event and item has session-order evidence"
    )
    assert (
        by_id["newer"].diagnostics["score_signals"]["temporal_query_intent_boost"]
        > by_id["older"].diagnostics["score_signals"]["temporal_query_intent_boost"]
    )


def test_earliest_event_query_prefers_earlier_locomo_session_evidence() -> None:
    intent = build_temporal_query_intent("What was the first conversation with Sam?")
    older = _item(
        "older",
        text="D1:6 Sam: We first talked about the Atlas prototype during the call.",
        score=0.7,
        source_id="locomo:conv-fixture:session_1:D1:6:turn",
    )
    newer = _item(
        "newer",
        text="D20:8 Sam: We talked about the Atlas prototype in a later call.",
        score=0.71,
        source_id="locomo:conv-fixture:session_20:D20:8:turn",
    )

    boosted = apply_temporal_query_intent_boosts((older, newer), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert intent.requests_earliest_event is True
    assert intent.requests_recent_event is False
    assert intent.prefers_current is False
    assert by_id["older"].score > by_id["newer"].score
    assert by_id["older"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for earliest event and item has session-order evidence"
    )
    assert (
        by_id["older"].diagnostics["score_signals"]["temporal_query_intent_boost"]
        > by_id["newer"].diagnostics["score_signals"]["temporal_query_intent_boost"]
    )


def test_recent_event_session_order_does_not_override_explicit_relative_time() -> None:
    intent = build_temporal_query_intent("What did Sam say last week?")
    matched = _item(
        "matched",
        text="D4:6 Sam: The Atlas prototype needs one more pass.",
        score=0.7,
        source_id="locomo:conv-fixture:session_4:D4:6:turn",
        event_temporal_hint_code="last_week",
    )

    boosted = apply_temporal_query_intent_boosts((matched,), intent=intent)

    assert intent.requests_recent_event is False
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query relative time matches item event window"
    )


def test_recent_event_session_order_does_not_revive_stale_state() -> None:
    intent = build_temporal_query_intent("What was the latest conversation with Sam?")
    stale = _item(
        "stale",
        text="D22:8 Sam: The old Atlas provider was deprecated after the review.",
        score=0.7,
        source_id="locomo:conv-fixture:session_22:D22:8:turn",
        fact_status="superseded",
    )

    boosted = apply_temporal_query_intent_boosts((stale,), intent=intent)

    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query prefers current active memory and item is superseded"
    )
    assert boosted[0].diagnostics["score_signals"]["temporal_query_intent_boost"] < 0


def test_current_query_does_not_boost_unmarked_old_session_fact() -> None:
    intent = build_temporal_query_intent("What is the current Atlas provider?")
    unmarked_old_fact = _item(
        "unmarked_old_fact",
        text="D4:6 Sam: Atlas provider is LocalAI.",
        score=0.7,
        source_id="locomo:conv-fixture:session_4:D4:6:turn",
        fact_status="",
    )

    boosted = apply_temporal_query_intent_boosts((unmarked_old_fact,), intent=intent)

    assert boosted[0].score == unmarked_old_fact.score
    assert "temporal_query_intent_reason" not in boosted[0].diagnostics


def _item(
    item_id: str,
    *,
    text: str,
    score: float,
    source_id: str,
    fact_status: str = "active",
    event_temporal_hint_code: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ContextItem:
    provenance = {"fact_status": fact_status, "source_id": source_id}
    if event_temporal_hint_code:
        provenance["event_temporal_hint_code"] = event_temporal_hint_code
    diagnostics: dict[str, object] = {
        "retrieval_source": "keyword_chunks",
        "retrieval_sources": ["keyword_chunks"],
        "score_signals": {"base_score": score},
        "provenance": provenance,
    }
    if metadata:
        diagnostics["metadata"] = metadata
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics=diagnostics,
    )
