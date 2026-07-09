from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slots,
)
from infinity_context_core.application.context_packer import (
    _answer_support_diversity_candidates,
    _ordered_answer_support_families_for_query,
)
from infinity_context_core.application.context_packer_answer_support_slots import (
    _inventory_answer_slot,
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


def test_query_expansion_covers_gratitude_note_people_inventory() -> None:
    plan = build_query_expansion_plan("Who has written notes of gratitude to Riley?")

    bridge = _expansion_query(plan, "volunteering_people_inventory_bridge")

    assert bridge.startswith("Riley ")
    assert "gratitude appreciation thank" in bridge
    assert "residents" in bridge


def test_query_expansion_covers_shelter_food_dropoff_inventory() -> None:
    plan = build_query_expansion_plan(
        "What food item did Riley drop off at the homeless shelter?"
    )

    bridge = _expansion_query(plan, "volunteering_inventory_bridge")

    assert bridge.startswith("Riley ")
    assert "drop off dropped off" in bridge
    assert "shelter food meal baked goods" in bridge


def test_query_expansion_covers_skill_teaching_inventory() -> None:
    plan = build_query_expansion_plan("What skills has Riley helped others learn?")

    bridge = _expansion_query(plan, "skill_teaching_inventory_bridge")

    assert bridge.startswith("Riley ")
    assert "skills helped others learn" in bridge
    assert "teach teaching taught" in bridge
    assert "tips improve practice" in bridge


def test_query_expansion_covers_game_win_counts() -> None:
    plan = build_query_expansion_plan("How many games has Riley mentioned winning?")

    bridge = _expansion_query(plan, "game_win_count_bridge")

    assert bridge.startswith("Riley ")
    assert "games game won winning" in bridge
    assert "count total number" in bridge


def test_source_sibling_answer_evidence_accepts_gratitude_note_turns() -> None:
    expansion = _expansion_query(
        build_query_expansion_plan("Who has written notes of gratitude to Riley?"),
        "volunteering_people_inventory_bridge",
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion,
        expansion_reason="volunteering_people_inventory_bridge",
        text=(
            "D12:8 Riley: One of the shelter residents wrote a heartfelt "
            "note of gratitude about the support they received."
        ),
    )
    assert "gratitude_note_writer" in aggregation_answer_slots(
        query=expansion,
        text=(
            "D12:8 Riley: One of the shelter residents wrote a heartfelt "
            "note of gratitude about the support they received."
        ),
    )


def test_source_sibling_answer_evidence_accepts_shelter_food_dropoffs() -> None:
    expansion = _expansion_query(
        build_query_expansion_plan(
            "What food item did Riley drop off at the homeless shelter?"
        ),
        "volunteering_inventory_bridge",
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion,
        expansion_reason="volunteering_inventory_bridge",
        text=(
            "D25:9 Riley: I dropped off baked goods and meals at the "
            "homeless shelter after the volunteer shift."
        ),
    )
    assert "shelter_food_dropoff" in aggregation_answer_slots(
        query=expansion,
        text=(
            "D25:9 Riley: I dropped off baked goods and meals at the "
            "homeless shelter after the volunteer shift."
        ),
    )


def test_source_sibling_answer_evidence_accepts_skill_teaching_turns() -> None:
    expansion = _expansion_query(
        build_query_expansion_plan("What skills has Riley helped others learn?"),
        "skill_teaching_inventory_bridge",
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion,
        expansion_reason="skill_teaching_inventory_bridge",
        text=(
            "D18:8 Riley: I started teaching people how to make a dessert "
            "recipe, and sharing what I know has been rewarding."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion,
        expansion_reason="skill_teaching_inventory_bridge",
        text=(
            "D14:16 Riley: They asked for tips on how to improve their game, "
            "so I helped coach them through practice."
        ),
    )


def test_source_sibling_answer_evidence_accepts_game_win_count_turns() -> None:
    expansion = _expansion_query(
        build_query_expansion_plan("How many games has Riley mentioned winning?"),
        "game_win_count_bridge",
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion,
        expansion_reason="game_win_count_bridge",
        text=(
            "D3:3 Riley: We pulled off a tough win after I scored the last "
            "basket, and the team celebrated the victory."
        ),
    )
    assert "game_win_result" in aggregation_answer_slots(
        query=expansion,
        text=(
            "D3:3 Riley: We pulled off a tough win after I scored the last "
            "basket, and the team celebrated the victory."
        ),
    )


def test_best_query_relevance_routes_inventory_recall_patterns() -> None:
    cases = (
        (
            "What food item did Riley drop off at the homeless shelter?",
            (
                "D25:19 Riley: I dropped off cakes and baked goods at the "
                "homeless shelter after the volunteer shift."
            ),
            "volunteering_inventory_bridge",
        ),
        (
            "Who has written notes of gratitude to Riley?",
            (
                "D27:8 Riley: One of the residents at the shelter, Cindy, "
                "wrote a heartfelt expression of gratitude."
            ),
            "volunteering_people_inventory_bridge",
        ),
        (
            "What skills has Riley helped others learn?",
            (
                "D18:8 Riley: I started teaching people how to make a dessert "
                "recipe and shared my love of dairy-free desserts."
            ),
            "skill_teaching_inventory_bridge",
        ),
        (
            "How many games has Riley mentioned winning?",
            (
                "D3:3 Riley: We pulled off a tough win after I scored the "
                "last basket, and the team celebrated the victory."
            ),
            "game_win_count_bridge",
        ),
    )

    for query, text, expected_reason in cases:
        _, reason, _ = best_query_relevance(build_query_expansion_plan(query), text=text)

        assert reason == expected_reason


def test_inventory_answer_slots_cover_inventory_recall_patterns() -> None:
    cases = (
        (
            "volunteering_inventory_bridge",
            "D25:19 Riley: I dropped off cakes at the homeless shelter.",
            "shelter_food_dropoff",
        ),
        (
            "volunteering_people_inventory_bridge",
            "D27:8 Riley: A shelter resident wrote a note of gratitude.",
            "gratitude_note_writer",
        ),
        (
            "skill_teaching_inventory_bridge",
            "D18:8 Riley: I taught people how to make a dessert recipe.",
            "skill_recipe_teaching",
        ),
        (
            "game_win_count_bridge",
            "D3:3 Riley: The team won a tight basketball game.",
            "game_win_result",
        ),
    )

    for reason, text, expected_slot in cases:
        assert _inventory_answer_slot(_item(text), query_reason=reason) == expected_slot


def test_precise_inventory_recall_slots_precede_broad_marker_coverage() -> None:
    broad_shelter_history = _item(
        (
            "D1:3 Riley: I volunteer at the homeless shelter. "
            "D1:5 Riley: The support work has been meaningful. "
            "D1:7 Riley: I helped with the front desk."
        ),
        item_id="broad_shelter_history",
        reason="volunteering_inventory_bridge",
        source_id="locomo:conv-fixture:session_1",
    )
    exact_dropoff = _item(
        "D26:1 Riley: Last week I dropped off cakes at the homeless shelter.",
        item_id="exact_dropoff",
        reason="volunteering_inventory_bridge",
        source_id="locomo:conv-fixture:session_26:D26:1:turn",
    )

    candidates = _answer_support_diversity_candidates(
        [broad_shelter_history, exact_dropoff]
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What food item did Riley drop off at the homeless shelter?",
    )

    assert candidates[ordered[0]].item_id == "exact_dropoff"


def _expansion_query(plan: QueryExpansionPlan, reason: str) -> str:
    for expansion in plan.expansions:
        if expansion.reason == reason:
            return expansion.query
    raise AssertionError(f"missing expansion {reason!r}: {plan.expansions!r}")


def _item(
    text: str,
    *,
    item_id: str = "candidate",
    reason: str | None = None,
    source_id: str = "fixture:turn",
) -> ContextItem:
    diagnostics = None
    if reason is not None:
        diagnostics = {
            "memory_scope_id": "memory_scope_default",
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "source_id": source_id,
            "source_type": "locomo_turn",
            "score_signals": {
                "query_expansion_reason": reason,
                "source_sibling_answer_evidence": 1,
            },
        }
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics=diagnostics,
    )
