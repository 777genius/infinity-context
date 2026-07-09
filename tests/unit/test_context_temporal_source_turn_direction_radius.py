from infinity_context_core.application.context_temporal_query import (
    apply_temporal_query_intent_boosts,
    build_temporal_query_intent,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_temporal_query_boosts_next_two_turns_after_source_turn() -> None:
    intent = build_temporal_query_intent("What did Riley mention next two turns after D12:4?")
    within_radius = _item(
        "turn_within_radius",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:6 Riley said the studio visit was confirmed.",
    )
    outside_radius = _item(
        "turn_outside_radius",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:8 Riley changed the topic to dinner plans.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_radius, within_radius),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.after_turn_radius == 2
    assert "after_source_turn_radius" in intent.diagnostics()[
        "temporal_query_intent_reasons"
    ]
    assert by_id["turn_within_radius"].score == 0.74
    assert by_id["turn_outside_radius"].score == 0.706


def test_temporal_query_boosts_next_turn_after_source_turn() -> None:
    intent = build_temporal_query_intent("What did Riley mention next turn after D12:4?")
    next_turn = _item(
        "turn_next",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:5 Riley said Morgan confirmed the visit.",
    )
    later_turn = _item(
        "turn_later",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:6 Riley said the studio visit was confirmed.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (later_turn, next_turn),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.after_turn_radius == 1
    assert "after_source_turn_radius" in intent.diagnostics()[
        "temporal_query_intent_reasons"
    ]
    assert by_id["turn_next"].score == 0.74
    assert by_id["turn_later"].score == 0.706


def test_temporal_query_boosts_next_couple_turns_after_source_turn() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention next couple turns after D12:4?"
    )
    within_radius = _item(
        "turn_within_radius",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:6 Riley said the studio visit was confirmed.",
    )
    outside_radius = _item(
        "turn_outside_radius",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:8 Riley changed the topic to dinner plans.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_radius, within_radius),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.after_turn_radius == 2
    assert by_id["turn_within_radius"].score == 0.74
    assert by_id["turn_outside_radius"].score == 0.706


def test_temporal_query_boosts_next_couple_of_turns_after_source_turn() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention next couple of turns after D12:4?"
    )
    within_radius = _item(
        "turn_within_radius",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:6 Riley said the studio visit was confirmed.",
    )
    outside_radius = _item(
        "turn_outside_radius",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:8 Riley changed the topic to dinner plans.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_radius, within_radius),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.after_turn_radius == 2
    assert by_id["turn_within_radius"].score == 0.74
    assert by_id["turn_outside_radius"].score == 0.706


def test_temporal_query_boosts_previous_two_turns_before_source_turn() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention previous two turns before D12:8?"
    )
    within_radius = _item(
        "turn_within_radius",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:6 Riley said the studio visit was confirmed.",
    )
    outside_radius = _item(
        "turn_outside_radius",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:4 Riley was still waiting on Morgan.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_radius, within_radius),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.before_turns[0].label() == "D12:8"
    assert intent.source_turn_sequence.before_turn_radius == 2
    assert "before_source_turn_radius" in intent.diagnostics()[
        "temporal_query_intent_reasons"
    ]
    assert by_id["turn_within_radius"].score == 0.74
    assert by_id["turn_outside_radius"].score == 0.706


def test_temporal_query_boosts_previous_turn_before_source_turn() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention previous turn before D12:8?"
    )
    previous_turn = _item(
        "turn_previous",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:7 Riley said the studio visit was confirmed.",
    )
    earlier_turn = _item(
        "turn_earlier",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:6 Riley was still waiting on Morgan.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (earlier_turn, previous_turn),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.before_turns[0].label() == "D12:8"
    assert intent.source_turn_sequence.before_turn_radius == 1
    assert "before_source_turn_radius" in intent.diagnostics()[
        "temporal_query_intent_reasons"
    ]
    assert by_id["turn_previous"].score == 0.74
    assert by_id["turn_earlier"].score == 0.706


def _item(
    item_id: str,
    *,
    score: float,
    retrieval_source: str,
    fact_status: str,
    review_only: bool = False,
    event_temporal_hint_code: str | None = None,
    temporal_hint_code: str | None = None,
    event_valid_from: str | None = None,
    text: str | None = None,
) -> ContextItem:
    provenance = {"fact_status": fact_status}
    if event_temporal_hint_code:
        provenance["event_temporal_hint_code"] = event_temporal_hint_code
    if temporal_hint_code:
        provenance["temporal_hint_code"] = temporal_hint_code
    if event_valid_from:
        provenance["event_valid_from"] = event_valid_from
    return ContextItem(
        item_id=item_id,
        item_type="fact",
        text=text or item_id,
        score=score,
        source_refs=(SourceRef(source_type="fact", source_id=item_id),),
        diagnostics={
            "retrieval_source": retrieval_source,
            "retrieval_sources": [retrieval_source],
            "review_only": review_only,
            "score_signals": {"base_score": score},
            "provenance": provenance,
        },
    )
