from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance


def test_query_expansion_bridges_writing_kind_to_inventory_evidence() -> None:
    plan = build_query_expansion_plan("What kinds of writing does Dana do?")

    inventory_query = next(
        expansion.query
        for expansion in plan.expansions
        if expansion.reason == "creative_writing_inventory_bridge"
    )
    assert "screenplay screenplays" in inventory_query
    assert "online blog post" in inventory_query

    _, reason, relevance = best_query_relevance(
        plan,
        text="D17:14 Dana started on a book recently after her movie did well.",
    )

    assert reason == "creative_writing_inventory_bridge"
    assert relevance.distinctive_term_hits >= 4


def test_query_expansion_bridges_travel_hobby_to_writing_and_destination_evidence() -> None:
    plan = build_query_expansion_plan(
        "What would be a good hobby related to Avery's travel dreams?"
    )

    travel_writing_query = next(
        expansion.query
        for expansion in plan.expansions
        if expansion.reason == "travel_hobby_writing_bridge"
    )
    assert "writing write wrote written" in travel_writing_query
    assert "travel traveling travelling" in travel_writing_query

    _, writing_reason, writing_relevance = best_query_relevance(
        plan,
        text=(
            "D4:1 Avery: I am writing articles about fantasy novels for an "
            "online magazine, and it is so rewarding."
        ),
    )
    _, travel_reason, travel_relevance = best_query_relevance(
        plan,
        text=(
            "D7:9 Avery: I love traveling too. Have you been to Paris? "
            "The tower there looks incredible."
        ),
    )

    assert writing_reason == "travel_hobby_writing_bridge"
    assert writing_relevance.distinctive_term_hits >= 4
    assert travel_reason == "travel_hobby_writing_bridge"
    assert travel_relevance.distinctive_term_hits >= 4
