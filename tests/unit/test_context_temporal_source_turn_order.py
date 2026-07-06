from infinity_context_core.application.context_temporal_query import (
    apply_temporal_query_intent_boosts,
    build_temporal_query_intent,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_temporal_query_intent_detects_hyphenated_and_window_source_turns() -> None:
    after_hyphen_source_ref = build_temporal_query_intent(
        "What did Riley mention after source ref "
        "locomo-conv-1-session_12-D12-4-turn?"
    )
    between_source_turns = build_temporal_query_intent(
        "What did Riley mention between D12:4 and D12:8?"
    )
    between_hyphen_source_turns = build_temporal_query_intent(
        "What did Riley mention between D12-4 and D12-8?"
    )

    assert after_hyphen_source_ref.after_event is True
    assert after_hyphen_source_ref.session_ordinals == (12,)
    assert after_hyphen_source_ref.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert between_source_turns.after_event is True
    assert between_source_turns.before_event is True
    assert between_source_turns.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert between_source_turns.source_turn_sequence.before_turns[0].label() == "D12:8"
    assert between_hyphen_source_turns.after_event is True
    assert between_hyphen_source_turns.before_event is True
    assert between_hyphen_source_turns.session_ordinals == (12,)
    assert (
        between_hyphen_source_turns.source_turn_sequence.after_turns[0].label()
        == "D12:4"
    )
    assert (
        between_hyphen_source_turns.source_turn_sequence.before_turns[0].label()
        == "D12:8"
    )


def test_temporal_query_does_not_cross_dialogues_for_source_turn_after_order() -> None:
    intent = build_temporal_query_intent("What did Riley mention after D12:4?")
    same_dialogue_after = _item(
        "same_dialogue_after",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D12:5 Riley said the studio visit was confirmed.",
    )
    next_dialogue = _item(
        "next_dialogue",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D13:1 Riley started a later conversation about dinner plans.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (next_dialogue, same_dialogue_after),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_dialogue_after"].score == 0.74
    assert by_id["same_dialogue_after"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert by_id["next_dialogue"].score == 0.702
    assert by_id["next_dialogue"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for an explicit session and item has a different session"
    )


def test_temporal_query_does_not_cross_dialogues_for_source_turn_before_order() -> None:
    intent = build_temporal_query_intent("What did Riley mention before D12:4?")
    same_dialogue_before = _item(
        "same_dialogue_before",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D12:3 Riley was still waiting on Morgan.",
    )
    previous_dialogue = _item(
        "previous_dialogue",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D11:99 Riley closed a prior conversation.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (previous_dialogue, same_dialogue_before),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_dialogue_before"].score == 0.74
    assert by_id["same_dialogue_before"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for before source turn and item source turn precedes boundary"
    )
    assert by_id["previous_dialogue"].score == 0.702
    assert by_id["previous_dialogue"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for an explicit session and item has a different session"
    )


def test_temporal_query_uses_source_ref_quote_preview_for_source_turn_order() -> None:
    intent = build_temporal_query_intent("What did Riley mention after D12:4?")
    after_item = ContextItem(
        item_id="after",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="conversation-summary",
                quote_preview="D12:5 Riley said the studio visit was confirmed.",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    before_item = ContextItem(
        item_id="before",
        item_type="fact",
        text="Riley was still waiting on Morgan.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="conversation-summary",
                quote_preview="D12:3 Riley was still waiting on Morgan.",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts((after_item, before_item), intent=intent)

    assert boosted[0].score == 0.74
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert boosted[1].score == 0.694


def test_temporal_query_boosts_full_source_ref_boundary_order() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref locomo:conv-1:session_12:D12:4:turn?"
    )
    after_item = ContextItem(
        item_id="after",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12:D12:5:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    before_item = ContextItem(
        item_id="before",
        item_type="fact",
        text="Riley was still waiting on Morgan.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12:D12:3:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts((after_item, before_item), intent=intent)

    assert boosted[0].score == 0.74
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert boosted[1].score == 0.694
    assert boosted[1].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn precedes boundary"
    )


def test_temporal_query_does_not_cross_source_identity_for_full_source_ref_order() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source_after = ContextItem(
        item_id="same_source_after",
        item_type="fact",
        text="D12:5 Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12:D12:5:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    different_source_same_turn = ContextItem(
        item_id="different_source_same_turn",
        item_type="fact",
        text="D12:5 Riley discussed a different conversation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-2:session_12:D12:5:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_same_turn, same_source_after),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source_after"].score == 0.74
    assert by_id["same_source_after"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert by_id["different_source_same_turn"].score == 0.694
    assert by_id["different_source_same_turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_combines_source_ref_scope_with_quote_preview_turn() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source_after = ContextItem(
        item_id="same_source_after_quote",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12",
                quote_preview="D12:5 Riley said the studio visit was confirmed.",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    different_source_after = ContextItem(
        item_id="different_source_after_quote",
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
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_after, same_source_after),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source_after_quote"].score == 0.74
    assert by_id["same_source_after_quote"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["different_source_after_quote"].score == 0.694
    assert by_id["different_source_after_quote"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_uses_separate_query_source_scope_for_turn_order() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after turn D12:4 in source locomo:conv-1:session_12?"
    )
    same_source_after = ContextItem(
        item_id="same_source_after_separate_query_scope",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12",
                quote_preview="D12:5 Riley said the studio visit was confirmed.",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    different_source_after = ContextItem(
        item_id="different_source_after_separate_query_scope",
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
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_after, same_source_after),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source_after_separate_query_scope"].score == 0.74
    assert by_id["same_source_after_separate_query_scope"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["different_source_after_separate_query_scope"].score == 0.694
    assert by_id["different_source_after_separate_query_scope"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_uses_separate_query_source_scope_for_before_turn_order() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention before turn D12:4 in source locomo:conv-1:session_12?"
    )
    same_source_before = ContextItem(
        item_id="same_source_before_separate_query_scope",
        item_type="fact",
        text="Riley was still waiting on Morgan.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12",
                quote_preview="D12:3 Riley was still waiting on Morgan.",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    different_source_before = ContextItem(
        item_id="different_source_before_separate_query_scope",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-2:session_12",
                quote_preview="D12:3 Riley discussed a different conversation.",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_before, same_source_before),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source_before_separate_query_scope"].score == 0.74
    assert by_id["same_source_before_separate_query_scope"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for before source turn and item source turn precedes boundary"
    assert by_id["different_source_before_separate_query_scope"].score == 0.694
    assert by_id["different_source_before_separate_query_scope"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_combines_diagnostic_source_scope_with_turn_refs() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source_after = ContextItem(
        item_id="same_source_after_diagnostic_scope",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "canonical_anchors",
            "source_id": "locomo:conv-1:session_12",
            "source_turn_refs": ["D12:5"],
        },
    )
    different_source_after = ContextItem(
        item_id="different_source_after_diagnostic_scope",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "canonical_anchors",
            "source_id": "locomo:conv-2:session_12",
            "source_turn_refs": ["D12:5"],
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_after, same_source_after),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source_after_diagnostic_scope"].score == 0.74
    assert by_id["same_source_after_diagnostic_scope"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["different_source_after_diagnostic_scope"].score == 0.694
    assert by_id["different_source_after_diagnostic_scope"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_combines_nested_diagnostic_source_scope_with_turn_refs() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref locomo:conv-1:session_12:D12:4:turn?"
    )
    same_source_after = ContextItem(
        item_id="same_source_after_nested_diagnostic_scope",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "canonical_anchors",
            "benchmark_candidate_features": {
                "source_id": "locomo:conv-1:session_12",
                "source_turn_refs": ["D12:5"],
            },
        },
    )
    different_source_after = ContextItem(
        item_id="different_source_after_nested_diagnostic_scope",
        item_type="fact",
        text="Riley discussed a different conversation.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "canonical_anchors",
            "benchmark_candidate_features": {
                "source_id": "locomo:conv-2:session_12",
                "source_turn_refs": ["D12:5"],
            },
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_after, same_source_after),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source_after_nested_diagnostic_scope"].score == 0.74
    assert by_id["same_source_after_nested_diagnostic_scope"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for after source turn and item source turn follows boundary"
    assert by_id["different_source_after_nested_diagnostic_scope"].score == 0.694
    assert by_id["different_source_after_nested_diagnostic_scope"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_boosts_source_turn_window_order() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention between D12:4 and D12:8?"
    )
    inside_item = _item(
        "inside",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D12:6 Riley said the studio visit was confirmed.",
    )
    before_item = _item(
        "before",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D12:3 Riley was still waiting on Morgan.",
    )
    after_item = _item(
        "after",
        score=0.71,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D12:9 Riley changed the topic to dinner plans.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (before_item, after_item, inside_item),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.before_turns[0].label() == "D12:8"
    assert "source_turn_window" in intent.diagnostics()["temporal_query_intent_reasons"]
    assert by_id["inside"].score == 0.74
    assert by_id["inside"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source-turn window and item source turn is inside boundaries"
    )
    assert by_id["before"].score == 0.694
    assert by_id["after"].score == 0.684
    assert by_id["after"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source-turn window and item source turn is outside boundaries"
    )


def test_temporal_query_does_not_cross_source_identity_for_source_turn_window() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention between source refs "
        "locomo:conv-1:session_12:D12:4:turn and "
        "locomo:conv-1:session_12:D12:8:turn?"
    )
    same_source_inside = ContextItem(
        item_id="same_source_inside",
        item_type="fact",
        text="D12:6 Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12:D12:6:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    different_source_inside = ContextItem(
        item_id="different_source_inside",
        item_type="fact",
        text="D12:6 Riley discussed a different conversation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-2:session_12:D12:6:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_inside, same_source_inside),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source_inside"].score == 0.74
    assert by_id["same_source_inside"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source-turn window and item source turn is inside boundaries"
    )
    assert by_id["different_source_inside"].score == 0.694
    assert by_id["different_source_inside"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_uses_hyphenated_source_refs_for_source_turn_window() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention between D12-4 and D12-8?"
    )
    inside_item = ContextItem(
        item_id="inside",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo-conv-1-session_12-D12-6-turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    outside_item = ContextItem(
        item_id="outside",
        item_type="fact",
        text="Riley changed the topic to dinner plans.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo-conv-1-session_12-D12-9-turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_item, inside_item),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.before_turns[0].label() == "D12:8"
    assert by_id["inside"].score == 0.74
    assert by_id["outside"].score == 0.694


def test_temporal_query_normalizes_reversed_source_turn_window_order() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention between D12:8 and D12:4?"
    )
    inside_item = _item(
        "inside",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D12:6 Riley said the studio visit was confirmed.",
    )
    outside_item = _item(
        "outside",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D12:9 Riley changed the topic to dinner plans.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_item, inside_item),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:8"
    assert intent.source_turn_sequence.before_turns[0].label() == "D12:4"
    assert "source_turn_window" in intent.diagnostics()["temporal_query_intent_reasons"]
    assert by_id["inside"].score == 0.74
    assert by_id["outside"].score == 0.694


def test_temporal_query_uses_hyphenated_source_ref_boundary_order() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref locomo-conv-1-session_12-D12-4-turn?"
    )
    after_item = ContextItem(
        item_id="after",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo-conv-1-session_12-D12-5-turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    before_item = ContextItem(
        item_id="before",
        item_type="fact",
        text="Riley was still waiting on Morgan.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo-conv-1-session_12-D12-3-turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (after_item, before_item),
        intent=intent,
    )

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert boosted[0].score == 0.74
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert boosted[1].score == 0.694


def test_temporal_query_matches_separator_variants_for_source_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref locomo-conv-1-session_12-D12-4-turn?"
    )
    same_source_after = ContextItem(
        item_id="same_source_after",
        item_type="fact",
        text="D12:5 Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12:D12:5:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    different_source_after = ContextItem(
        item_id="different_source_after",
        item_type="fact",
        text="D12:5 Riley discussed a different conversation.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-2:session_12:D12:5:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_source_after, same_source_after),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["same_source_after"].score == 0.74
    assert by_id["same_source_after"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert by_id["different_source_after"].score == 0.694
    assert by_id["different_source_after"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for source turn and item source identity differs"


def test_temporal_query_uses_nested_diagnostic_source_turn_refs() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention between D12:4 and D12:8?"
    )
    inside_item = ContextItem(
        item_id="inside_nested_diagnostics",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "canonical_anchors",
            "benchmark_candidate_features": {
                "source_turn_refs": ["D12:6"],
                "source_ref_dedupe_key": "source_turn_refs:D12:6",
            },
        },
    )
    outside_item = ContextItem(
        item_id="outside_nested_diagnostics",
        item_type="fact",
        text="Riley changed the topic to dinner plans.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "canonical_anchors",
            "benchmark_candidate_features": {
                "source_turn_refs": ["D12:9"],
                "source_ref_dedupe_key": "source_turn_refs:D12:9",
            },
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_item, inside_item),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["inside_nested_diagnostics"].score == 0.74
    assert by_id["outside_nested_diagnostics"].score == 0.694


def test_temporal_query_uses_structured_diagnostic_source_turn_refs() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention between D12:4 and D12:8?"
    )
    inside_item = ContextItem(
        item_id="inside_structured_diagnostics",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "canonical_anchors",
            "benchmark_candidate_features": {
                "source_turn": {"dialogue": 12, "turn": 6},
            },
        },
    )
    outside_item = ContextItem(
        item_id="outside_structured_diagnostics",
        item_type="fact",
        text="Riley changed the topic to dinner plans.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "canonical_anchors",
            "benchmark_candidate_features": {
                "source_turn": {"session_index": "12", "turn_index": "9"},
            },
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_item, inside_item),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["inside_structured_diagnostics"].score == 0.74
    assert by_id["outside_structured_diagnostics"].score == 0.694


def test_temporal_query_uses_top_level_structured_diagnostic_source_turn_refs() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention between D12:4 and D12:8?"
    )
    inside_item = ContextItem(
        item_id="inside_top_level_structured_diagnostics",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "canonical_anchors",
            "source_dialogue_id": "12",
            "source_turn_id": "6",
        },
    )
    outside_item = ContextItem(
        item_id="outside_top_level_structured_diagnostics",
        item_type="fact",
        text="Riley changed the topic to dinner plans.",
        score=0.72,
        source_refs=(SourceRef(source_type="document", source_id="conversation-summary"),),
        diagnostics={
            "retrieval_source": "canonical_anchors",
            "source_dialogue_id": "12",
            "source_turn_id": "9",
        },
    )

    boosted = apply_temporal_query_intent_boosts(
        (outside_item, inside_item),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["inside_top_level_structured_diagnostics"].score == 0.74
    assert by_id["outside_top_level_structured_diagnostics"].score == 0.694


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
