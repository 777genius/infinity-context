from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance


def test_query_expansion_bridges_implicit_book_suggestion_language() -> None:
    plan = build_query_expansion_plan("What book recommendations has Dana given Lee?")

    suggestion_query = next(
        expansion.query
        for expansion in plan.expansions
        if expansion.reason == "book_suggestion_bridge"
    )
    assert "must-see" in suggestion_query
    assert "great one" in suggestion_query

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            'D3:17 Dana: I just watched "Moon Garden" and it was amazing. '
            "Definitely a must-see!"
        ),
    )

    assert reason == "book_suggestion_bridge"
    assert relevance.distinctive_term_hits >= 3
