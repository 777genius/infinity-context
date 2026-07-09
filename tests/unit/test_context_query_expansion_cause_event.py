from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance


def test_query_expansion_bridges_cause_events_to_event_cause_evidence() -> None:
    plan = build_query_expansion_plan("What causes has Jordan done events for?")

    cause_query = next(
        expansion.query
        for expansion in plan.expansions
        if expansion.reason == "cause_event_inventory_bridge"
    )
    assert "community food drive" in cause_query
    assert "toy drive" in cause_query
    assert "domestic abuse" in cause_query

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Jordan organized a community food drive after seeing how unemployment "
            "affected neighbors."
        ),
    )

    assert reason == "cause_event_inventory_bridge"
    assert relevance.distinctive_term_hits >= 4
