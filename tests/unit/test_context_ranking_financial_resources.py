from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import (
    best_query_relevance,
    keyword_chunk_score,
    query_expansion_reason_priority,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    PRECISE_TURN_SOURCE_SIBLING_REASONS,
)


def test_financial_resources_inference_reason_has_bounded_high_signal_policy() -> None:
    plan = build_query_expansion_plan("What might John's financial status be?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "John has substantial income and savings, enough money to cover bills "
            "and expenses, and financial resources in reserve."
        ),
    )

    score = keyword_chunk_score(
        relevance,
        query_expansion_reason="decomposition_financial_resources_inference",
    )
    unregistered_score = keyword_chunk_score(
        relevance,
        query_expansion_reason="unregistered_financial_resources_reason",
    )

    assert reason == "decomposition_financial_resources_inference"
    assert relevance.distinctive_term_hits >= 4
    assert (
        query_expansion_reason_priority("decomposition_financial_resources_inference")
        == 3
    )
    assert unregistered_score + 0.03 <= score <= 0.96
    assert (
        "decomposition_financial_resources_inference"
        not in PRECISE_TURN_SOURCE_SIBLING_REASONS
    )
