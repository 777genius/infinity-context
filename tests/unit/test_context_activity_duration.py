from infinity_context_core.application.context_query_decomposition import (
    build_query_decomposition_plan,
)
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
    best_query_relevance,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_query_decomposition_adds_activity_duration_query() -> None:
    plan = build_query_decomposition_plan("How long has Maria volunteered at the shelter?")

    duration = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_activity_duration"
    )

    assert duration.query.casefold().startswith("maria ")
    assert "volunteer" in duration.query.casefold()
    assert "duration since for years months" in duration.query
    assert "started in began in" in duration.query


def test_query_decomposition_adds_how_many_units_activity_duration_query() -> None:
    plan = build_query_decomposition_plan(
        "How many years has Maria volunteered at the shelter?"
    )

    duration = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_activity_duration"
    )

    assert duration.query.casefold().startswith("maria ")
    assert "volunteer" in duration.query.casefold()
    assert "duration since for years months" in duration.query


def test_query_decomposition_adds_russian_activity_duration_query() -> None:
    plan = build_query_decomposition_plan("Как долго Мария волонтерит в приюте?")

    duration = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_activity_duration"
    )

    assert duration.query.casefold().startswith("мария ")
    assert "duration since for years months" in duration.query


def test_activity_duration_does_not_capture_relationship_duration_query() -> None:
    plan = build_query_decomposition_plan("How long has Alex known Maria?")

    assert "decomposition_activity_duration" not in {
        item.reason for item in plan.decompositions
    }


def test_best_query_relevance_uses_activity_duration_decomposition() -> None:
    plan = build_query_expansion_plan("How long has Maria lived in Sweden?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Maria has lived in Sweden for three years and still calls it home.",
    )

    assert reason == "decomposition_activity_duration"
    assert relevance.distinctive_term_hits >= 4


def test_deterministic_rerank_prefers_activity_duration_evidence() -> None:
    query = "How long has Maria volunteered at the shelter?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    exact = _item(
        "volunteered_for_years",
        score=0.72,
        text="D4:1 Maria has volunteered at the homeless shelter for three years.",
    )
    topic_only = _item(
        "shelter_topic",
        score=0.755,
        text="D2:3 Maria volunteers at the homeless shelter and likes the team.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_only, exact),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["volunteered_for_years"].score > by_id["shelter_topic"].score
    assert (
        "activity_duration_exact_evidence"
        in by_id["volunteered_for_years"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "activity_duration_weak_evidence"
        in by_id["shelter_topic"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_accepts_qualitative_duration_evidence() -> None:
    query = "How many months has Lina been taking pottery classes?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    exact = _item(
        "taking_for_few_months",
        score=0.72,
        text="D4:1 Lina has been taking pottery classes for a few months.",
    )
    topic_only = _item(
        "pottery_topic",
        score=0.755,
        text="D2:3 Lina takes pottery classes and enjoys the clay work.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_only, exact),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["taking_for_few_months"].score > by_id["pottery_topic"].score
    assert (
        "activity_duration_exact_evidence"
        in by_id["taking_for_few_months"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def _item(item_id: str, *, score: float, text: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"base_score": score},
            "provenance": {"retrieval_sources": ["keyword_chunks"]},
        },
    )
