from infinity_context_core.application.context_query_decomposition import (
    build_query_decomposition_plan,
)
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance


def test_query_decomposition_splits_compound_event_artifact_query() -> None:
    plan = build_query_decomposition_plan(
        "What changed after the call with Alex about Atlas and what text was in the screenshot?"
    )

    reasons = [item.reason for item in plan.decompositions]
    queries = [item.query.casefold() for item in plan.decompositions]
    assert reasons.count("decomposition_clause") == 2
    assert "decomposition_event_context" in reasons
    assert "decomposition_temporal_change" in reasons
    assert "decomposition_artifact_evidence" in reasons
    assert any("alex atlas what text was in the screenshot" in query for query in queries)
    assert any("changed updated current previous" in query for query in queries)
    assert any("screenshot image video audio document ocr" in query for query in queries)
    assert plan.diagnostics()["query_decomposition_status"] == "available"


def test_query_decomposition_handles_russian_event_artifact_query() -> None:
    plan = build_query_decomposition_plan(
        "Что изменилось после созвона с алексом по Атласу и что было на скриншоте?"
    )

    queries = [item.query.casefold() for item in plan.decompositions]
    assert any("алекс" in query and "атлас" in query for query in queries)
    assert any("changed updated current previous" in query for query in queries)
    assert any("artifact file screenshot image video audio" in query for query in queries)


def test_query_decomposition_is_bounded_and_deduplicated() -> None:
    plan = build_query_decomposition_plan(
        "What changed after the call with Alex about Atlas and what changed after "
        "the call with Alex about Atlas and show source and screenshot and video?"
    )

    queries = [item.query.casefold() for item in plan.decompositions]
    assert len(plan.decompositions) <= 6
    assert len(queries) == len(set(queries))
    assert plan.diagnostics()["query_decomposition_count"] == len(plan.decompositions)


def test_query_expansion_plan_uses_decompositions_for_retrieval_queries() -> None:
    plan = build_query_expansion_plan(
        "What changed after the meeting with Alex and what was written in the screenshot?"
    )

    retrieval_reasons = [item.reason for item in plan.retrieval_queries]
    assert retrieval_reasons[0] == "original_query"
    assert "decomposition_temporal_change" in retrieval_reasons
    assert "decomposition_artifact_evidence" in retrieval_reasons
    assert "change_over_time_bridge" in retrieval_reasons
    assert plan.diagnostics()["query_decomposition_count"] > 0


def test_best_query_relevance_uses_decomposed_artifact_query() -> None:
    plan = build_query_expansion_plan(
        "What changed after the call with Alex about Atlas and what was written in the screenshot?"
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Screenshot OCR detected text: Atlas launch deadline moved after "
            "the Alex call."
        ),
    )

    assert reason == "decomposition_artifact_evidence"
    assert relevance.distinctive_term_hits >= 4
