from infinity_context_core.application.context_packer import (
    ContextPacker,
    _answer_support_diversity_candidates,
    _ordered_answer_support_families_for_query,
)
from infinity_context_core.application.context_packer_inventory_slots import (
    _game_inventory_answer_directness_rank,
    _game_inventory_slot_for_text,
)
from infinity_context_core.application.context_query_expansion import (
    QueryExpansionPlan,
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance
from infinity_context_core.application.context_source_siblings import (
    source_sibling_answer_evidence,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_query_expansion_routes_video_game_lists_to_game_inventory() -> None:
    plan = build_query_expansion_plan("What video games does Riley play?")

    expansion = _expansion_query(plan, "board_game_inventory_bridge")

    assert "video game video games" in expansion
    assert "tournament tournaments" in expansion
    assert "won winning winner victory" in expansion
    assert "called named title" in expansion


def test_game_inventory_recognizes_named_video_game_evidence_shapes() -> None:
    cases = {
        "D1:7 The game was called Counter-Strike: Global Offensive.": (
            "game_named_counter_strike_global_offensive"
        ),
        (
            "D10:6 I usually play CS:GO, but I tried my hand at the local "
            "Street Fighter tournament since I play that game a lot."
        ): "game_named_cs_go",
        (
            "D27:1 I was in the final of a big Valorant tournament last "
            "Saturday, and I won as champion."
        ): "game_named_valorant",
        (
            "D23:17 I have been playing a game nonstop with a futuristic "
            "setting and gameplay called Cyberpunk 2077."
        ): "game_named_cyberpunk_2077",
    }

    for text, expected_slot in cases.items():
        assert _game_inventory_slot_for_text(text) == expected_slot
        assert _game_inventory_answer_directness_rank(text) == 0


def test_best_query_relevance_uses_game_inventory_for_video_game_evidence() -> None:
    plan = build_query_expansion_plan("What video games does Riley play?")
    cases = (
        "D1:7 The game was called Counter-Strike: Global Offensive.",
        (
            "D10:6 I usually play CS:GO, but I tried my hand at the local "
            "Street Fighter tournament since I play that game a lot."
        ),
        (
            "D27:1 I was in the final of a big Valorant tournament last "
            "Saturday, and I won as champion."
        ),
        (
            "D23:17 I have been playing a game nonstop with a futuristic "
            "setting and gameplay called Cyberpunk 2077."
        ),
    )

    for text in cases:
        _, reason, _ = best_query_relevance(plan, text=text)

        assert reason == "board_game_inventory_bridge"


def test_source_sibling_answer_evidence_accepts_named_video_game_turns() -> None:
    expansion_query = _expansion_query(
        build_query_expansion_plan("What video games does Riley play?"),
        "board_game_inventory_bridge",
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="board_game_inventory_bridge",
        text=(
            "session_27 turn D27:1\n"
            "D27:1 Riley: I was in the final of a big Valorant tournament "
            "last Saturday, and I won as champion."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="board_game_inventory_bridge",
        text=(
            "session_23 turn D23:17\n"
            "D23:17 Riley: I have been playing a game nonstop with a "
            "futuristic setting and gameplay called Cyberpunk 2077."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="board_game_inventory_bridge",
        text=(
            "session_4 turn D4:1\n"
            "D4:1 Riley: I went to a game convention and met new people."
        ),
    )


def test_source_sibling_answer_evidence_accepts_gaming_medium_visual_equipment() -> None:
    expansion_query = _expansion_query(
        build_query_expansion_plan("What mediums does Riley use to play games?"),
        "gaming_medium_bridge",
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="gaming_medium_bridge",
        text=(
            "session_22 turn D22:2\n"
            "D22:2 Riley: I won a really big video game tournament last week.\n"
            "image caption: a photo of a trophy and a game controller on a table\n"
            "visual query: video game tournament trophy cash prize"
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="gaming_medium_bridge",
        text=(
            "session_27 turn D27:15\n"
            "D27:15 Riley: I upgraded some of my equipment at home.\n"
            "image caption: a photo of a desk with a computer monitor and a keyboard\n"
            "visual query: gaming setup"
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="gaming_medium_bridge",
        text=(
            "session_4 turn D4:1\n"
            "D4:1 Riley: I went to a game convention and met new people."
        ),
    )


def test_answer_support_prioritizes_exact_named_game_inventory_over_marker_groups() -> None:
    exact_named_game = _answer_support_item(
        "street_fighter",
        (
            "D10:6 Riley: I usually play CS:GO, but I tried my hand at the "
            "local Street Fighter tournament since I play that game a lot."
        ),
        source_id="locomo:conv-fixture:session_10:D10:6:turn",
    )
    broad_marker_group = _answer_support_item(
        "broad_marker_group",
        (
            "D1:3 Riley won a video game tournament. Related turns: D1:5 D1:7. "
            "D1:11 Riley's main hobbies are playing video games and watching movies."
        ),
        source_type="locomo_observation",
        source_id="locomo:conv-fixture:session_1:observation",
    )

    candidates = _answer_support_diversity_candidates(
        [broad_marker_group, exact_named_game]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What video games does Riley play?",
    )

    assert candidates[ordered[0]].item_id == "street_fighter"


def test_context_packer_keeps_exact_named_video_game_turns_for_inventory_lists() -> None:
    named_games = (
        _answer_support_item(
            "counter_strike",
            (
                "D1:7 Riley: The game was called Counter-Strike: Global "
                "Offensive, and the team had a blast to the end."
            ),
            source_id="locomo:conv-fixture:session_1:D1:7:turn",
        ),
        _answer_support_item(
            "street_fighter",
            (
                "D10:6 Riley: I usually play CS:GO, but I tried my hand at "
                "the local Street Fighter tournament since I play that game a lot."
            ),
            source_id="locomo:conv-fixture:session_10:D10:6:turn",
        ),
        _answer_support_item(
            "valorant",
            (
                "D27:1 Riley: I was in the final of a big Valorant tournament "
                "last Saturday, and I won as champion."
            ),
            source_id="locomo:conv-fixture:session_27:D27:1:turn",
        ),
        _answer_support_item(
            "xenoblade",
            (
                "D27:23 Riley: I am currently playing this awesome fantasy "
                "RPG called Xenoblade Chronicles."
            ),
            source_id="locomo:conv-fixture:session_27:D27:23:turn",
        ),
        _answer_support_item(
            "cyberpunk",
            (
                "D23:17 Riley: I have been playing a game nonstop with a "
                "futuristic setting and gameplay called Cyberpunk 2077."
            ),
            source_id="locomo:conv-fixture:session_23:D23:17:turn",
        ),
    )
    generic_noise = tuple(
        _answer_support_item(
            f"noise_{index}",
            f"D{index}:1 Riley talked about gaming gear and tournament schedules.",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
        )
        for index in range(30, 38)
    )

    result = ContextPacker().pack(
        bundle_id="ctx_named_video_games",
        items=(*generic_noise, *named_games),
        token_budget=360,
        query="What video games does Riley play?",
        max_rendered_chars=2200,
    )

    rendered = result.bundle.rendered_text
    assert "Counter-Strike: Global Offensive" in rendered
    assert "Street Fighter tournament" in rendered
    assert "Valorant tournament" in rendered
    assert "Xenoblade Chronicles" in rendered
    assert "Cyberpunk 2077" in rendered


def _expansion_query(plan: QueryExpansionPlan, reason: str) -> str:
    for expansion in plan.expansions:
        if expansion.reason == reason:
            return expansion.query
    raise AssertionError(f"missing expansion {reason}")


def _answer_support_item(
    item_id: str,
    text: str,
    *,
    source_id: str,
    source_type: str = "locomo_turn",
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.9,
        source_refs=(SourceRef(source_type=source_type, source_id=source_id),),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "score_signals": {
                "query_expansion_reason": "board_game_inventory_bridge",
                "distinctive_term_hits": 8,
            },
        },
    )
