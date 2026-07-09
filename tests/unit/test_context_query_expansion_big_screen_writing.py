from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance


def test_query_expansion_bridges_big_screen_writing_count_evidence() -> None:
    plan = build_query_expansion_plan(
        "How many of Dana's writing projects made it to the big screen?"
    )

    screenplay_query = next(
        expansion.query
        for expansion in plan.expansions
        if expansion.reason == "screenplay_count_bridge"
    )
    assert "contributed bits words" in screenplay_query
    assert "big screen" in screenplay_query

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D12:1 Dana wrote a few bits for a screenplay that appeared "
            "on the big screen yesterday, and it was inspiring."
        ),
    )

    assert reason == "screenplay_count_bridge"
    assert relevance.distinctive_term_hits >= 5
