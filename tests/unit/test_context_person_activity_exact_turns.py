from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_person_activity_exact_turns import (
    exact_person_activity_turn_candidates,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _turn_ref(marker: str) -> SourceRef:
    session, turn = marker[1:].split(":")
    return SourceRef(
        source_type="locomo_turn",
        source_id=f"locomo:conv-43:session_{session}:D{session}:{turn}:turn",
    )


def test_person_activity_exact_turns_focus_direct_outdoor_participation() -> None:
    item = ContextItem(
        item_id="outdoor_activity_window",
        item_type="chunk",
        text=(
            "D3:27 John: I started surfing five years ago and it's been great. "
            "I love the connection to nature. "
            "D12:6 John: Some of my hiking club friends came even though I just joined! "
            "D20:36 John: We went camping in the mountains and it was stunning! "
            "D25:2 John: Last week I got this amazing deal with a renowned outdoor gear company."
        ),
        score=0.99,
        source_refs=(
            _turn_ref("D3:27"),
            _turn_ref("D12:6"),
            _turn_ref("D20:36"),
            _turn_ref("D25:2"),
        ),
        diagnostics={
            "score_signals": {
                "query_expansion_reason": "outdoor_activity_inventory_bridge",
            },
        },
    )

    selected = exact_person_activity_turn_candidates(
        [item],
        query="What outdoor activities does John enjoy?",
    )
    source_ids = [str(ref.source_id) for item in selected for ref in item.source_refs]

    assert "locomo:conv-43:session_3:D3:27:turn" in source_ids
    assert "locomo:conv-43:session_12:D12:6:turn" in source_ids
    assert "locomo:conv-43:session_25:D25:2:turn" not in source_ids


def test_person_activity_exact_turns_prioritize_exercise_benefit_for_performance_query() -> None:
    items = (
        ContextItem(
            item_id="early_basketball_role",
            item_type="chunk",
            text="D1:1 John: I'm a shooting guard and our season opener is next week.",
            score=0.99,
            source_refs=(_turn_ref("D1:1"),),
            diagnostics={
                "score_signals": {
                    "query_expansion_reason": "exercise_activity_inventory_bridge",
                },
            },
        ),
        ContextItem(
            item_id="early_basketball_game",
            item_type="chunk",
            text="D2:1 John: I scored a lot in our latest basketball game.",
            score=0.98,
            source_refs=(_turn_ref("D2:1"),),
            diagnostics={
                "score_signals": {
                    "query_expansion_reason": "exercise_activity_inventory_bridge",
                },
            },
        ),
        ContextItem(
            item_id="strength_training_balance",
            item_type="chunk",
            text=(
                "D12:4 John: I added strength training to my schedule to balance "
                "basketball and improve performance."
            ),
            score=0.97,
            source_refs=(_turn_ref("D12:4"),),
            diagnostics={
                "score_signals": {
                    "query_expansion_reason": "exercise_activity_inventory_bridge",
                },
            },
        ),
        ContextItem(
            item_id="yoga_flexibility",
            item_type="chunk",
            text=(
                "D18:3 John: I'm trying out yoga to build strength and flexibility "
                "for my workouts."
            ),
            score=0.96,
            source_refs=(_turn_ref("D18:3"),),
            diagnostics={
                "score_signals": {
                    "query_expansion_reason": "exercise_activity_inventory_bridge",
                },
            },
        ),
    )

    selected = exact_person_activity_turn_candidates(
        items,
        query="What other exercises can help John with basketball performance?",
        limit=2,
    )
    source_ids = [str(ref.source_id) for item in selected for ref in item.source_refs]

    assert "locomo:conv-43:session_12:D12:4:turn" in source_ids
    assert "locomo:conv-43:session_18:D18:3:turn" in source_ids
    assert "locomo:conv-43:session_1:D1:1:turn" not in source_ids


def test_person_activity_exact_turns_accept_direct_source_sibling_without_reason() -> None:
    item = ContextItem(
        item_id="hydrated_source_sibling_direct_game",
        item_type="chunk",
        text=(
            "D4:8 John: That sounds great. Here's a picture from a recent game. "
            "image caption: a basketball game in progress visual query: basketball game"
        ),
        score=0.82,
        source_refs=(_turn_ref("D4:8"),),
        diagnostics={"retrieval_source": "keyword_source_sibling_chunks"},
    )

    selected = exact_person_activity_turn_candidates(
        [item],
        query="What sports does John like?",
        limit=1,
    )

    assert [str(ref.source_id) for ref in selected[0].source_refs] == [
        "locomo:conv-43:session_4:D4:8:turn"
    ]


def test_person_activity_exact_turns_prioritize_alternative_sport_for_besides_query() -> None:
    items = (
        ContextItem(
            item_id="basketball_role",
            item_type="chunk",
            text="D1:2 John: I'm a shooting guard for the team this season.",
            score=0.99,
            source_refs=(_turn_ref("D1:2"),),
        ),
        ContextItem(
            item_id="basketball_game",
            item_type="chunk",
            text=(
                "D2:4 John: Here's a picture from a recent game. "
                "image caption: a basketball game in progress"
            ),
            score=0.98,
            source_refs=(_turn_ref("D2:4"),),
        ),
        ContextItem(
            item_id="surfing_trip",
            item_type="chunk",
            text="D9:6 John: I spent the summer surfing and riding the waves.",
            score=0.97,
            source_refs=(_turn_ref("D9:6"),),
        ),
    )

    selected = exact_person_activity_turn_candidates(
        items,
        query="What sports does John like besides basketball?",
        limit=2,
    )
    source_ids = [str(ref.source_id) for item in selected for ref in item.source_refs]

    assert source_ids[0] == "locomo:conv-43:session_9:D9:6:turn"
    assert any(source_id.startswith("locomo:conv-43:session_1:") for source_id in source_ids)


def test_context_packer_prioritizes_person_activity_exact_turns_under_noise() -> None:
    query = "What sports does John like besides basketball?"
    exact_items = (
        ContextItem(
            item_id="john_basketball_role",
            item_type="chunk",
            text="D1:7 John: I'm a shooting guard for the team and our season opener is next week.",
            score=0.91,
            source_refs=(_turn_ref("D1:7"),),
            diagnostics={
                "score_signals": {
                    "query_expansion_reason": "decomposition_activity_participation",
                },
            },
        ),
        ContextItem(
            item_id="john_recent_game",
            item_type="chunk",
            text=(
                "D2:14 John: Here's a pic from a recent game. "
                "image caption: a basketball game in progress visual query: basketball game"
            ),
            score=0.9,
            source_refs=(_turn_ref("D2:14"),),
            diagnostics={
                "score_signals": {
                    "query_expansion_reason": "decomposition_activity_participation",
                },
            },
        ),
        ContextItem(
            item_id="john_court_score",
            item_type="chunk",
            text="D3:1 John: Last week I scored 40 points, my highest ever, on and off the court.",
            score=0.89,
            source_refs=(_turn_ref("D3:1"),),
            diagnostics={
                "score_signals": {
                    "query_expansion_reason": "decomposition_activity_participation",
                },
            },
        ),
        ContextItem(
            item_id="john_surfing",
            item_type="chunk",
            text=(
                "D3:25 John: I had an awesome summer with my friends, surfing "
                "and riding the waves."
            ),
            score=0.88,
            source_refs=(_turn_ref("D3:25"),),
            diagnostics={
                "score_signals": {
                    "query_expansion_reason": "outdoor_activity_inventory_bridge",
                },
            },
        ),
    )
    broad_noise = tuple(
        ContextItem(
            item_id=f"broad_activity_noise_{index}",
            item_type="chunk",
            text=f"D15:{20 + index} John: My family and team are supportive.",
            score=0.99 - index * 0.001,
            source_refs=(
                SourceRef(
                    source_type="locomo_turn",
                    source_id=f"locomo:conv-43:session_15:D15:{20 + index}:turn",
                ),
            ),
            diagnostics={
                "score_signals": {
                    "query_expansion_reason": "decomposition_activity_participation",
                },
            },
        )
        for index in range(8)
    )

    result = ContextPacker().pack(
        bundle_id="ctx_person_activity_inventory",
        items=(*broad_noise, *exact_items),
        query=query,
        token_budget=180,
    )

    assert "D1:7" in result.bundle.rendered_text
    assert "D2:14" in result.bundle.rendered_text
    assert "D3:1" in result.bundle.rendered_text
    assert "D3:25" in result.bundle.rendered_text
