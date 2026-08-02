from __future__ import annotations

from infinity_context_core.application.context_count_cardinality import (
    keyword_aggregation_intent,
)
from infinity_context_core.application.context_query_decomposition import (
    build_query_decomposition_plan,
)
from infinity_context_core.application.context_temporal_interval_requirements import (
    temporal_interval_requirements,
)
from infinity_context_core.domain.aggregation_admission import AggregationIntent


def test_temporal_interval_requirements_extract_two_explicit_between_boundaries() -> None:
    requirements = temporal_interval_requirements(
        "How many days passed between the day Morgan started watering a herb garden "
        "and the day Morgan harvested fresh herbs?"
    )

    assert [(endpoint.slot_id, endpoint.query) for endpoint in requirements.endpoints] == [
        (
            "decomposition_temporal_interval_endpoint_1",
            "the day Morgan started watering a herb garden",
        ),
        (
            "decomposition_temporal_interval_endpoint_2",
            "the day Morgan harvested fresh herbs",
        ),
    ]
    assert requirements.explicit is True


def test_temporal_interval_requirements_support_from_to_and_reject_implicit_queries() -> None:
    from_to = temporal_interval_requirements(
        "How much time passed from the day Lina planted tomatoes "
        "to the day Lina picked ripe tomatoes?"
    )

    assert [endpoint.query for endpoint in from_to.endpoints] == [
        "the day Lina planted tomatoes",
        "the day Lina picked ripe tomatoes",
    ]
    for query in (
        "How long did Morgan water the herb garden?",
        "How many days until Morgan harvests herbs?",
        "What changed between Morgan starting and harvesting?",
        "How many days passed between Monday and Monday?",
    ):
        assert temporal_interval_requirements(query).endpoints == ()


def test_temporal_interval_requirements_are_bounded_to_two_short_question_terms() -> None:
    long_boundary = " ".join(["growing"] * 100)

    requirements = temporal_interval_requirements(
        f"How many days passed between {long_boundary} and Morgan harvested herbs?"
    )

    assert requirements.endpoints == ()


def test_interval_decomposition_reserves_exactly_two_endpoints_without_preference_noise() -> None:
    query = (
        "How many days passed between the day Morgan started watering a herb garden "
        "and the day Morgan harvested fresh herbs?"
    )

    plan = build_query_decomposition_plan(query)
    interval_items = tuple(
        item
        for item in plan.decompositions
        if item.reason.startswith("decomposition_temporal_interval_endpoint_")
    )

    assert [item.reason for item in plan.decompositions[:2]] == [
        "decomposition_temporal_interval_endpoint_1",
        "decomposition_temporal_interval_endpoint_2",
    ]
    assert len(interval_items) == 2
    assert "decomposition_comparison_preference" not in {
        item.reason for item in plan.decompositions
    }


def test_interval_cardinality_uses_sequence_before_generic_count() -> None:
    query = (
        "How many days passed between the day Morgan started watering a herb garden "
        "and the day Morgan harvested fresh herbs?"
    )

    assert keyword_aggregation_intent(query) is AggregationIntent.SEQUENCE
    assert keyword_aggregation_intent("How many days did Morgan water the herb garden?") is (
        AggregationIntent.COUNT
    )

