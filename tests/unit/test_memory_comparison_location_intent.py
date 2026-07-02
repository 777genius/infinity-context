from __future__ import annotations

from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_rerank import (
    benchmark_rerank_memories,
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
