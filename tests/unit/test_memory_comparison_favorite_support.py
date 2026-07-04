from __future__ import annotations

import infinity_context_server.memory_comparison_rerank as rerank_module
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    PublicBenchmarkCase,
)


def test_query_decomposition_marks_favorite_as_typed_support_role() -> None:
    case = _case(
        case_id="favorite-color-query-plan",
        question="What is Alex's favorite color?",
        expected_terms=("green",),
        answer="green",
    )

    queries, metadata = rerank_module.decomposed_search_queries(case)
    query_profile = metadata["query_profile"]

    assert queries[2] == "alex favorite color favourite prefer like love"
    assert query_profile["relation_categories"] == (
        "favorite_preference",
        "preference",
    )
    assert query_profile["evidence_need"] == (
        "favorite_preference",
        "preference",
    )
    assert "favorite_support" in query_profile["bundle_evidence_roles"]
    assert metadata["query_plan"]["selected_roles"][2] == "favorite_support"


def test_query_decomposition_keeps_like_domain_in_preference_support() -> None:
    case = _case(
        case_id="like-animal-query-plan",
        question="What animal does Melanie like?",
        expected_terms=("cats",),
        answer="cats",
    )

    queries, metadata = rerank_module.decomposed_search_queries(case)
    query_profile = metadata["query_profile"]

    assert queries[2] == "melanie like animal love"
    assert query_profile["relation_categories"] == ("preference",)
    assert query_profile["evidence_need"] == ("preference",)
    assert query_profile["bundle_evidence_roles"] == (
        "primary",
        "preference_support",
    )
    assert metadata["query_plan"]["selected_roles"][2] == "preference_support"


def test_query_decomposition_marks_avoid_as_negative_preference_support() -> None:
    case = _case(
        case_id="avoid-activity-query-plan",
        question="What activity does Alex avoid?",
        expected_terms=("running",),
        answer="running",
    )

    queries, metadata = rerank_module.decomposed_search_queries(case)
    query_profile = metadata["query_profile"]

    assert queries[2] == "alex avoid activity dislike dislik hate hat prefer"
    assert query_profile["relation_categories"] == (
        "activity",
        "preference",
    )
    assert query_profile["evidence_need"] == ("preference",)
    assert "preference_support" in query_profile["bundle_evidence_roles"]
    assert metadata["query_plan"]["selected_roles"][2] == "preference_support"


