import pytest
from infinity_context_core.application.context_query_decomposition import (
    build_query_decomposition_plan,
)
from infinity_context_core.application.context_query_financial_resources_inference import (
    FINANCIAL_RESOURCES_INFERENCE_TAIL,
)


@pytest.mark.parametrize(
    "query",
    (
        "What might John's financial status be?",
        "What could Maria's economic situation suggest?",
        "What might Alex's income and resources suggest?",
    ),
)
def test_query_decomposition_adds_financial_resources_inference(query: str) -> None:
    plan = build_query_decomposition_plan(query)
    reasons = {item.reason for item in plan.decompositions}
    financial = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_financial_resources_inference"
    )

    assert (
        "household family dependents children kids material needs resources assets"
        in financial.query
    )
    assert (
        "surplus scarcity inequality disparity income salary earnings bills expenses"
        in financial.query
    )
    assert "wealth savings debt budget security" in financial.query
    assert "others" not in FINANCIAL_RESOURCES_INFERENCE_TAIL.split()
    assert "charity" not in FINANCIAL_RESOURCES_INFERENCE_TAIL.split()
    assert "donations" not in FINANCIAL_RESOURCES_INFERENCE_TAIL.split()
    assert "giving" not in FINANCIAL_RESOURCES_INFERENCE_TAIL.split()
    assert "help" not in FINANCIAL_RESOURCES_INFERENCE_TAIL.split()
    assert "so much" not in FINANCIAL_RESOURCES_INFERENCE_TAIL
    assert "others don't" not in FINANCIAL_RESOURCES_INFERENCE_TAIL
    assert "need something" not in FINANCIAL_RESOURCES_INFERENCE_TAIL
    assert "decomposition_inference_support" in reasons


@pytest.mark.parametrize(
    "query",
    (
        "What might John's relationship status be?",
        "What might John's financial account status be?",
        "What might John's API endpoint status be?",
        "What might John's order status be?",
        "What might John's camera purchase price be?",
        "What charities does John support?",
        "Could John's financial status be poor?",
        "What might John's colleague's financial status be?",
        "What might John's financial advisor's status be?",
        "What might John's financial status not be?",
        "What might John's financial status be if it isn't clear?",
        "What might someone's financial status be?",
    ),
)
def test_query_decomposition_rejects_unrelated_financial_resources_inference(
    query: str,
) -> None:
    plan = build_query_decomposition_plan(query)

    assert "decomposition_financial_resources_inference" not in {
        item.reason for item in plan.decompositions
    }
