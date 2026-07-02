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


def test_query_decomposition_adds_frequency_recurrence_query() -> None:
    plan = build_query_decomposition_plan("How often does Maria volunteer at the shelter?")

    recurrence = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_frequency_recurrence"
    )

    assert recurrence.query.casefold().startswith("maria ")
    assert "volunteer" in recurrence.query.casefold()
    assert "frequency recurrence cadence" in recurrence.query
    assert "every each daily weekly monthly yearly" in recurrence.query


def test_query_decomposition_carries_activity_terms_for_frequency_questions() -> None:
    cases = (
        ("How often does Melanie go to the beach with her kids?", "beach"),
        ("How often does John take his kids to the library?", "library"),
        ("How often does Audrey take her dogs for walks?", "walks"),
        ("How often does Sam get health checkups?", "checkups"),
    )

    for query, expected_term in cases:
        plan = build_query_decomposition_plan(query)
        recurrence = next(
            item
            for item in plan.decompositions
            if item.reason == "decomposition_frequency_recurrence"
        )

        assert expected_term in recurrence.query.casefold()
        assert "every other" in recurrence.query
        assert "every few" in recurrence.query


def test_query_decomposition_adds_russian_frequency_recurrence_query() -> None:
    plan = build_query_decomposition_plan("Как часто Мария волонтерит в приюте?")

    recurrence = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_frequency_recurrence"
    )

    assert recurrence.query.casefold().startswith("мария ")
    assert "frequency recurrence cadence" in recurrence.query


def test_query_decomposition_does_not_treat_generic_how_as_frequency() -> None:
    plan = build_query_decomposition_plan("Как Мария познакомилась с Алексом?")

    assert "decomposition_frequency_recurrence" not in {
        item.reason for item in plan.decompositions
    }


def test_query_decomposition_keeps_how_many_times_as_count_not_frequency() -> None:
    plan = build_query_decomposition_plan(
        "How many times has Melanie gone to the beach in 2023?"
    )

    reasons = {item.reason for item in plan.decompositions}

    assert "decomposition_quantity_count" in reasons
    assert "decomposition_frequency_recurrence" not in reasons


def test_best_query_relevance_uses_frequency_recurrence_decomposition() -> None:
    plan = build_query_expansion_plan("How often does Maria volunteer at the shelter?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Maria volunteers at the homeless shelter every weekend and often helps on Fridays.",
    )

    assert reason == "decomposition_frequency_recurrence"
    assert relevance.distinctive_term_hits >= 4


def test_best_query_relevance_uses_frequency_recurrence_for_common_activity_topics() -> None:
    cases = (
        (
            "How often does Melanie go to the beach with her kids?",
            "Melanie takes her kids to the beach every other weekend.",
        ),
        (
            "How often does Audrey take her dogs for walks?",
            "Audrey walks her dogs twice weekly and meets other dog owners.",
        ),
        (
            "How often does Sam get health checkups?",
            "Sam schedules health checkups every few months.",
        ),
    )

    for query, text in cases:
        _, reason, relevance = best_query_relevance(
            build_query_expansion_plan(query),
            text=text,
        )

        assert reason == "decomposition_frequency_recurrence"
        assert relevance.distinctive_term_hits >= 4


def test_deterministic_rerank_prefers_recurring_frequency_evidence() -> None:
    query = "How often does Maria volunteer at the shelter?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    recurring = _item(
        "recurring",
        score=0.72,
        text=(
            "D4:1 Maria volunteers at the homeless shelter every weekend "
            "and often helps on Friday nights."
        ),
    )
    one_time = _item(
        "one_time",
        score=0.755,
        text="D2:3 Maria visited the homeless shelter once for orientation.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (one_time, recurring),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["recurring"].score > by_id["one_time"].score
    assert (
        "frequency_recurrence_exact_evidence"
        in by_id["recurring"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "frequency_recurrence_one_time_noise"
        in by_id["one_time"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_less_formulaic_recurrence_phrases() -> None:
    query = "How often does Audrey take her dogs for walks?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    recurring = _item(
        "recurring",
        score=0.72,
        text="D4:1 Audrey walks her dogs twice weekly and visits the park each Sunday.",
    )
    one_time = _item(
        "one_time",
        score=0.755,
        text="D2:3 Audrey took her dogs to the park once for a practice session.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (one_time, recurring),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["recurring"].score > by_id["one_time"].score
    assert (
        "frequency_recurrence_exact_evidence"
        in by_id["recurring"].diagnostics["provenance"]["deterministic_rerank_reasons"]
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
