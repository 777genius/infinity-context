from __future__ import annotations

from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_rerank import (
    benchmark_rerank_memories,
    decomposed_search_queries,
    query_retrieval_intent,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase


def test_location_transition_intent_is_question_only() -> None:
    case = _case("Where did Caroline move from?")

    intent = query_retrieval_intent(case)
    profile = intent.to_query_profile()
    facets = {facet.category: facet for facet in intent.relation_intents}

    assert "location_transition" in profile["relation_categories"]
    assert "location_support" in profile["evidence_need"]
    assert facets["location_transition"].evidence_need == "location_support"
    assert "move" in facets["location_transition"].terms
    assert {"country", "home", "origin"} <= set(
        facets["location_transition"].variant_terms
    )
    assert intent.to_diagnostics()["uses_ground_truth"] is False
    assert "Canada" not in str(intent.to_diagnostics())


def test_location_transition_relation_category_boosts_origin_evidence() -> None:
    case = _case("Where did Caroline move from?")
    origin_evidence = RetrievedMemory(
        item_id="origin-evidence",
        rank=2,
        score=0.5,
        text=(
            "D1:4 Caroline: I moved from my home country, Canada, before "
            "settling here."
        ),
        source_refs=("D1:4",),
        metadata={"item_type": "raw_turn"},
    )
    distractor = RetrievedMemory(
        item_id="move-distractor",
        rank=1,
        score=0.55,
        text="D1:3 Caroline: I moved the meeting after work.",
        source_refs=("D1:3",),
        metadata={"item_type": "raw_turn"},
    )

    reranked, diagnostics = benchmark_rerank_memories(
        case,
        (distractor, origin_evidence),
    )

    assert reranked[0].item_id == "origin-evidence"
    assert diagnostics["retrieval_intent"]["uses_ground_truth"] is False
    origin_features = reranked[0].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    origin_signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert origin_features["relation_category_hits"] == ["location_transition"]
    assert origin_features["source_locality_reason_codes"] == [
        "direct_localized_turn"
    ]
    assert origin_signals["benchmark_relation_category_coverage_boost"] > 0
    assert origin_signals["benchmark_location_support_boost"] > 0


def test_location_transition_decomposition_adds_location_support_query() -> None:
    case = _case("Where did Caroline relocate from?")

    queries, diagnostics = decomposed_search_queries(case)

    assert queries == (
        "Where did Caroline relocate from?",
        "caroline from origin home country city place",
        "caroline from origin home country city place location destination near",
    )
    assert diagnostics["query_plan"]["selected_roles"] == [
        "original_question",
        "compact_relation",
        "location_support",
    ]
    assert diagnostics["query_plan"]["recommended_role_families"] == [
        "base_query",
        "relation_compact",
        "location_support",
    ]
    assert "relocate" in diagnostics["query_profile"]["relation_terms"]


def test_location_temporal_decomposition_preserves_time_and_location_support() -> None:
    case = _case("Where did Caroline move from 4 years ago?")

    queries, diagnostics = decomposed_search_queries(case)

    assert queries == (
        "Where did Caroline move from 4 years ago?",
        "caroline from origin home country 4 year ago",
        "caroline from origin home country city place location destination near",
        "caroline ago year session date time",
    )
    assert diagnostics["query_plan"]["selected_roles"] == [
        "original_question",
        "compact_relation",
        "location_support",
        "relative_temporal_support",
    ]
    assert diagnostics["query_plan"]["selected_type_counts"] == {
        "semantic": 1,
        "lexical": 3,
    }


def test_workplace_location_query_gets_location_support_without_answer_leakage() -> None:
    case = _case("Which city was Alex working in?")

    intent = query_retrieval_intent(case)
    queries, diagnostics = decomposed_search_queries(case)
    profile = intent.to_query_profile()
    facets = {facet.category: facet for facet in intent.relation_intents}

    assert "location_transition" in profile["relation_categories"]
    assert "location_support" in profile["evidence_need"]
    assert facets["location_transition"].terms == ("employment",)
    assert {"company", "office", "workplace", "working"} & set(
        facets["location_transition"].variant_terms
    )
    assert diagnostics["query_plan"]["selected_roles"] == [
        "original_question",
        "compact_relation",
        "location_support",
    ]
    assert any(
        "alex work worked working workplace office company city place location" in query
        for query in queries
    )
    assert intent.to_diagnostics()["uses_ground_truth"] is False
    assert "Canada" not in str(intent.to_diagnostics())


def test_workplace_location_rerank_boosts_place_evidence_over_generic_work() -> None:
    case = _case("Which city was Alex working in?")
    place_evidence = RetrievedMemory(
        item_id="workplace-place",
        rank=2,
        score=0.5,
        text="D2:8 Alex: I was working at a design studio in Chicago last summer.",
        source_refs=("D2:8",),
        metadata={"item_type": "raw_turn"},
    )
    generic_work = RetrievedMemory(
        item_id="generic-work",
        rank=1,
        score=0.55,
        text="D2:7 Alex: I was working on a report after dinner.",
        source_refs=("D2:7",),
        metadata={"item_type": "raw_turn"},
    )

    reranked, diagnostics = benchmark_rerank_memories(
        case,
        (generic_work, place_evidence),
    )

    assert reranked[0].item_id == "workplace-place"
    assert diagnostics["retrieval_intent"]["uses_ground_truth"] is False
    features = reranked[0].metadata["diagnostics"]["benchmark_candidate_features"]
    signals = reranked[0].metadata["diagnostics"]["score_signals"]
    assert features["relation_category_hits"] == ["location_transition"]
    assert signals["benchmark_location_support_boost"] > 0


def test_workplace_location_support_requires_place_evidence() -> None:
    case = _case("Which city was Alex working in?")
    place_evidence = RetrievedMemory(
        item_id="workplace-place",
        rank=2,
        score=0.5,
        text="D2:8 Alex: I was working at a design studio in Chicago last summer.",
        source_refs=("D2:8",),
        metadata={"item_type": "raw_turn"},
    )
    workplace_without_place = RetrievedMemory(
        item_id="workplace-no-place",
        rank=1,
        score=0.55,
        text="D2:7 Alex: I was working at a design studio on a new report.",
        source_refs=("D2:7",),
        metadata={"item_type": "raw_turn"},
    )

    reranked, _diagnostics = benchmark_rerank_memories(
        case,
        (workplace_without_place, place_evidence),
    )

    no_place_features = next(
        memory
        for memory in reranked
        if memory.item_id == "workplace-no-place"
    ).metadata["diagnostics"]["benchmark_candidate_features"]
    no_place_signals = next(
        memory
        for memory in reranked
        if memory.item_id == "workplace-no-place"
    ).metadata["diagnostics"]["score_signals"]
    assert reranked[0].item_id == "workplace-place"
    assert no_place_features["relation_category_hits"] == []
    assert no_place_signals["benchmark_location_support_boost"] == 0.0


def test_workplace_location_support_ignores_non_place_work_field() -> None:
    case = _case("Which city was Alex working in?")
    place_evidence = RetrievedMemory(
        item_id="workplace-place",
        rank=2,
        score=0.5,
        text="D2:8 Alex: I was working at a design studio in Chicago last summer.",
        source_refs=("D2:8",),
        metadata={"item_type": "raw_turn"},
    )
    field_evidence = RetrievedMemory(
        item_id="workplace-field",
        rank=1,
        score=0.55,
        text="D2:7 Alex: I was working in marketing on a new report.",
        source_refs=("D2:7",),
        metadata={"item_type": "raw_turn"},
    )

    reranked, _diagnostics = benchmark_rerank_memories(
        case,
        (field_evidence, place_evidence),
    )

    field_features = next(
        memory
        for memory in reranked
        if memory.item_id == "workplace-field"
    ).metadata["diagnostics"]["benchmark_candidate_features"]
    field_signals = next(
        memory
        for memory in reranked
        if memory.item_id == "workplace-field"
    ).metadata["diagnostics"]["score_signals"]
    assert reranked[0].item_id == "workplace-place"
    assert field_features["relation_category_hits"] == []
    assert field_signals["benchmark_location_support_boost"] == 0.0


def test_event_location_rerank_boosts_venue_evidence_over_generic_event() -> None:
    case = _case("Where did Alex attend the concert?")
    venue_evidence = RetrievedMemory(
        item_id="event-venue",
        rank=2,
        score=0.5,
        text="D3:9 Alex: I attended the concert at the Rialto Theater last Friday.",
        source_refs=("D3:9",),
        metadata={"item_type": "raw_turn"},
    )
    generic_event = RetrievedMemory(
        item_id="generic-event",
        rank=1,
        score=0.55,
        text="D3:8 Alex: I attended the concert after work and enjoyed it.",
        source_refs=("D3:8",),
        metadata={"item_type": "raw_turn"},
    )

    reranked, diagnostics = benchmark_rerank_memories(
        case,
        (generic_event, venue_evidence),
    )

    assert reranked[0].item_id == "event-venue"
    assert diagnostics["retrieval_intent"]["uses_ground_truth"] is False
    assert "location_support" in diagnostics["retrieval_intent"]["evidence_need"]
    venue_features = reranked[0].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    venue_signals = reranked[0].metadata["diagnostics"]["score_signals"]
    generic_features = next(
        memory for memory in reranked if memory.item_id == "generic-event"
    ).metadata["diagnostics"]["benchmark_candidate_features"]
    assert venue_features["relation_category_hits"] == ["location_transition"]
    assert generic_features["relation_category_hits"] == []
    assert venue_signals["benchmark_location_support_boost"] > 0


def test_non_place_work_question_does_not_get_location_support() -> None:
    case = _case("What field was Alex working in?")

    intent = query_retrieval_intent(case)

    assert "location_transition" not in intent.to_query_profile()["relation_categories"]
    assert "location_support" not in intent.evidence_need


def test_roadtrip_inference_query_is_not_location_support() -> None:
    case = _case("Would Melanie go on another roadtrip soon?")

    intent = query_retrieval_intent(case)
    queries, diagnostics = decomposed_search_queries(case)

    assert "location_support" not in intent.evidence_need
    assert "location_transition" not in diagnostics["query_profile"][
        "relation_categories"
    ]
    assert diagnostics["query_plan"]["selected_roles"] == [
        "original_question",
        "activity_support",
        "relative_temporal_support",
    ]
    assert queries[1] == "melanie roadtrip trip road weekend past soon"


def test_future_home_move_goal_query_is_not_location_support() -> None:
    case = _case("Would Caroline want to move back to her home country soon?")

    intent = query_retrieval_intent(case)
    queries, diagnostics = decomposed_search_queries(case)

    assert "location_support" not in intent.evidence_need
    assert "location_transition" not in diagnostics["query_profile"][
        "relation_categories"
    ]
    assert "current_goal" in diagnostics["query_profile"]["relation_categories"]
    assert diagnostics["query_plan"]["selected_roles"] == [
        "original_question",
        "current_goal_support",
        "relative_temporal_support",
    ]
    assert queries[1] == "caroline want move hop hope plan goal"


def _case(question: str) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-location:qa:1",
        question=question,
        expected_terms=("Canada",),
        memory_scope_external_ref="locomo-conv-location",
        thread_external_ref="locomo-conv-location",
        metadata={"category": 4},
    )
