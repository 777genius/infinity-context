from infinity_context_core.application.context_query_decomposition import (
    build_query_decomposition_plan,
)


def test_query_decomposition_adds_value_answer_unit_query() -> None:
    plan = build_query_decomposition_plan(
        "What was the deposit amount for Mia's ceramics class?"
    )
    decompositions = {item.reason: item.query for item in plan.decompositions}

    assert "decomposition_value_answer" in decompositions
    assert "deposit" in decompositions["decomposition_value_answer"]
    assert "dollars" in decompositions["decomposition_value_answer"]
