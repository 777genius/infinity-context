from infinity_context_core.application.context_temporal_query import (
    apply_temporal_query_intent_boosts,
    build_temporal_query_intent,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_temporal_query_extracts_dialogue_turn_session_hint() -> None:
    intent = build_temporal_query_intent("What did Riley mention around D12:4?")
    matched = _item(
        "turn_match",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:4 Riley mentioned the studio visit with Morgan.",
    )
    adjacent = _item(
        "turn_adjacent",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:5 Riley said Morgan confirmed the visit.",
    )
    distant_same_session = _item(
        "turn_distant",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:9 Riley changed the topic to dinner plans.",
    )
    different_session = _item(
        "turn_decoy",
        score=0.71,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D11:4 Riley mentioned the volunteer shift.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, distant_same_session, adjacent, matched),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.session_ordinals == (12,)
    assert intent.source_turn_sequence.near_turns[0].label() == "D12:4"
    assert intent.diagnostics()["temporal_query_near_source_turns"] == ["D12:4"]
    assert by_id["turn_match"].score > by_id["turn_decoy"].score
    assert by_id["turn_match"].score > by_id["turn_adjacent"].score
    assert by_id["turn_adjacent"].score > by_id["turn_distant"].score
    assert by_id["turn_match"].diagnostics["score_signals"][
        "temporal_query_intent_boost"
    ] == 0.04
    assert by_id["turn_match"].diagnostics["temporal_query_intent_reason"] == (
        "query asks around source turn and item source turn matches boundary"
    )
    assert by_id["turn_adjacent"].diagnostics["temporal_query_intent_reason"] == (
        "query asks around source turn and item source turn is adjacent"
    )
    assert by_id["turn_distant"].diagnostics["temporal_query_intent_reason"] == (
        "query asks around source turn and item source turn is distant"
    )


def test_temporal_query_does_not_cross_source_identity_for_near_source_turn() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention around source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source_match = ContextItem(
        item_id="same_source_match",
        item_type="fact",
        text="D12:4 Riley mentioned the studio visit with Morgan.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12:D12:4:turn",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    different_source_same_turn = ContextItem(
        item_id="different_source_same_turn",
        item_type="fact",
        text="D12:4 Riley discussed a different conversation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-2:session_12:D12:4:turn",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_same_turn, same_source_match),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source_match"].score == 0.74
    assert by_id["same_source_match"].diagnostics["temporal_query_intent_reason"] == (
        "query asks around source turn and item source turn matches boundary"
    )
    assert by_id["different_source_same_turn"].score == 0.694
    assert by_id["different_source_same_turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_uses_separate_query_source_scope_for_near_turn_order() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention around turn D12:4 in source locomo:conv-1:session_12?"
    )
    same_source_match = ContextItem(
        item_id="same_source_near_separate_query_scope",
        item_type="fact",
        text="Riley mentioned the studio visit with Morgan.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12",
                quote_preview="D12:4 Riley mentioned the studio visit with Morgan.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    different_source_same_turn = ContextItem(
        item_id="different_source_near_separate_query_scope",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-2:session_12",
                quote_preview="D12:4 Riley discussed a different conversation.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_same_turn, same_source_match),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source_near_separate_query_scope"].score == 0.74
    assert by_id["same_source_near_separate_query_scope"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks around source turn and item source turn matches boundary"
    assert by_id["different_source_near_separate_query_scope"].score == 0.694
    assert by_id["different_source_near_separate_query_scope"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_boosts_within_two_source_turn_radius() -> None:
    intent = build_temporal_query_intent("What did Riley mention within 2 turns of D12:4?")
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
    different_session = _item(
        "turn_decoy",
        score=0.71,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D11:6 Riley mentioned the volunteer shift.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, outside_radius, within_radius),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.near_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.near_turn_radius == 2
    assert intent.diagnostics()["temporal_query_near_source_turn_radius"] == 2
    assert "near_source_turn_radius" in intent.diagnostics()[
        "temporal_query_intent_reasons"
    ]
    assert by_id["turn_within_radius"].score == 0.722
    assert by_id["turn_outside_radius"].score == 0.706
    assert by_id["turn_decoy"].score == 0.692
    assert by_id["turn_within_radius"].diagnostics["temporal_query_intent_reason"] == (
        "query asks around source turn and item source turn is within radius"
    )


def test_temporal_query_boosts_natural_source_turn_radius() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention within two turns of the fifth turn in the twelfth session?"
    )
    within_radius = _item(
        "natural_turn_within_radius",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="Session twelve turn seven: Riley said the studio visit was confirmed.",
    )
    outside_radius = _item(
        "natural_turn_outside_radius",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="Session twelve turn nine: Riley changed the topic to dinner plans.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_radius, within_radius),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.near_turns[0].label() == "D12:5"
    assert intent.source_turn_sequence.near_turn_radius == 2
    assert by_id["natural_turn_within_radius"].score == 0.722
    assert by_id["natural_turn_outside_radius"].score == 0.706
    assert by_id["natural_turn_within_radius"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks around source turn and item source turn is within radius"


def test_temporal_query_treats_couple_as_two_source_turn_radius() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention within a couple turns of D12:4?"
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

    assert intent.source_turn_sequence.near_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.near_turn_radius == 2
    assert by_id["turn_within_radius"].score == 0.722
    assert by_id["turn_outside_radius"].score == 0.706


def test_temporal_query_treats_couple_of_as_two_source_turn_radius() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention within a couple of turns of D12:4?"
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

    assert intent.source_turn_sequence.near_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.near_turn_radius == 2
    assert by_id["turn_within_radius"].score == 0.722
    assert by_id["turn_outside_radius"].score == 0.706


def test_temporal_query_caps_oversized_source_turn_radius() -> None:
    intent = build_temporal_query_intent("What did Riley mention within 99 turns of D12:4?")
    capped_match = _item(
        "turn_capped_match",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:9 Riley said the studio visit was confirmed.",
    )
    outside_cap = _item(
        "turn_outside_cap",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:10 Riley changed the topic to dinner plans.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_cap, capped_match),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.near_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.near_turn_radius == 5
    assert intent.diagnostics()["temporal_query_near_source_turn_radius"] == 5
    assert by_id["turn_capped_match"].score == 0.722
    assert by_id["turn_outside_cap"].score == 0.706


def test_temporal_query_boosts_within_two_turns_after_source_turn() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention within 2 turns after D12:4?"
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
    wrong_side = _item(
        "turn_wrong_side",
        score=0.71,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:3 Riley was still waiting on Morgan.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_radius, wrong_side, within_radius),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.after_turn_radius == 2
    assert intent.diagnostics()["temporal_query_after_source_turn_radius"] == 2
    assert "after_source_turn_radius" in intent.diagnostics()[
        "temporal_query_intent_reasons"
    ]
    assert by_id["turn_within_radius"].score == 0.74
    assert by_id["turn_outside_radius"].score == 0.706
    assert by_id["turn_wrong_side"].score == 0.684
    assert by_id["turn_within_radius"].diagnostics["temporal_query_intent_reason"] == (
        "query asks within 2 turns after source turn and item source turn is inside radius"
    )


def test_temporal_query_does_not_cross_source_identity_for_direction_radius() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention within 2 turns after source ref "
        "locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source_within_radius = ContextItem(
        item_id="same_source_within_radius",
        item_type="fact",
        text="D12:6 Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12:D12:6:turn",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    different_source_within_radius = ContextItem(
        item_id="different_source_within_radius",
        item_type="fact",
        text="D12:6 Riley discussed a different conversation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-2:session_12:D12:6:turn",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_within_radius, same_source_within_radius),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source_within_radius"].score == 0.74
    assert by_id["same_source_within_radius"].diagnostics[
        "temporal_query_intent_reason"
    ] == (
        "query asks within 2 turns after source turn and item source turn is inside radius"
    )
    assert by_id["different_source_within_radius"].score == 0.694
    assert by_id["different_source_within_radius"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_does_not_cross_source_identity_for_scoped_turn_radius() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention within 2 turns of D12:4 in source "
        "locomo:conv-1:session_12?"
    )
    same_source_within_radius = ContextItem(
        item_id="same_source_within_radius",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12",
                quote_preview="D12:6 Riley said the studio visit was confirmed.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    different_source_within_radius = ContextItem(
        item_id="different_source_within_radius",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-2:session_12",
                quote_preview="D12:6 Riley discussed a different conversation.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_within_radius, same_source_within_radius),
        intent=intent,
    )

    by_id = {item.item_id: item for item in boosted}
    assert by_id["same_source_within_radius"].score == 0.722
    assert by_id["same_source_within_radius"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks around source turn and item source turn is within radius"
    assert by_id["different_source_within_radius"].score == 0.694
    assert by_id["different_source_within_radius"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_requires_candidate_source_identity_for_scoped_turn_radius() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention within 2 turns of D12:4 in source "
        "locomo:conv-1:session_12?"
    )
    unidentified_within_radius = _item(
        "unidentified_within_radius",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:6 Riley said the studio visit was confirmed.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (unidentified_within_radius,),
        intent=intent,
    )

    assert boosted[0].score == 0.7
    assert "temporal_query_intent_reason" not in boosted[0].diagnostics


def test_temporal_query_does_not_cross_source_identity_for_scoped_turn_window() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention between D12:4 and D12:8 in source "
        "locomo:conv-1:session_12?"
    )
    same_source_inside_window = ContextItem(
        item_id="same_source_inside_window",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12",
                quote_preview="D12:6 Riley said the studio visit was confirmed.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    different_source_inside_window = ContextItem(
        item_id="different_source_inside_window",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-2:session_12",
                quote_preview="D12:6 Riley discussed a different conversation.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_inside_window, same_source_inside_window),
        intent=intent,
    )

    by_id = {item.item_id: item for item in boosted}
    assert by_id["same_source_inside_window"].score == 0.74
    assert by_id["same_source_inside_window"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source-turn window and item source turn is inside boundaries"
    assert by_id["different_source_inside_window"].score == 0.694
    assert by_id["different_source_inside_window"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_shares_source_identity_across_mixed_source_turn_window() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention between source ref "
        "locomo:conv-1:session_12:D12:4:turn and D12:8?"
    )
    assert intent.source_turn_sequence.after_turns[0].source_identity
    assert (
        intent.source_turn_sequence.before_turns[0].source_identity
        == intent.source_turn_sequence.after_turns[0].source_identity
    )
    same_source_inside_window = ContextItem(
        item_id="same_source_inside_window",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12",
                quote_preview="D12:6 Riley said the studio visit was confirmed.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    unidentified_inside_window = _item(
        "unidentified_inside_window",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:6 Riley discussed an unidentified conversation.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (unidentified_inside_window, same_source_inside_window),
        intent=intent,
    )

    by_id = {item.item_id: item for item in boosted}
    assert by_id["same_source_inside_window"].score == 0.74
    assert by_id["same_source_inside_window"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source-turn window and item source turn is inside boundaries"
    assert by_id["unidentified_inside_window"].score == 0.72
    assert "temporal_query_intent_reason" not in by_id[
        "unidentified_inside_window"
    ].diagnostics


def test_temporal_query_shares_source_identity_from_second_mixed_window_boundary() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention between D12:4 and source ref "
        "locomo:conv-1:session_12:D12:8:turn?"
    )
    assert intent.source_turn_sequence.after_turns[0].source_identity
    assert (
        intent.source_turn_sequence.after_turns[0].source_identity
        == intent.source_turn_sequence.before_turns[0].source_identity
    )
    same_source_inside_window = ContextItem(
        item_id="same_source_inside_window",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12",
                quote_preview="D12:6 Riley said the studio visit was confirmed.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (same_source_inside_window,),
        intent=intent,
    )

    assert boosted[0].score == 0.74
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source-turn window and item source turn is inside boundaries"
    )


def test_temporal_query_does_not_cross_source_identity_for_scoped_next_turn() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention next turn after D12:4 in source "
        "locomo:conv-1:session_12?"
    )
    same_source_next_turn = ContextItem(
        item_id="same_source_next_turn",
        item_type="fact",
        text="Riley said Morgan confirmed the studio visit.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12",
                quote_preview="D12:5 Riley said Morgan confirmed the studio visit.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    different_source_next_turn = ContextItem(
        item_id="different_source_next_turn",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-2:session_12",
                quote_preview="D12:5 Riley discussed a different conversation.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_next_turn, same_source_next_turn),
        intent=intent,
    )

    by_id = {item.item_id: item for item in boosted}
    assert by_id["same_source_next_turn"].score == 0.74
    assert by_id["same_source_next_turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks within 1 turns after source turn and item source turn is inside radius"
    assert by_id["different_source_next_turn"].score == 0.694
    assert by_id["different_source_next_turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_does_not_cross_source_identity_for_scoped_previous_turn() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention previous turn before D12:8 in source "
        "locomo:conv-1:session_12?"
    )
    same_source_previous_turn = ContextItem(
        item_id="same_source_previous_turn",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12",
                quote_preview="D12:7 Riley said the studio visit was confirmed.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    different_source_previous_turn = ContextItem(
        item_id="different_source_previous_turn",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-2:session_12",
                quote_preview="D12:7 Riley discussed a different conversation.",
            ),
        ),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_previous_turn, same_source_previous_turn),
        intent=intent,
    )

    by_id = {item.item_id: item for item in boosted}
    assert by_id["same_source_previous_turn"].score == 0.74
    assert by_id["same_source_previous_turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks within 1 turns before source turn and item source turn is inside radius"
    assert by_id["different_source_previous_turn"].score == 0.694
    assert by_id["different_source_previous_turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_boosts_within_two_turns_before_source_turn() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention within two turns before D12:8?"
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
    wrong_side = _item(
        "turn_wrong_side",
        score=0.71,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:9 Riley changed the topic to dinner plans.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_radius, wrong_side, within_radius),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.before_turns[0].label() == "D12:8"
    assert intent.source_turn_sequence.before_turn_radius == 2
    assert intent.diagnostics()["temporal_query_before_source_turn_radius"] == 2
    assert "before_source_turn_radius" in intent.diagnostics()[
        "temporal_query_intent_reasons"
    ]
    assert by_id["turn_within_radius"].score == 0.74
    assert by_id["turn_outside_radius"].score == 0.706
    assert by_id["turn_wrong_side"].score == 0.684
    assert by_id["turn_within_radius"].diagnostics["temporal_query_intent_reason"] == (
        "query asks within 2 turns before source turn and item source turn is inside radius"
    )


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
