from __future__ import annotations

from infinity_context_server.memory_comparison_evidence import evidence_bundle
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_rerank import (
    benchmark_rerank_memories,
    decomposed_search_queries,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase


def test_list_question_decomposition_adds_list_support_query() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="list-names-support",
        question="What are the names of Mia's dogs?",
        expected_terms=("Max",),
        metadata={"category": 4},
    )

    queries, diagnostics = decomposed_search_queries(case)

    assert "list_support" in diagnostics["query_profile"]["evidence_need"]
    assert "list_support" in diagnostics["query_profile"]["bundle_evidence_roles"]
    assert "list_support" in diagnostics["query_plan"]["selected_roles"]
    assert any({"dogs", "names", "list", "items"} <= set(query.split()) for query in queries)


def test_list_rerank_prefers_multi_item_evidence_over_single_mention() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="list-names-rerank",
        question="What are the names of Mia's dogs?",
        expected_terms=("Max",),
        metadata={"category": 4},
    )
    single_mention = RetrievedMemory(
        item_id="single-dog",
        rank=1,
        score=0.55,
        text="D2:3 Mia: I took Max to the dog park after work.",
        source_refs=("D2:3",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"benchmark_query_roles": ["original_question"]},
        },
    )
    list_evidence = RetrievedMemory(
        item_id="dog-list",
        rank=2,
        score=0.5,
        text="D2:4 Mia: My dogs are Max, Luna, and Pip.",
        source_refs=("D2:4",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"benchmark_query_roles": ["list_support"]},
        },
    )

    reranked, diagnostics = benchmark_rerank_memories(case, (single_mention, list_evidence))
    by_id = {memory.item_id: memory for memory in reranked}

    assert reranked[0].item_id == "dog-list"
    assert diagnostics["retrieval_intent"]["uses_ground_truth"] is False
    score_signals = by_id["dog-list"].metadata["diagnostics"]["score_signals"]
    assert score_signals["benchmark_list_answer_shape_boost"] > 0
    assert score_signals["benchmark_list_item_count"] == 3
    candidate_features = by_id["dog-list"].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    assert candidate_features["list_item_count"] == 3


def test_count_rerank_prefers_explicit_count_or_multi_item_evidence() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="count-dogs-rerank",
        question="How many dogs does Mia have?",
        expected_terms=("three",),
        metadata={"category": 4},
    )
    single_mention = RetrievedMemory(
        item_id="single-dog",
        rank=1,
        score=0.55,
        text="D2:3 Mia: Max loves the dog park.",
        source_refs=("D2:3",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"benchmark_query_roles": ["original_question"]},
        },
    )
    count_evidence = RetrievedMemory(
        item_id="dog-count",
        rank=2,
        score=0.5,
        text="D2:4 Mia: I have three dogs: Max, Luna, and Pip.",
        source_refs=("D2:4",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"benchmark_query_roles": ["count_support"]},
        },
    )

    reranked, _diagnostics = benchmark_rerank_memories(case, (single_mention, count_evidence))
    by_id = {memory.item_id: memory for memory in reranked}

    assert reranked[0].item_id == "dog-count"
    score_signals = by_id["dog-count"].metadata["diagnostics"]["score_signals"]
    assert score_signals["benchmark_count_answer_shape_boost"] > 0
    assert score_signals["benchmark_exact_count_evidence"] is True


def test_list_evidence_satisfies_required_bundle_role() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="list-names-bundle",
        question="What are the names of Mia's dogs?",
        expected_terms=("Max",),
        metadata={"category": 4},
    )

    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                item_id="dog-list",
                rank=1,
                score=0.6,
                text="D2:4 Mia: My dogs are Max, Luna, and Pip.",
                source_refs=("D2:4",),
                metadata={
                    "item_type": "raw_turn",
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.9,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "entity_hits": ["mia"],
                            "speaker_hits": ["mia"],
                            "query_has_entities": True,
                            "source_type": "raw_turn",
                            "list_item_count": 3,
                        }
                    },
                },
            ),
        ),
    )

    assert bundle["required_roles"] == ["primary", "list_support"]
    assert bundle["satisfied_required_roles"] == ["primary", "list_support"]
    assert bundle["bundle_planner"]["role_counts"] == {"primary": 1}
    assert bundle["items"][0]["list_item_count"] == 3


def test_count_list_query_roles_without_cardinality_do_not_complete_roles() -> None:
    cases = (
        (
            PublicBenchmarkCase(
                benchmark="locomo",
                case_id="count-role-needs-grounding",
                question="How many dogs does Mia have?",
                expected_terms=("three",),
                metadata={"category": 4},
            ),
            "count_support",
            "count_support",
        ),
        (
            PublicBenchmarkCase(
                benchmark="locomo",
                case_id="list-role-needs-grounding",
                question="What are the names of Mia's dogs?",
                expected_terms=("Max",),
                metadata={"category": 4},
            ),
            "list_support",
            "list_support",
        ),
    )

    for case, query_role, required_role in cases:
        generic_role_memory = RetrievedMemory(
            item_id=f"generic-{query_role}",
            rank=1,
            score=0.55,
            text="D2:3 Mia: I took Max to the dog park after work.",
            source_refs=("D2:3",),
            metadata={
                "item_type": "raw_turn",
                "diagnostics": {"benchmark_query_roles": [query_role]},
            },
        )

        reranked, _diagnostics = benchmark_rerank_memories(
            case,
            (generic_role_memory,),
        )
        reranked_memory = reranked[0]
        score_signals = reranked_memory.metadata["diagnostics"]["score_signals"]
        candidate_features = reranked_memory.metadata["diagnostics"][
            "benchmark_candidate_features"
        ]
        bundle = evidence_bundle(case, (reranked_memory,))

        assert candidate_features["query_roles"] == [query_role]
        assert candidate_features["exact_count_evidence"] is False
        assert candidate_features["list_item_count"] == 0
        assert score_signals["benchmark_count_answer_shape_boost"] == 0
        assert score_signals["benchmark_list_answer_shape_boost"] == 0
        assert score_signals["benchmark_count_list_query_role_boost"] == 0
        assert required_role not in bundle["satisfied_required_roles"]
        assert required_role in bundle["missing_required_roles"]
        assert bundle["bundle_complete"] is False
