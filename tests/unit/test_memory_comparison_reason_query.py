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


def test_explanation_question_gets_causal_support_terms() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="explanation-causal-support",
        question="What explanation did Alex give for leaving?",
        expected_terms=("family",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert "reason" in profile["relation_terms"]
    assert "causal" in profile["relation_categories"]
    assert "causal_support" in profile["evidence_need"]
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex give reason motivation because cause" in query for query in queries)


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
        "alex cause caus because reason prompt inspiring made leave" in q for q in causal_queries
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
    assert any("alex prefer cause reason because caus" in query for query in queries)


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
    assert "preference_support" in metadata["query_plan"]["selected_roles"]
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert "preference_support" in metadata["query_plan"]["recommended_role_families"]
    assert metadata["query_plan"]["missing_recommended_role_families"] == []
    assert any("alex reason give prefer motivation because cause" in query for query in queries)


def test_prefer_relation_counts_as_preference_query() -> None:
    assert is_preference_query({"relation_terms": ("prefer",)})
    assert is_preference_query({"relation_terms": ("preference",)})


def test_reason_activity_question_keeps_causal_support_role() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="reason-activity-causal-support",
        question="What is Alex's reason for getting into running?",
        expected_terms=("fitness",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("reason", "get", "run")
    assert profile["relation_categories"] == ("activity", "causal")
    assert profile["evidence_need"] == ("causal_support", "activity_support")
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex reason get run because cause caus" in query for query in queries)


def test_why_marker_relation_query_keeps_generic_causal_terms() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="why-move-causal-support",
        question="Why did Alex move?",
        expected_terms=("job",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("move",)
    assert profile["relation_categories"] == ("causal",)
    assert profile["evidence_need"] == ("multi_hop", "causal_support")
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex move reason because cause" in query for query in queries)


def test_because_question_keeps_causal_support_ahead_of_vehicle_profile() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="because-vehicle-causal-support",
        question="What happened because Alex's car broke down?",
        expected_terms=("repair",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("because", "cause", "vehicle")
    assert profile["relation_categories"] == ("causal", "vehicle_profile")
    assert profile["evidence_need"] == ("causal_support", "vehicle_profile")
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex because cause vehicle reason caus explain" in query for query in queries)


def test_motivated_question_gets_causal_support_without_how_marker() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="motivation-causal-support",
        question="What motivated Alex to leave?",
        expected_terms=("family",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]
    query_plan = metadata["query_plan"]

    assert profile["relation_terms"] == ("motivat",)
    assert profile["relation_categories"] == ("causal",)
    assert profile["evidence_need"] == ("causal_support",)
    assert profile["multi_hop_markers"] == ()
    assert "causal_support" in query_plan["selected_roles"]
    assert "multi_hop_bridge" in query_plan["selected_roles"]
    assert any("alex motivat motivation reason because cause" in query for query in queries)


def test_boost_motivation_question_keeps_causal_support() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="boost-motivation-causal-support",
        question="What tools does Alex use to boost his motivation for music?",
        expected_terms=("whiteboard",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("motivation", "music")
    assert "causal" in profile["relation_categories"]
    assert "causal_support" in profile["evidence_need"]
    assert any("alex motivation music motivat reason because cause" in query for query in queries)


def test_song_motivation_question_keeps_causal_support_role() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="song-motivation-causal-support",
        question="Which song motivates Alex to be courageous?",
        expected_terms=("song",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("song", "motivate")
    assert profile["relation_categories"] == ("activity", "causal")
    assert profile["evidence_need"] == ("causal_support", "activity_support")
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex song motivate motivat motivation reason because" in query for query in queries)


def test_what_caused_frustration_question_keeps_causal_support_role() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="caused-frustration-causal-support",
        question="What caused Alex's frustration about the car?",
        expected_terms=("repair",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("caus", "cause", "feel", "vehicle")
    assert profile["relation_categories"] == (
        "causal",
        "emotion_response",
        "vehicle_profile",
    )
    assert profile["evidence_need"] == (
        "causal_support",
        "emotion_response",
        "vehicle_profile",
    )
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex caus cause feel vehicle frustration reason" in query for query in queries)


def test_what_made_negative_emotion_question_preserves_emotion_cue() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="what-made-sad-causal-support",
        question="What made Alex sad?",
        expected_terms=("family",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("cause", "feel")
    assert profile["relation_categories"] == ("causal", "emotion_response")
    assert profile["evidence_need"] == ("causal_support", "emotion_response")
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex cause feel sad reason because caus" in query for query in queries)


def test_what_prompted_question_gets_causal_support_terms() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="what-prompted-causal-support",
        question="What prompted Alex to leave?",
        expected_terms=("family",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("prompt", "cause")
    assert profile["relation_categories"] == ("causal",)
    assert profile["evidence_need"] == ("causal_support",)
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex prompt cause reason because reflect caus" in query for query in queries)


def test_prompted_reflection_question_preserves_causal_prompt_cue() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="prompted-reflection-causal-support",
        question=(
            "What did Alex find in old notebooks last week that prompted "
            "him to reflect on his progress as a writer?"
        ),
        expected_terms=("notebooks",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("prompt",)
    assert profile["relation_categories"] == ("causal", "temporal")
    assert profile["evidence_need"] == ("temporal_support", "causal_support")
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert "relative_temporal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex prompt reason because cause week reflect" in query for query in queries)


def test_prompt_lookup_question_does_not_get_causal_support() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="prompt-lookup-not-causal",
        question="What prompt did Alex use?",
        expected_terms=("template",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("prompt",)
    assert profile["relation_categories"] == ()
    assert profile["evidence_need"] == ("single_fact",)
    assert "causal_support" not in metadata["query_plan"]["selected_roles"]
    assert not any("because" in query or "cause" in query for query in queries)


def test_what_led_to_leaving_question_gets_causal_support_terms() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="what-led-to-leaving-causal-support",
        question="What led to Alex leaving?",
        expected_terms=("family",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("cause",)
    assert profile["relation_categories"] == ("causal",)
    assert profile["evidence_need"] == ("causal_support",)
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex cause reason because caus prompt inspiring" in query for query in queries)


def test_what_inspired_question_gets_causal_support_terms() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="what-inspired-causal-support",
        question="What inspired Alex to leave?",
        expected_terms=("family",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("inspir", "cause")
    assert profile["relation_categories"] == ("causal",)
    assert profile["evidence_need"] == ("causal_support",)
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex inspiring cause motivation reason because caus" in query for query in queries)


def test_inspired_by_question_gets_causal_support_terms() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="inspired-by-causal-support",
        question="What is Alex inspired by?",
        expected_terms=("family",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("inspir",)
    assert profile["relation_categories"] == ("causal",)
    assert profile["evidence_need"] == ("causal_support",)
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex inspiring motivation reason because cause" in query for query in queries)


def test_who_inspired_question_gets_causal_support_terms() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="who-inspired-causal-support",
        question="Who inspired Alex to start volunteering?",
        expected_terms=("family",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("inspir",)
    assert profile["relation_categories"] == ("causal",)
    assert profile["evidence_need"] == ("causal_support",)
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert "multi_hop_bridge" in metadata["query_plan"]["selected_roles"]
    assert any(
        "alex inspiring motivation reason because cause start volunteer" in query
        for query in queries
    )


def test_what_made_emotion_question_gets_causal_emotion_terms() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="what-made-emotion-causal-support",
        question="What made Alex happy?",
        expected_terms=("family",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("cause", "feel")
    assert profile["relation_categories"] == ("causal", "emotion_response")
    assert profile["evidence_need"] == ("causal_support", "emotion_response")
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex cause feel happy reason because caus" in query for query in queries)


def test_inspired_emotion_activity_question_keeps_causal_support_role() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="inspired-emotion-activity-causal-support",
        question=(
            "What book did Alex recently finish rereading that left him "
            "feeling inspired and hopeful about following dreams?"
        ),
        expected_terms=("book",),
        metadata={"category": 4},
    )

    queries, metadata = decomposed_search_queries(case)
    profile = metadata["query_profile"]

    assert profile["relation_terms"] == ("book", "feel", "inspir")
    assert profile["relation_categories"] == (
        "activity",
        "causal",
        "emotion_response",
        "temporal",
    )
    assert "causal_support" in profile["evidence_need"]
    assert "causal_support" in metadata["query_plan"]["selected_roles"]
    assert any("alex book feel inspiring felt reaction response" in query for query in queries)
