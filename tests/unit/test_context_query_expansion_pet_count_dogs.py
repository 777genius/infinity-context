from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)


def test_query_expansion_routes_dog_count_questions_to_pet_count() -> None:
    plan = build_query_expansion_plan(
        "How many dogs has Maria adopted from the shelter?"
    )

    pet_query = next(
        expansion.query
        for expansion in plan.expansions
        if expansion.reason == "pet_count_bridge"
    )

    assert "dog dogs" in pet_query
    assert "adopted another dog" in pet_query
    assert "animal shelter" in pet_query
