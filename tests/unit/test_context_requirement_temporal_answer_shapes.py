import pytest
from infinity_context_core.application.context_query_intent import (
    build_query_anchor_intent,
)
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)


def _requested_answer_shapes(query: str) -> list[str]:
    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(),
    )
    return list(coverage["requested_answer_shapes"])


def test_subordinate_when_clause_does_not_request_temporal_answer_shape() -> None:
    query = "What does Nate want to do when he goes over to Joanna's place?"

    assert "temporal" not in _requested_answer_shapes(query)


@pytest.mark.parametrize(
    "query",
    [
        "When did Andrew adopt Scout?",
        "What date did Nate visit Joanna?",
        "What did Alex say two weeks ago?",
    ],
)
def test_direct_or_relative_temporal_query_requests_temporal_answer_shape(
    query: str,
) -> None:
    assert "temporal" in _requested_answer_shapes(query)
