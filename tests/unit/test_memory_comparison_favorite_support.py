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
