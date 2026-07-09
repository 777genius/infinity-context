from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance


def test_query_expansion_bridges_gave_joy_to_gift_object_evidence() -> None:
    plan = build_query_expansion_plan(
        "What is something Sam gave Dana that brings her a lot of joy?"
    )

    gift_query = next(
        expansion.query
        for expansion in plan.expansions
        if expansion.reason == "possession_gift_object_bridge"
    )
    assert "stuffed animal toy" in gift_query
    assert "brings joy" in gift_query

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D20:2 Dana opened the conversation after finishing a recipe. "
            "Related turns: D20:4. "
            "D20:4 Dana has a stuffed animal dog named Pippa that was a gift "
            "from Sam. Related turns: D20:8. "
            "D20:8 Pippa brings Dana so much joy and helps her focus."
        ),
    )

    assert reason == "possession_gift_object_bridge"
    assert relevance.distinctive_term_hits >= 6
