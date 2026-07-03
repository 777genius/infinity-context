from __future__ import annotations

from infinity_context_server.memory_comparison_rerank import decomposed_search_queries
from infinity_context_server.memory_comparison_rerank_text import is_preference_query
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase


def test_reason_question_gets_causal_support_without_why_marker() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="reason-causal-support",
        question="What was Alex's reason for leaving?",
        expected_terms=("family",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]
    query_plan = metadata["query_plan"]

    assert profile["relation_terms"] == ("reason",)
    assert profile["relation_categories"] == ("causal",)
    assert profile["evidence_need"] == ("causal_support",)
    assert profile["multi_hop_markers"] == ()
    assert "causal_support" in query_plan["selected_roles"]
    assert "multi_hop_bridge" in query_plan["selected_roles"]
    assert any("alex reason because cause caus decision explain" in q for q in queries)


def test_motivation_noun_gets_causal_support_terms() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="motivation-noun-causal-support",
        question="What is Alex's motivation for leaving?",
        expected_terms=("family",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("motivation",)
    assert profile["relation_categories"] == ("causal",)
    assert profile["relation_category_terms"]["causal"] == (
        "motivation",
        "motivat",
        "reason",
        "because",
        "cause",
    )
    assert profile["evidence_need"] == ("causal_support",)
    assert any("alex motivation motivat reason because cause" in q for q in queries)


def test_motivation_artifact_lookup_does_not_get_causal_support() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="motivation-artifact-lookup",
        question="What is displayed on Alex's cork board for motivation and creativity?",
        expected_terms=("quote",),
        metadata={"category": 4},
    )

    _, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("motivation",)
    assert profile["relation_categories"] == ()
    assert profile["evidence_need"] == ("single_fact",)
    assert "causal_support" not in metadata["query_plan"]["selected_roles"]


def test_health_motivation_question_keeps_causal_support_role() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="health-motivation-causal-support",
        question="What health issue did Alex face that motivated him to change his lifestyle?",
        expected_terms=("health",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("health", "motivat")
    assert profile["relation_categories"] == ("causal", "health_profile")
    assert profile["evidence_need"] == ("causal_support", "health_profile")
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex health motivat motivation reason because cause" in q for q in queries)


def test_what_made_question_gets_causal_support_without_action_drift() -> None:
    causal_case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="what-made-causal-support",
        question="What made Alex leave?",
        expected_terms=("family",),
        metadata={"category": 4},
    )
    action_case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="what-did-make-action-support",
        question="What did Alex make?",
        expected_terms=("painting",),
        metadata={"category": 4},
    )

    causal_queries, causal_metadata = decomposed_search_queries(causal_case)
    _, action_metadata = decomposed_search_queries(action_case)

    assert causal_metadata["query_profile"]["relation_terms"] == ("cause",)
    assert causal_metadata["query_profile"]["relation_categories"] == ("causal",)
    assert causal_metadata["query_profile"]["evidence_need"] == ("causal_support",)
    assert "causal_support" in causal_metadata["query_plan"]["selected_roles"]
    assert any(
        "alex cause caus because reason prompt inspiring made leave" in q
        for q in causal_queries
    )
    assert "cause" not in action_metadata["query_profile"]["relation_terms"]
    assert "causal_support" not in action_metadata["query_profile"]["evidence_need"]


def test_what_made_preference_question_gets_preference_and_causal_support() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="what-made-preference-reason-support",
        question="What made Alex prefer tea over coffee?",
        expected_terms=("calmer",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("prefer", "cause")
    assert profile["relation_categories"] == ("preference", "causal")
    assert profile["evidence_need"] == ("preference", "causal_support")
    assert "preference_support" in profile["bundle_evidence_roles"]
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any(
        "alex prefer cause reason because caus" in query
        for query in queries
    )


def test_preferring_reason_question_keeps_preference_support() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="preferring-reason-support",
        question="What reason did Alex give for preferring tea over coffee?",
        expected_terms=("calmer",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert "prefer" in profile["relation_terms"]
    assert "preference" in profile["relation_categories"]
    assert "causal" in profile["relation_categories"]
    assert "preference" in profile["evidence_need"]
    assert "causal_support" in profile["evidence_need"]
    assert "preference_support" in profile["bundle_evidence_roles"]
    assert any(
        "alex reason give prefer motivation because cause" in query
        for query in queries
    )


def test_prefer_relation_counts_as_preference_query() -> None:
    assert is_preference_query({"relation_terms": ("prefer",)})
    assert is_preference_query({"relation_terms": ("preference",)})