def test_favorite_support_distinguishes_explicit_favorite_from_generic_preference() -> None:
    case = _case(
        case_id="favorite-color-rerank-typed-support",
        question="What is Alex's favorite color?",
        expected_terms=("green",),
        answer="green",
    )
    generic_preference = RetrievedMemory(
        item_id="generic-like",
        rank=1,
        score=0.2,
        text=(
            "session_1 turn D1:1 date: 10:00 am "
            "D1:1 Alex: I like the green color in that mural."
        ),
        source_refs=("D1:1",),
    )
    explicit_favorite = RetrievedMemory(
        item_id="explicit-favorite",
        rank=2,
        score=0.0,
        text=(
            "session_1 turn D1:2 date: 10:05 am "
            "D1:2 Alex: My favorite color is green."
        ),
        source_refs=("D1:2",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (generic_preference, explicit_favorite),
    )

    assert metadata["query_profile"]["bundle_evidence_roles"] == (
        "primary",
        "preference_support",
        "favorite_support",
    )
    assert reranked[0].item_id == "explicit-favorite"

    diagnostics_by_id = {
        memory.item_id: memory.metadata["diagnostics"] for memory in reranked
    }
    explicit_features = diagnostics_by_id["explicit-favorite"][
        "benchmark_candidate_features"
    ]
    generic_features = diagnostics_by_id["generic-like"]["benchmark_candidate_features"]

    assert explicit_features["relation_category_hits"] == [
        "favorite_preference",
        "preference",
    ]
    assert generic_features["relation_category_hits"] == ["preference"]
    assert "favorite_preference" not in generic_features["relation_category_hits"]
    assert diagnostics_by_id["explicit-favorite"]["score_signals"][
        "benchmark_typed_relation_support_roles"
    ] == ["favorite_support"]


def test_negative_preference_support_prefers_avoid_evidence() -> None:
    case = _case(
        case_id="avoid-activity-rerank-preference-support",
        question="What activity does Alex avoid?",
        expected_terms=("running",),
        answer="running",
    )
    activity_context = RetrievedMemory(
        item_id="activity-context",
        rank=1,
        score=0.0,
        text=(
            "session_1 turn D1:1 date: 10:00 am "
            "D1:1 Alex: Running is an activity at the park."
        ),
        source_refs=("D1:1",),
    )
    avoid_preference = RetrievedMemory(
        item_id="avoid-preference",
        rank=2,
        score=0.0,
        text=(
            "session_1 turn D1:2 date: 10:05 am "
            "D1:2 Alex: I avoid running because it hurts my knee."
        ),
        source_refs=("D1:2",),
    )

    reranked, _metadata = rerank_module.benchmark_rerank_memories(
        case,
        (activity_context, avoid_preference),
    )

    assert reranked[0].item_id == "avoid-preference"
    diagnostics = reranked[0].metadata["diagnostics"]
    features = diagnostics["benchmark_candidate_features"]
    signals = diagnostics["score_signals"]
    assert features["has_preference_evidence"] is True
    assert features["relation_category_hits"] == ["activity", "preference"]
    assert signals["benchmark_preference_evidence_boost"] == 0.12
    assert signals["benchmark_preference_evidence_grounded"] is True


def test_comparative_option_preference_scores_later_option_speaker() -> None:
    case = _case(
        case_id="comparative-option-preference-speaker",
        question="Who likes tea more, Alice or Bob?",
        expected_terms=("bob",),
        answer="Bob",
    )
    first_option_preference = RetrievedMemory(
        item_id="alice-like",
        rank=1,
        score=0.0,
        text=(
            "session_1 turn D1:1 date: 10:00 am "
            "D1:1 Alice: I like tea."
        ),
        source_refs=("D1:1",),
    )
    later_option_stronger_preference = RetrievedMemory(
        item_id="bob-prefer",
        rank=2,
        score=0.0,
        text=(
            "session_1 turn D1:2 date: 10:05 am "
            "D1:2 Bob: I love tea and prefer tea over coffee."
        ),
        source_refs=("D1:2",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (first_option_preference, later_option_stronger_preference),
    )

    assert metadata["query_profile"]["comparative_option_preference_query"] is True
    assert reranked[0].item_id == "bob-prefer"

    diagnostics_by_id = {
        memory.item_id: memory.metadata["diagnostics"] for memory in reranked
    }
    bob_features = diagnostics_by_id["bob-prefer"]["benchmark_candidate_features"]
    bob_signals = diagnostics_by_id["bob-prefer"]["score_signals"]

    assert bob_features["speaker_hits"] == ["bob"]
    assert bob_signals["benchmark_speaker_boost"] == 0.08
    assert bob_signals["benchmark_focused_turn_boost"] == 0.08

    current_case = _case(
        case_id="current-comparative-option-preference",
        question="Who likes tea more now, Alice or Bob?",
        expected_terms=("bob",),
        answer="Bob",
    )
    _reranked, current_metadata = rerank_module.benchmark_rerank_memories(
        current_case,
        (),
    )

    assert (
        current_metadata["query_profile"]["comparative_option_preference_query"]
        is False
    )


def _case(
    *,
    case_id: str,
    question: str,
    expected_terms: tuple[str, ...],
    answer: str,
) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id=case_id,
        question=question,
        expected_terms=expected_terms,
        documents=(
            BenchmarkDocumentInput(
                title="Conversation",
                text=f"Alex said: {answer}",
                source_external_id="conv-1-doc",
            ),
        ),
        memory_scope_external_ref="locomo-conv-1",
        thread_external_ref="locomo-conv-1",
        metadata={"category": 4, "answer_preview": answer},
    )
