from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance


def test_query_expansion_bridges_submitted_work_to_destination_evidence() -> None:
    plan = build_query_expansion_plan("What places has Dana submitted her work to?")

    submission_query = next(
        expansion.query
        for expansion in plan.expansions
        if expansion.reason == "creative_work_submission_bridge"
    )
    assert "film festivals" in submission_query
    assert "producers directors" in submission_query

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D2:7 Dana plans to submit the project to film festivals so "
            "producers and directors can check it out."
        ),
    )

    assert reason == "creative_work_submission_bridge"
    assert relevance.distinctive_term_hits >= 5
