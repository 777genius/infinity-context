from __future__ import annotations

from infinity_context_server.memory_comparison_rerank import (
    decomposed_search_queries,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase


def test_commonality_queries_get_shared_attribute_support_fanout() -> None:
    case = _case("What do Alex and Riley have in common?")

    queries, diagnostics = decomposed_search_queries(case)
    query_plan = diagnostics["query_plan"]

    assert "commonality_support" in query_plan["selected_roles"]
    assert "commonality_support" in query_plan["selected_role_families"]
    assert "commonality_support" in query_plan["recommended_role_families"]
    assert query_plan["missing_recommended_role_families"] == []
    commonality_query = _selected_query(query_plan, role="commonality_support")
    assert "alex" in commonality_query
    assert "riley" in commonality_query
    assert "common shared both mutual" in commonality_query
    assert commonality_query in tuple(query.casefold() for query in queries)


def test_commonality_support_covers_shared_place_activity_and_event_shapes() -> None:
    place = _case("Which shared place connects Alex and Riley?")
    activity = _case("Which shared activity connects Alex and Riley?")
    event = _case("What common event involved both Alex and Riley?")

    for case in (place, activity, event):
        _, diagnostics = decomposed_search_queries(case)
        query_plan = diagnostics["query_plan"]
        commonality_query = _selected_query(query_plan, role="commonality_support")

        assert query_plan["missing_recommended_role_families"] == []
        assert "commonality_support" in query_plan["selected_roles"]
        assert "alex" in commonality_query
        assert "riley" in commonality_query


def test_commonality_support_requires_two_entities() -> None:
    case = _case("What does Alex have in common with the team?")

    _, diagnostics = decomposed_search_queries(case)
    query_plan = diagnostics["query_plan"]

    assert "commonality_support" not in query_plan["selected_roles"]
    assert "commonality_support" not in query_plan["recommended_role_families"]


def _case(question: str) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="unit",
        case_id="commonality-support",
        question=question,
        expected_terms=(),
    )


def _selected_query(query_plan: dict[str, object], *, role: str) -> str:
    selected = query_plan["selected"]
    assert isinstance(selected, list)
    for item in selected:
        assert isinstance(item, dict)
        if item["role"] == role:
            return str(item["query"]).casefold()
    raise AssertionError(f"missing selected query role: {role}")
