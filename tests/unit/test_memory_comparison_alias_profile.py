from infinity_context_server import memory_comparison_rerank as rerank_module
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase


def test_query_decomposition_expands_called_and_who_goes_by_alias_questions() -> None:
    called_case = _case(
        case_id="alias-profile-called",
        question="What is Alex called?",
        expected_terms=("Ace",),
        answer="Ace",
    )
    who_goes_by_case = _case(
        case_id="alias-profile-who-goes-by",
        question="Who goes by Sunny?",
        expected_terms=("Maria",),
        answer="Maria",
    )

    called_queries, called_metadata = rerank_module.decomposed_search_queries(
        called_case,
    )
    who_queries, who_metadata = rerank_module.decomposed_search_queries(
        who_goes_by_case,
    )

    assert called_metadata["query_profile"]["evidence_need"] == ("alias_profile",)
    assert called_metadata["query_profile"]["relation_categories"] == (
        "alias_profile",
    )
    assert called_queries[2] == "alex call nickname name go by"

    assert who_metadata["query_profile"]["evidence_need"] == ("alias_profile",)
    assert who_metadata["query_profile"]["relation_categories"] == ("alias_profile",)
    assert who_queries[2] == "sunny nickname call name go by goes"


def test_benchmark_rerank_uses_full_name_speaker_for_alias_profile_evidence() -> None:
    case = _case(
        case_id="alias-profile-full-name-rerank",
        question="What is Melanie Chen's nickname?",
        expected_terms=("Mel",),
        answer="Mel",
    )
    same_given_name_distractor = RetrievedMemory(
        item_id="melanie-smith-alias",
        rank=1,
        score=0.2,
        text=(
            "session_1 turn D1:1 date: 10:00 am "
            "D1:1 Melanie Smith: My nickname is Spark."
        ),
        source_refs=("D1:1",),
    )
    exact_person_alias = RetrievedMemory(
        item_id="melanie-chen-alias",
        rank=2,
        score=0.0,
        text=(
            "session_1 turn D1:2 date: 10:01 am "
            "D1:2 Melanie Chen: My nickname is Mel."
        ),
        source_refs=("D1:2",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (same_given_name_distractor, exact_person_alias),
    )

    assert metadata["query_profile"]["evidence_need"] == ("alias_profile",)
    assert [memory.item_id for memory in reranked] == [
        "melanie-chen-alias",
        "melanie-smith-alias",
    ]
    diagnostics_by_id = {
        memory.item_id: memory.metadata["diagnostics"] for memory in reranked
    }
    exact_features = diagnostics_by_id["melanie-chen-alias"][
        "benchmark_candidate_features"
    ]
    distractor_features = diagnostics_by_id["melanie-smith-alias"][
        "benchmark_candidate_features"
    ]

    assert exact_features["relation_category_hits"] == ["alias_profile"]
    assert exact_features["speaker_hits"] == ["melanie chen"]
    assert distractor_features["relation_category_hits"] == []
    assert distractor_features["speaker_hits"] == []
    assert (
        diagnostics_by_id["melanie-smith-alias"]["score_signals"][
            "benchmark_typed_relation_support_boost"
        ]
        == 0
    )


def test_benchmark_rerank_boosts_called_known_as_alias_evidence() -> None:
    case = _case(
        case_id="alias-profile-known-as-rerank",
        question="What is Alex called?",
        expected_terms=("Ace",),
        answer="Ace",
    )
    topical_call = RetrievedMemory(
        item_id="topical-call",
        rank=1,
        score=0.2,
        text=(
            "session_1 turn D1:1 date: 10:00 am "
            "D1:1 Alex called Maria about the invoice."
        ),
        source_refs=("D1:1",),
    )
    alias_profile = RetrievedMemory(
        item_id="alias-profile",
        rank=2,
        score=0.0,
        text=(
            "session_1 turn D1:2 date: 10:01 am "
            "D1:2 Alex: I am known as Ace."
        ),
        source_refs=("D1:2",),
    )

    reranked, metadata = rerank_module.benchmark_rerank_memories(
        case,
        (topical_call, alias_profile),
    )

    assert metadata["query_profile"]["evidence_need"] == ("alias_profile",)
    assert [memory.item_id for memory in reranked] == ["alias-profile", "topical-call"]
    diagnostics_by_id = {
        memory.item_id: memory.metadata["diagnostics"] for memory in reranked
    }
    assert diagnostics_by_id["alias-profile"]["benchmark_candidate_features"][
        "relation_category_hits"
    ] == ["alias_profile"]
    assert diagnostics_by_id["topical-call"]["benchmark_candidate_features"][
        "relation_category_hits"
    ] == []


def _case(
    *,
    case_id: str,
    question: str,
    expected_terms: tuple[str, ...],
    answer: str,
) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="unit",
        case_id=case_id,
        question=question,
        expected_terms=expected_terms,
        metadata={"answer": answer, "category": 4},
    )
