from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance


def _expansion_query(plan, reason: str) -> str:
    for expansion in plan.expansions:
        if expansion.reason == reason:
            return expansion.query
    raise AssertionError(f"missing expansion reason: {reason}")


def test_query_expansion_covers_where_camping_location_wording() -> None:
    plan = build_query_expansion_plan("Where has Alex gone camping?")

    reasons = {expansion.reason for expansion in plan.expansions}

    assert "camping_location_bridge" in reasons
    assert "camping_detail_bridge" in reasons
    assert "campsite campground" in _expansion_query(plan, "camping_location_bridge")
    assert "location place" in _expansion_query(plan, "camping_location_bridge")


def test_best_query_relevance_prefers_camping_location_for_place_evidence() -> None:
    plan = build_query_expansion_plan("Where has Alex gone camping?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D6:16 Alex: We went camping at a beach campground near the lake, "
            "then hiked the forest trail the next morning."
        ),
    )

    assert reason == "camping_location_bridge"
    assert relevance.distinctive_term_hits >= 6
