from __future__ import annotations

from infinity_context_server.memory_comparison_evidence import evidence_bundle
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_rerank import (
    benchmark_rerank_memories,
    decomposed_search_queries,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase


def test_value_answer_decomposition_adds_value_support_query() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="value-answer-shape",
        question="What was the deposit amount for Mia's ceramics class?",
        expected_terms=("$45",),
        metadata={"category": 4},
    )

    queries, diagnostics = decomposed_search_queries(case)

    assert "quantity_dollar" in diagnostics["query_profile"]["answer_unit_shapes"]
    assert "value_support" in diagnostics["query_profile"]["evidence_need"]
    assert "value_support" in diagnostics["query_profile"]["bundle_evidence_roles"]
    assert "value_support" in diagnostics["query_plan"]["selected_roles"]
    assert any(
        {"deposit", "amount", "cost", "price", "value", "dollar"} <= set(query.split())
        for query in queries
    )


def test_value_answer_rerank_beats_generic_same_topic_evidence() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="value-answer-rerank",
        question="What was the deposit amount for Mia's ceramics class?",
        expected_terms=("$45",),
        metadata={"category": 4},
    )
    generic = RetrievedMemory(
        item_id="generic-deposit",
        rank=1,
        score=0.55,
        text="D2:3 Mia paid the deposit for her ceramics class before registration closed.",
        source_refs=("D2:3",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"benchmark_query_roles": ["original_question"]},
        },
    )
    value_evidence = RetrievedMemory(
        item_id="deposit-amount",
        rank=2,
        score=0.5,
        text="D2:4 Mia: The ceramics class deposit was $45.",
        source_refs=("D2:4",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"benchmark_query_roles": ["value_support"]},
        },
    )

    reranked, diagnostics = benchmark_rerank_memories(case, (generic, value_evidence))
    by_id = {memory.item_id: memory for memory in reranked}

    assert reranked[0].item_id == "deposit-amount"
    assert diagnostics["retrieval_intent"]["uses_ground_truth"] is False
    assert (
        by_id["deposit-amount"].metadata["diagnostics"]["score_signals"][
            "benchmark_value_answer_shape_boost"
        ]
        > 0
    )
    candidate_features = by_id["deposit-amount"].metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    assert candidate_features["covered_answer_unit_shapes"] == ["quantity_dollar"]


def test_value_answer_evidence_satisfies_required_role() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="value-answer-bundle-role",
        question="What was the deposit amount for Mia's ceramics class?",
        expected_terms=("$45",),
        metadata={"category": 4},
    )
    bundle = evidence_bundle(
        case,
        (
            RetrievedMemory(
                item_id="generic-deposit",
                rank=1,
                score=0.55,
                text=(
                    "D2:3 Mia paid the deposit for her ceramics class before "
                    "registration closed."
                ),
                source_refs=("D2:3",),
                metadata={
                    "item_type": "raw_turn",
                    "diagnostics": {
                        "benchmark_candidate_features": {
                            "answerability_score": 0.85,
                            "source_locality_score": 1.0,
                            "direct_speaker_turn": True,
                            "entity_hits": ["mia"],
                            "speaker_hits": ["mia"],
                            "query_has_entities": True,
                            "source_type": "raw_turn",
                        }
                    },
                },
            ),
            RetrievedMemory(
                item_id="deposit-amount",
                rank=2,
                score=0.5,
                text="D2:4 Mia: The ceramics class deposit was $45.",
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
                            "covered_answer_unit_shapes": ["quantity_dollar"],
                            "source_type": "raw_turn",
                        }
                    },
                },
            ),
        ),
    )

    assert bundle["required_roles"] == ["primary", "value_support"]
    assert bundle["satisfied_required_roles"] == ["primary", "value_support"]
    assert bundle["missing_required_roles"] == []
    assert bundle["bundle_complete"] is True


def test_value_query_role_without_value_evidence_does_not_complete_role() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="value-answer-role-needs-grounding",
        question="What was the deposit amount for Mia's ceramics class?",
        expected_terms=("$45",),
        metadata={"category": 4},
    )
    generic_value_role = RetrievedMemory(
        item_id="generic-value-role",
        rank=1,
        score=0.55,
        text=(
            "D2:3 Mia: The ceramics class deposit amount came up before "
            "registration closed."
        ),
        source_refs=("D2:3",),
        metadata={
            "item_type": "raw_turn",
            "diagnostics": {"benchmark_query_roles": ["value_support"]},
        },
    )

    reranked, _diagnostics = benchmark_rerank_memories(case, (generic_value_role,))
    reranked_memory = reranked[0]
    score_signals = reranked_memory.metadata["diagnostics"]["score_signals"]
    candidate_features = reranked_memory.metadata["diagnostics"][
        "benchmark_candidate_features"
    ]
    bundle = evidence_bundle(case, (reranked_memory,))

    assert candidate_features["query_roles"] == ["value_support"]
    assert candidate_features["covered_answer_unit_shapes"] == []
    assert score_signals["benchmark_value_answer_shape_boost"] == 0
    assert score_signals["benchmark_value_query_role_boost"] == 0
    assert "value_support" not in bundle["satisfied_required_roles"]
    assert "value_support" in bundle["missing_required_roles"]
    assert bundle["bundle_complete"] is False
