from infinity_context_core.application.context_query_expansion import (
    QueryExpansionPlan,
    build_query_expansion_plan,
)


def test_person_relation_expansion_covers_extended_family_questions() -> None:
    cousin = build_query_expansion_plan("Who is Dana's cousin?")
    aunt = build_query_expansion_plan("Who is the aunt of Dana?")
    grandparent = build_query_expansion_plan("Who is Dana's grandmother?")

    for plan in (cousin, aunt, grandparent):
        expansion_query = _expansion_query(plan, "person_relation_inventory_bridge")
        assert "family relatives" in expansion_query
        assert "cousin aunt uncle grandmother" in expansion_query

    assert "Dana" in _expansion_query(cousin, "person_relation_inventory_bridge")
    assert "Dana" in _expansion_query(aunt, "person_relation_inventory_bridge")
    assert "Dana" in _expansion_query(grandparent, "person_relation_inventory_bridge")


def _expansion_query(plan: QueryExpansionPlan, reason: str) -> str:
    return next(item.query for item in plan.expansions if item.reason == reason)
