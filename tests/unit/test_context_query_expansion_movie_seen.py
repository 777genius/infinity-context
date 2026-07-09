from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance


def test_query_expansion_bridges_movies_seen_to_common_interest_evidence() -> None:
    plan = build_query_expansion_plan("What movies have both Sam and Dana seen?")

    commonality_query = next(
        expansion.query
        for expansion in plan.expansions
        if expansion.reason == "commonality_interest_bridge"
    )
    assert "watched saw seen recently" in commonality_query
    assert "recommendation recommended movie film" in commonality_query

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D12:8 Sam: I watched \"Moon Garden\" recently, and it was great. "
            "The acting was strong and the story was captivating."
        ),
    )

    assert reason == "commonality_interest_bridge"
    assert relevance.distinctive_term_hits >= 5
