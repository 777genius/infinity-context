from __future__ import annotations

import pytest
from infinity_context_server.memory_comparison_rerank_policy import (
    BenchmarkRerankFeatures,
    score_benchmark_rerank_candidate,
)


def test_rerank_policy_boosts_dense_focused_relation_evidence() -> None:
    score = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("relationship", "status"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("parent", "breakup", "family", "support"),
            relation_terms=("relationship", "status"),
            query_has_entities=True,
            high_signal_relation_hit_count=1,
            is_temporal_query=False,
            has_temporal_surface=False,
            has_sequence_surface=False,
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.08,
            has_multi_hop_markers=False,
            direct_speaker_turn=True,
            source_locality_score=1.0,
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert score.boost == 0.62
    assert signals["benchmark_focused_relation_density_boost"] == 0.06
    assert signals["benchmark_direct_speaker_relation_boost"] == 0.12
    assert policy["schema_version"] == "benchmark_rerank_policy.v2"
    assert policy["reason_codes_by_policy"]["FocusedTurnPolicy"] == [
        "focused_turn",
        "focused_relation_density",
        "direct_speaker_relation",
    ]


def test_rerank_policy_does_not_density_boost_broad_relation_summaries() -> None:
    score = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("relationship", "status"),
            entity_hits=("caroline",),
            speaker_hits=(),
            relation_hits=("parent", "breakup", "family", "support"),
            relation_terms=("relationship", "status"),
            query_has_entities=True,
            high_signal_relation_hit_count=1,
            is_temporal_query=False,
            has_temporal_surface=False,
            has_sequence_surface=False,
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.0,
            has_multi_hop_markers=False,
        )
    )

    signals = score.signals["score_signals"]
    assert signals["benchmark_focused_relation_density_boost"] == 0.0
    assert score.boost < 0.6


def test_rerank_policy_requires_grounded_direct_speaker_relation() -> None:
    score = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("relationship", "status"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("parent", "breakup", "family", "support"),
            relation_terms=("relationship", "status"),
            query_has_entities=True,
            high_signal_relation_hit_count=1,
            is_temporal_query=False,
            has_temporal_surface=False,
            has_sequence_surface=False,
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.08,
            has_multi_hop_markers=False,
            broad_summary=True,
            direct_speaker_turn=True,
            source_locality_score=0.35,
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]

    assert signals["benchmark_direct_speaker_relation_boost"] == 0.0
    assert signals["benchmark_direct_speaker_relation_evidence"] is False
    assert signals["benchmark_rich_direct_speaker_relation_evidence"] is False
    assert "direct_speaker_relation" not in policy["reason_codes_by_policy"][
        "FocusedTurnPolicy"
    ]


def test_rerank_policy_allows_unmeasured_direct_speaker_relation_locality() -> None:
    unmeasured = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("relationship", "status"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("parent", "breakup", "family", "support"),
            relation_terms=("relationship", "status"),
            high_signal_relation_hit_count=1,
            focused_turn_boost=0.08,
            direct_speaker_turn=True,
            source_locality_score=0.0,
        )
    )
    measured_weak = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("relationship", "status"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("parent", "breakup", "family", "support"),
            relation_terms=("relationship", "status"),
            high_signal_relation_hit_count=1,
            focused_turn_boost=0.08,
            direct_speaker_turn=True,
            source_locality_score=0.35,
        )
    )

    unmeasured_signals = unmeasured.signals["score_signals"]
    measured_signals = measured_weak.signals["score_signals"]
    unmeasured_policy = unmeasured.signals["policy_contributions"]

    assert unmeasured_signals["benchmark_direct_speaker_relation_boost"] == 0.12
    assert unmeasured_signals["benchmark_direct_speaker_relation_evidence"] is True
    assert "direct_speaker_relation" in unmeasured_policy["reason_codes_by_policy"][
        "FocusedTurnPolicy"
    ]
    assert measured_signals["benchmark_direct_speaker_relation_boost"] == 0.0
    assert measured_signals["benchmark_direct_speaker_relation_evidence"] is False


def test_rerank_policy_reports_relation_category_coverage_boost() -> None:
    score = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("relationship", "status"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("parent", "breakup", "family", "support"),
            relation_terms=("relationship", "status"),
            query_has_entities=True,
            high_signal_relation_hit_count=0,
            is_temporal_query=False,
            has_temporal_surface=False,
            has_sequence_surface=False,
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.0,
            has_multi_hop_markers=False,
            relation_categories=("status_profile",),
            relation_category_hits=("status_profile",),
            relation_category_coverage_ratio=1.0,
            direct_speaker_turn=True,
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_relation_category_coverage_boost"] == 0.055
    assert signals["benchmark_relation_category_hits"] == ["status_profile"]
    assert "relation_category_coverage" in policy["reason_codes_by_policy"][
        "RelationCoveragePolicy"
    ]


@pytest.mark.parametrize(
    ("category", "reason"),
    (
        ("status_profile", "missing_status_profile_evidence"),
        ("causal", "missing_causal_evidence"),
        ("contrast", "missing_contrast_evidence"),
        ("location_transition", "missing_location_transition_evidence"),
        ("preference", "missing_preference_evidence"),
    ),
)
def test_rerank_policy_caps_missing_typed_relation_evidence(
    category: str,
    reason: str,
) -> None:
    score = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("caroline", "relationship", "status"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("relationship", "status"),
            relation_terms=("relationship", "status"),
            query_has_entities=True,
            high_signal_relation_hit_count=0,
            is_temporal_query=False,
            has_temporal_surface=False,
            has_sequence_surface=False,
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.08,
            has_multi_hop_markers=False,
            relation_categories=(category,),
            relation_category_hits=(),
            relation_category_coverage_ratio=0.0,
            direct_speaker_turn=True,
            source_locality_score=1.0,
            answerability_score=0.5,
            answerability_reason_codes=(reason,),
        )
    )

    signals = score.signals["score_signals"]
    assert score.boost <= 0.4
    assert f"{reason}_cap" in signals["benchmark_provenance_safety_reason_codes"]


def test_rerank_policy_guards_writing_career_from_generic_density_boost() -> None:
    score = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("career",),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("counsel", "mental", "support", "similar", "issue"),
            relation_terms=("write", "career", "option"),
            query_has_entities=True,
            high_signal_relation_hit_count=1,
            is_temporal_query=False,
            has_temporal_surface=False,
            has_sequence_surface=False,
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.08,
            has_multi_hop_markers=False,
        )
    )

    signals = score.signals["score_signals"]
    assert signals["benchmark_focused_relation_density_boost"] == 0.0
    assert score.boost < 0.59


def test_rerank_policy_reports_contrast_penalty_for_stale_evidence() -> None:
    score = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("relationship",),
            entity_hits=("caroline",),
            speaker_hits=(),
            relation_hits=("parent", "breakup"),
            relation_terms=("relationship", "status"),
            query_has_entities=True,
            high_signal_relation_hit_count=0,
            is_temporal_query=False,
            has_temporal_surface=False,
            has_sequence_surface=False,
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.0,
            has_multi_hop_markers=False,
            conflict_or_stale=True,
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_contrast_penalty"] == -0.06
    assert "conflict_or_stale" in policy["reason_codes_by_policy"][
        "ContrastIntentPolicy"
    ]
    assert 0 < score.boost < 0.2


def test_rerank_policy_reports_bounded_answerability_boost() -> None:
    score = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("caroline", "breakup"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("parent", "breakup", "support"),
            relation_terms=("relationship", "status"),
            query_has_entities=True,
            high_signal_relation_hit_count=1,
            is_temporal_query=False,
            has_temporal_surface=False,
            has_sequence_surface=False,
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.0,
            has_multi_hop_markers=False,
            answerability_score=0.91,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_satisfied",
                "direct_provenance",
                "high_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_answerability_score"] == 0.91
    assert signals["benchmark_answerability_boost"] == 0.1
    assert "high_answerability" in policy["reason_codes_by_policy"][
        "AnswerabilityPolicy"
    ]


def test_rerank_policy_allows_answerability_for_grounded_typed_category() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("alex", "notebook", "class"),
            entity_hits=("alex",),
            speaker_hits=("alex",),
            relation_hits=(),
            relation_terms=("action",),
            relation_categories=("action_event",),
            relation_category_hits=("action_event",),
            relation_category_coverage_ratio=1.0,
            query_has_entities=True,
            evidence_need=("action_support",),
            query_roles=("action_support",),
            answerability_score=0.9,
            answerability_reason_codes=(
                "entity_satisfied",
                "intent_satisfied",
                "direct_provenance",
                "high_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_answerability_boost"] == 0.1
    assert signals["benchmark_answerability_boost_eligible"] is True
    assert "high_answerability" in policy["reason_codes_by_policy"][
        "AnswerabilityPolicy"
    ]


def test_rerank_policy_caps_missing_action_event_evidence() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "notebook"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("notebook", "desk", "planning", "class"),
            relation_terms=("brought", "notebook"),
            relation_categories=("action_event",),
            relation_category_hits=(),
            query_has_entities=True,
            evidence_need=("action_support",),
            query_roles=("action_support",),
            direct_speaker_turn=True,
            focused_turn_boost=0.12,
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
            answerability_score=0.74,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_partial",
                "direct_provenance",
                "intent_partial",
                "missing_action_event_evidence",
                "medium_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]
    assert signals["benchmark_answerability_boost_eligible"] is False
    assert score.boost == 0.4
    assert signals["benchmark_provenance_safety_reason_codes"] == [
        "missing_action_event_evidence_cap"
    ]


def test_rerank_policy_reports_contrast_and_currentness_support() -> None:
    score = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("caroline", "current", "plan"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("current", "plan", "counseling"),
            relation_terms=("current", "plan"),
            query_has_entities=True,
            high_signal_relation_hit_count=1,
            is_temporal_query=True,
            has_temporal_surface=True,
            has_sequence_surface=True,
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.0,
            has_multi_hop_markers=False,
            negation_surface=True,
            currentness_surface=True,
            stale_surface=True,
            contrast_surface=True,
            evidence_need=("inference_support", "temporal_sequence"),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_currentness_support_boost"] == 0.04
    assert signals["benchmark_contrast_support_boost"] == 0.045
    assert signals["benchmark_negation_surface"] is True
    assert "currentness_support" in policy["reason_codes_by_policy"][
        "TemporalPolicy"
    ]
    assert "contrast_support" in policy["reason_codes_by_policy"][
        "ContrastIntentPolicy"
    ]


def test_rerank_policy_prefers_typed_duration_temporal_evidence() -> None:
    duration = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("caroline", "known", "friend"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("known", "friend"),
            relation_terms=("known", "friend"),
            query_has_entities=True,
            high_signal_relation_hit_count=1,
            is_temporal_query=True,
            time_intent_kind="duration",
            has_temporal_surface=True,
            has_sequence_surface=False,
            has_duration_surface=True,
            query_roles=("duration_temporal_support",),
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.0,
            has_multi_hop_markers=False,
        )
    )
    generic_temporal = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("caroline", "known", "friend"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("known", "friend"),
            relation_terms=("known", "friend"),
            query_has_entities=True,
            high_signal_relation_hit_count=1,
            is_temporal_query=True,
            time_intent_kind="duration",
            has_temporal_surface=True,
            has_sequence_surface=False,
            has_relative_time_surface=True,
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.0,
            has_multi_hop_markers=False,
        )
    )

    duration_signals = duration.signals["score_signals"]
    generic_signals = generic_temporal.signals["score_signals"]
    duration_policy = duration.signals["policy_contributions"]
    generic_policy = generic_temporal.signals["policy_contributions"]

    assert duration_signals["benchmark_time_intent_kind"] == "duration"
    assert duration_signals["benchmark_temporal_text_boost"] == 0.085
    assert duration_signals["benchmark_temporal_role_support_boost"] == 0.055
    assert duration_signals["benchmark_temporal_query_roles"] == [
        "duration_temporal_support"
    ]
    assert duration_signals["benchmark_typed_temporal_reason"] == (
        "duration_temporal_evidence"
    )
    assert generic_signals["benchmark_temporal_text_boost"] == 0.025
    assert generic_signals["benchmark_temporal_role_support_boost"] == 0.0
    assert generic_signals["benchmark_typed_temporal_reason"] == (
        "duration_temporal_evidence_partial"
    )
    assert "duration_temporal_evidence" in duration_policy[
        "reason_codes_by_policy"
    ]["TemporalPolicy"]
    assert "temporal_query_role_support" in duration_policy[
        "reason_codes_by_policy"
    ]["TemporalPolicy"]
    assert "duration_temporal_evidence_partial" in generic_policy[
        "reason_codes_by_policy"
    ]["TemporalPolicy"]
    assert duration.boost > generic_temporal.boost


def test_rerank_policy_treats_explicit_date_as_relative_answer_evidence() -> None:
    explicit_date = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("morgan", "hike"),
            entity_hits=("morgan",),
            speaker_hits=("morgan",),
            relation_hits=("hike",),
            relation_terms=("hike", "friend"),
            is_temporal_query=True,
            time_intent_kind="relative_time",
            has_temporal_surface=True,
            has_explicit_time_content_surface=True,
            query_roles=("relative_temporal_support",),
            direct_speaker_turn=True,
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
        )
    )
    generic_temporal = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("morgan", "hike"),
            entity_hits=("morgan",),
            speaker_hits=("morgan",),
            relation_hits=("hike",),
            relation_terms=("hike", "friend"),
            is_temporal_query=True,
            time_intent_kind="relative_time",
            has_temporal_surface=True,
            query_roles=("relative_temporal_support",),
            direct_speaker_turn=True,
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
        )
    )

    explicit_signals = explicit_date.signals["score_signals"]
    generic_signals = generic_temporal.signals["score_signals"]
    explicit_policy = explicit_date.signals["policy_contributions"]

    assert explicit_signals["benchmark_temporal_text_boost"] == 0.08
    assert explicit_signals["benchmark_temporal_role_support_boost"] == 0.055
    assert explicit_signals["benchmark_typed_temporal_reason"] == (
        "relative_temporal_explicit_answer_evidence"
    )
    assert generic_signals["benchmark_temporal_text_boost"] == 0.0
    assert generic_signals["benchmark_temporal_role_support_boost"] == 0.0
    assert "relative_temporal_explicit_answer_evidence" in explicit_policy[
        "reason_codes_by_policy"
    ]["TemporalPolicy"]
    assert explicit_date.boost > generic_temporal.boost


def test_rerank_policy_rejects_stale_only_current_state_temporal_support() -> None:
    stale = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("alex", "currently", "plan"),
            entity_hits=("alex",),
            speaker_hits=("alex",),
            relation_hits=("plan", "move"),
            relation_terms=("current", "plan", "move"),
            high_signal_relation_hit_count=1,
            is_temporal_query=True,
            time_intent_kind="relative_time",
            temporal_query_terms=("currently",),
            current_state_query=True,
            has_relative_time_surface=True,
            stale_surface=True,
            query_roles=("relative_temporal_support", "current_goal_support"),
            evidence_need=("temporal_support", "current_goal"),
            direct_speaker_turn=True,
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
            answerability_score=0.9,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_satisfied",
                "direct_provenance",
                "high_answerability",
            ),
        )
    )
    current = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("alex", "currently", "plan"),
            entity_hits=("alex",),
            speaker_hits=("alex",),
            relation_hits=("plan", "move"),
            relation_terms=("current", "plan", "move"),
            high_signal_relation_hit_count=1,
            is_temporal_query=True,
            time_intent_kind="relative_time",
            temporal_query_terms=("currently",),
            current_state_query=True,
            currentness_surface=True,
            query_roles=("relative_temporal_support", "current_goal_support"),
            evidence_need=("temporal_support", "current_goal"),
            direct_speaker_turn=True,
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
            answerability_score=0.9,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_satisfied",
                "direct_provenance",
                "high_answerability",
            ),
        )
    )

    stale_signals = stale.signals["score_signals"]
    current_signals = current.signals["score_signals"]

    assert stale_signals["benchmark_current_state_query"] is True
    assert stale_signals["benchmark_stale_only_current_state_evidence"] is True
    assert stale_signals["benchmark_temporal_text_boost"] == 0.0
    assert stale_signals["benchmark_temporal_role_support_boost"] == 0.0
    assert stale_signals["benchmark_typed_temporal_reason"] == (
        "stale_only_current_state_evidence"
    )
    assert stale_signals["benchmark_effective_boost_cap"] == 0.28
    assert "stale_only_current_state_cap" in stale_signals[
        "benchmark_provenance_safety_reason_codes"
    ]
    assert current_signals["benchmark_stale_only_current_state_evidence"] is False
    assert current_signals["benchmark_currentness_support_boost"] == 0.04
    assert current.boost > stale.boost


def test_rerank_policy_caps_missing_typed_temporal_evidence() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "known", "friend"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("known", "friend", "school", "years"),
            relation_terms=("known", "friend", "school", "years"),
            high_signal_relation_hit_count=1,
            is_temporal_query=True,
            time_intent_kind="duration",
            has_temporal_surface=True,
            query_roles=("duration_temporal_support",),
            direct_speaker_turn=True,
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
            focused_turn_boost=0.08,
            answerability_score=0.54,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_satisfied",
                "direct_provenance",
                "missing_duration_temporal_evidence",
                "low_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]
    assert score.boost == 0.4
    assert signals["benchmark_answerability_boost"] == 0.0
    assert signals["benchmark_answerability_boost_eligible"] is False
    assert signals["benchmark_effective_boost_cap"] == 0.4
    assert "missing_duration_temporal_evidence_cap" in signals[
        "benchmark_provenance_safety_reason_codes"
    ]


def test_rerank_policy_accepts_typed_contrast_need() -> None:
    score = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=("caroline", "current"),
            entity_hits=("caroline",),
            speaker_hits=(),
            relation_hits=("current",),
            relation_terms=("current",),
            query_has_entities=True,
            high_signal_relation_hit_count=1,
            is_temporal_query=False,
            has_temporal_surface=False,
            has_sequence_surface=False,
            is_preference_query=False,
            has_preference_evidence=False,
            has_visual_terms=False,
            has_visual_evidence=False,
            focused_turn_boost=0.0,
            has_multi_hop_markers=False,
            negation_surface=False,
            currentness_surface=True,
            stale_surface=True,
            contrast_surface=True,
            evidence_need=("contrast",),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_contrast_support_boost"] == 0.045
    assert "contrast_support" in policy["reason_codes_by_policy"][
        "ContrastIntentPolicy"
    ]


def test_rerank_policy_accepts_typed_location_support_need() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "move", "from"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("move", "home", "country", "relocated"),
            relation_terms=("move",),
            relation_categories=("location_transition",),
            relation_category_hits=("location_transition",),
            relation_category_coverage_ratio=1.0,
            direct_speaker_turn=True,
            source_locality_score=1.0,
            evidence_need=("location_support",),
            query_roles=("location_support",),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_location_support_boost"] == 0.05
    assert signals["benchmark_location_query_role_boost"] == 0.035
    assert signals["benchmark_location_relation_category_hit"] is True
    assert "location_support" in policy["reason_codes_by_policy"][
        "LocationIntentPolicy"
    ]
    assert "location_query_role_support" in policy["reason_codes_by_policy"][
        "LocationIntentPolicy"
    ]


def test_rerank_policy_accepts_unmeasured_source_ref_location_support() -> None:
    unmeasured = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "move", "from"),
            entity_hits=("caroline",),
            relation_hits=("move", "home", "country", "relocated"),
            relation_terms=("move",),
            relation_categories=("location_transition",),
            relation_category_hits=("location_transition",),
            relation_category_coverage_ratio=1.0,
            source_locality_score=0.0,
            source_ref_count=1,
            turn_ref_count=1,
            evidence_need=("location_support",),
            query_roles=("location_support",),
        )
    )
    measured_weak = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "move", "from"),
            entity_hits=("caroline",),
            relation_hits=("move", "home", "country", "relocated"),
            relation_terms=("move",),
            relation_categories=("location_transition",),
            relation_category_hits=("location_transition",),
            relation_category_coverage_ratio=1.0,
            source_locality_score=0.35,
            source_ref_count=1,
            turn_ref_count=1,
            evidence_need=("location_support",),
            query_roles=("location_support",),
        )
    )

    unmeasured_signals = unmeasured.signals["score_signals"]
    measured_signals = measured_weak.signals["score_signals"]

    assert unmeasured_signals["benchmark_location_support_boost"] == 0.05
    assert unmeasured_signals["benchmark_location_query_role_boost"] == 0.035
    assert unmeasured_signals["benchmark_location_precise_provenance"] is True
    assert measured_signals["benchmark_location_support_boost"] == 0.0
    assert measured_signals["benchmark_location_precise_provenance"] is False


def test_rerank_policy_requires_grounded_preference_evidence() -> None:
    grounded = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("melanie", "like", "camping"),
            entity_hits=("melanie",),
            speaker_hits=("melanie",),
            relation_hits=("like", "camping"),
            relation_terms=("like", "camping"),
            is_preference_query=True,
            has_preference_evidence=True,
            direct_speaker_turn=True,
            source_locality_score=1.0,
        )
    )
    broad = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("melanie", "like", "camping"),
            entity_hits=("melanie",),
            relation_hits=("like", "camping"),
            relation_terms=("like", "camping"),
            is_preference_query=True,
            has_preference_evidence=True,
            broad_summary=True,
            source_locality_score=0.35,
            source_ref_count=8,
            turn_ref_count=12,
        )
    )

    grounded_signals = grounded.signals["score_signals"]
    broad_signals = broad.signals["score_signals"]
    grounded_policy = grounded.signals["policy_contributions"]
    broad_policy = broad.signals["policy_contributions"]

    assert grounded_signals["benchmark_preference_evidence_boost"] == 0.12
    assert grounded_signals["benchmark_preference_evidence_grounded"] is True
    assert "preference_evidence" in grounded_policy["reason_codes_by_policy"][
        "PreferenceIntentPolicy"
    ]
    assert broad_signals["benchmark_preference_evidence_boost"] == 0.0
    assert broad_signals["benchmark_preference_evidence_grounded"] is False
    assert "PreferenceIntentPolicy" not in broad_policy["reason_codes_by_policy"]
    assert grounded.boost > broad.boost


def test_rerank_policy_requires_reason_grounding_for_preference_reason_query() -> None:
    generic_preference = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("alex", "prefer", "tea"),
            entity_hits=("alex",),
            speaker_hits=("alex",),
            relation_hits=("prefer", "tea"),
            relation_terms=("prefer", "cause"),
            relation_categories=("preference", "causal"),
            relation_category_hits=("preference",),
            relation_category_coverage_ratio=0.5,
            is_preference_query=True,
            has_preference_evidence=True,
            evidence_need=("preference", "causal_support"),
            direct_speaker_turn=True,
            source_locality_score=1.0,
            answerability_score=0.74,
            answerability_reason_codes=(
                "preference_evidence",
                "missing_causal_evidence",
            ),
        )
    )
    preference_reason = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("alex", "prefer", "tea"),
            entity_hits=("alex",),
            speaker_hits=("alex",),
            relation_hits=("prefer", "tea", "because", "calmer"),
            relation_terms=("prefer", "cause"),
            relation_categories=("preference", "causal"),
            relation_category_hits=("preference", "causal"),
            relation_category_coverage_ratio=1.0,
            high_signal_relation_hit_count=1,
            is_preference_query=True,
            has_preference_evidence=True,
            evidence_need=("preference", "causal_support"),
            query_roles=("preference_support", "causal_support"),
            direct_speaker_turn=True,
            source_locality_score=1.0,
            answerability_score=0.9,
            answerability_reason_codes=(
                "preference_evidence",
                "causal_evidence",
                "high_answerability",
            ),
        )
    )

    generic_signals = generic_preference.signals["score_signals"]
    reason_signals = preference_reason.signals["score_signals"]
    reason_policy = preference_reason.signals["policy_contributions"]

    assert generic_signals["benchmark_preference_evidence_boost"] == 0.0
    assert generic_signals["benchmark_preference_reason_required"] is True
    assert generic_signals["benchmark_preference_reason_grounded"] is False
    assert reason_signals["benchmark_preference_evidence_boost"] == 0.12
    assert reason_signals["benchmark_preference_reason_required"] is True
    assert reason_signals["benchmark_preference_reason_grounded"] is True
    assert "preference_reason_grounding" in reason_policy["reason_codes_by_policy"][
        "PreferenceIntentPolicy"
    ]
    assert preference_reason.boost > generic_preference.boost


def test_rerank_policy_allows_unmeasured_direct_preference_locality() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("melanie", "like", "camping"),
            entity_hits=("melanie",),
            speaker_hits=("melanie",),
            relation_hits=("like", "camping"),
            relation_terms=("like", "camping"),
            is_preference_query=True,
            has_preference_evidence=True,
            direct_speaker_turn=True,
            source_locality_score=0.0,
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]

    assert signals["benchmark_preference_evidence_boost"] == 0.12
    assert signals["benchmark_preference_evidence_grounded"] is True
    assert "preference_evidence" in policy["reason_codes_by_policy"][
        "PreferenceIntentPolicy"
    ]
    assert "weak_source_locality_cap" not in signals[
        "benchmark_provenance_safety_reason_codes"
    ]


def test_rerank_policy_requires_grounded_visual_evidence() -> None:
    grounded = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("melanie", "painting"),
            entity_hits=("melanie",),
            speaker_hits=("melanie",),
            relation_hits=("painting",),
            relation_terms=("painting",),
            has_visual_terms=True,
            has_visual_evidence=True,
            direct_speaker_turn=True,
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
        )
    )
    broad = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("melanie", "painting"),
            entity_hits=("melanie",),
            relation_hits=("painting",),
            relation_terms=("painting",),
            has_visual_terms=True,
            has_visual_evidence=True,
            broad_summary=True,
            source_locality_score=0.35,
            source_ref_count=8,
            turn_ref_count=12,
        )
    )

    grounded_signals = grounded.signals["score_signals"]
    broad_signals = broad.signals["score_signals"]
    grounded_policy = grounded.signals["policy_contributions"]
    broad_policy = broad.signals["policy_contributions"]

    assert grounded_signals["benchmark_visual_evidence_boost"] == 0.16
    assert grounded_signals["benchmark_visual_evidence_grounded"] is True
    assert "visual_evidence" in grounded_policy["reason_codes_by_policy"][
        "EvidenceBundlePolicy"
    ]
    assert broad_signals["benchmark_visual_evidence_boost"] == 0.0
    assert broad_signals["benchmark_visual_evidence_grounded"] is False
    assert "EvidenceBundlePolicy" not in broad_policy["reason_codes_by_policy"]
    assert grounded.boost > broad.boost


def test_rerank_policy_allows_unmeasured_direct_visual_locality() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("melanie", "painting"),
            entity_hits=("melanie",),
            speaker_hits=("melanie",),
            relation_hits=("painting",),
            relation_terms=("painting",),
            has_visual_terms=True,
            has_visual_evidence=True,
            direct_speaker_turn=True,
            source_locality_score=0.0,
            source_ref_count=1,
            turn_ref_count=1,
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]

    assert signals["benchmark_visual_evidence_boost"] == 0.16
    assert signals["benchmark_visual_evidence_grounded"] is True
    assert "visual_evidence" in policy["reason_codes_by_policy"][
        "EvidenceBundlePolicy"
    ]
    assert "weak_source_locality_cap" not in signals[
        "benchmark_provenance_safety_reason_codes"
    ]


def test_rerank_policy_accepts_typed_communication_support_need() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "recommend", "book"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("recommend", "book", "said"),
            relation_terms=("recommend", "book"),
            relation_categories=("communication",),
            relation_category_hits=("communication",),
            relation_category_coverage_ratio=1.0,
            direct_speaker_turn=True,
            source_locality_score=1.0,
            evidence_need=("communication",),
            query_roles=("communication_support",),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_typed_relation_support_boost"] == 0.045
    assert signals["benchmark_typed_relation_query_role_boost"] == 0.02
    assert signals["benchmark_typed_relation_support_roles"] == [
        "communication_support"
    ]
    assert signals["benchmark_typed_relation_support_category_hits"] == [
        "communication"
    ]
    assert "typed_relation_support" in policy["reason_codes_by_policy"][
        "TypedRelationSupportPolicy"
    ]
    assert "typed_relation_query_role_support" in policy["reason_codes_by_policy"][
        "TypedRelationSupportPolicy"
    ]


def test_rerank_policy_accepts_unmeasured_source_ref_typed_relation_support() -> None:
    unmeasured = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "recommend", "book"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("recommend", "book", "said"),
            relation_terms=("recommend", "book"),
            relation_categories=("communication",),
            relation_category_hits=("communication",),
            relation_category_coverage_ratio=1.0,
            source_locality_score=0.0,
            source_ref_count=1,
            turn_ref_count=1,
            evidence_need=("communication",),
            query_roles=("communication_support",),
        )
    )
    measured_weak = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "recommend", "book"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("recommend", "book", "said"),
            relation_terms=("recommend", "book"),
            relation_categories=("communication",),
            relation_category_hits=("communication",),
            relation_category_coverage_ratio=1.0,
            source_locality_score=0.35,
            source_ref_count=1,
            turn_ref_count=1,
            evidence_need=("communication",),
            query_roles=("communication_support",),
        )
    )

    unmeasured_signals = unmeasured.signals["score_signals"]
    measured_signals = measured_weak.signals["score_signals"]

    assert unmeasured_signals["benchmark_typed_relation_support_boost"] == 0.045
    assert unmeasured_signals["benchmark_typed_relation_query_role_boost"] == 0.02
    assert (
        unmeasured_signals["benchmark_typed_relation_support_precise_provenance"]
        is True
    )
    assert measured_signals["benchmark_typed_relation_support_boost"] == 0.0
    assert (
        measured_signals["benchmark_typed_relation_support_precise_provenance"]
        is False
    )


def test_rerank_policy_accepts_category_grounded_typed_profile_support() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("alex", "medicine", "zyrtec"),
            entity_hits=("alex",),
            relation_hits=(),
            relation_terms=("health",),
            relation_categories=("health_profile",),
            relation_category_hits=("health_profile",),
            relation_category_coverage_ratio=1.0,
            source_locality_score=1.0,
            evidence_need=("health_profile",),
            query_roles=("health_support",),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_typed_relation_support_boost"] == 0.045
    assert signals["benchmark_typed_relation_query_role_boost"] == 0.02
    assert signals["benchmark_typed_relation_support_roles"] == ["health_support"]
    assert signals["benchmark_typed_relation_support_category_hits"] == [
        "health_profile"
    ]
    assert "typed_relation_support" in policy["reason_codes_by_policy"][
        "TypedRelationSupportPolicy"
    ]


def test_rerank_policy_role_boost_uses_only_typed_relation_hit_roles() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("alex", "medicine", "zyrtec"),
            entity_hits=("alex",),
            relation_hits=(),
            relation_terms=("health", "status"),
            relation_categories=("health_profile", "status_profile"),
            relation_category_hits=("health_profile",),
            relation_category_coverage_ratio=0.5,
            source_locality_score=1.0,
            evidence_need=("health_profile", "status_profile"),
            query_roles=("health_support", "status_support"),
        )
    )

    signals = score.signals["score_signals"]
    assert signals["benchmark_typed_relation_support_boost"] == 0.045
    assert signals["benchmark_typed_relation_query_role_boost"] == 0.02
    assert signals["benchmark_typed_relation_support_roles"] == [
        "health_support",
        "status_support",
    ]
    assert signals["benchmark_typed_relation_support_hit_roles"] == [
        "health_support"
    ]


def test_rerank_policy_rejects_ungrounded_typed_profile_category_hit() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("medicine", "zyrtec"),
            relation_hits=(),
            relation_terms=("health",),
            relation_categories=("health_profile",),
            relation_category_hits=("health_profile",),
            relation_category_coverage_ratio=1.0,
            source_locality_score=1.0,
            evidence_need=("health_profile",),
            query_roles=("health_support",),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_typed_relation_support_boost"] == 0.0
    assert signals["benchmark_typed_relation_query_role_boost"] == 0.0
    assert "TypedRelationSupportPolicy" not in policy["reason_codes_by_policy"]


def test_rerank_policy_rejects_typed_support_role_without_category_hit() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "recommend"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("recommend", "book"),
            relation_terms=("recommend", "book"),
            relation_categories=("communication",),
            direct_speaker_turn=True,
            source_locality_score=1.0,
            evidence_need=("communication",),
            query_roles=("communication_support",),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_typed_relation_support_boost"] == 0.0
    assert signals["benchmark_typed_relation_query_role_boost"] == 0.0
    assert "TypedRelationSupportPolicy" not in policy["reason_codes_by_policy"]


def test_rerank_policy_requires_speaker_grounding_for_communication_support() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("alex", "project", "delay"),
            entity_hits=("alex",),
            relation_hits=("told",),
            relation_terms=("tell",),
            relation_categories=("communication",),
            relation_category_hits=("communication",),
            relation_category_coverage_ratio=1.0,
            direct_speaker_turn=True,
            source_locality_score=1.0,
            evidence_need=("communication",),
            query_roles=("communication_support",),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_typed_relation_support_boost"] == 0.0
    assert signals["benchmark_typed_relation_query_role_boost"] == 0.0
    assert "TypedRelationSupportPolicy" not in policy["reason_codes_by_policy"]


def test_rerank_policy_boosts_precise_speaker_grounding() -> None:
    grounded = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline",),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            direct_speaker_turn=True,
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
        )
    )
    entity_only = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline",),
            entity_hits=("caroline",),
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
        )
    )

    signals = grounded.signals["score_signals"]
    policy = grounded.signals["policy_contributions"]
    assert grounded.boost > entity_only.boost
    assert signals["benchmark_speaker_grounding_boost"] == 0.045
    assert signals["benchmark_speaker_grounding_evidence"] is True
    assert signals["benchmark_effective_boost_cap"] == 0.4
    assert "speaker_grounding" in policy["reason_codes_by_policy"][
        "EntitySpeakerPolicy"
    ]


def test_rerank_policy_allows_unmeasured_speaker_grounding_locality() -> None:
    unmeasured = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline",),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            direct_speaker_turn=True,
            source_locality_score=0.0,
            source_ref_count=1,
            turn_ref_count=1,
        )
    )
    measured_weak = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline",),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            direct_speaker_turn=True,
            source_locality_score=0.35,
            source_ref_count=1,
            turn_ref_count=1,
        )
    )

    unmeasured_signals = unmeasured.signals["score_signals"]
    measured_signals = measured_weak.signals["score_signals"]
    unmeasured_policy = unmeasured.signals["policy_contributions"]

    assert unmeasured_signals["benchmark_speaker_grounding_boost"] == 0.045
    assert unmeasured_signals["benchmark_speaker_grounding_evidence"] is True
    assert "speaker_grounding" in unmeasured_policy["reason_codes_by_policy"][
        "EntitySpeakerPolicy"
    ]
    assert measured_signals["benchmark_speaker_grounding_boost"] == 0.0
    assert measured_signals["benchmark_speaker_grounding_evidence"] is False


def test_rerank_policy_rejects_broad_summary_speaker_grounding() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline",),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            direct_speaker_turn=True,
            broad_summary=True,
            source_locality_score=0.45,
            source_ref_count=6,
            turn_ref_count=12,
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_speaker_grounding_boost"] == 0.0
    assert signals["benchmark_speaker_grounding_evidence"] is False
    assert "speaker_grounding" not in policy["reason_codes_by_policy"][
        "EntitySpeakerPolicy"
    ]


def test_rerank_policy_rejects_generic_move_as_location_support() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "move"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("move",),
            relation_terms=("move",),
            relation_categories=("location_transition",),
            direct_speaker_turn=True,
            source_locality_score=1.0,
            evidence_need=("location_support",),
            query_roles=("location_support",),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert signals["benchmark_location_support_boost"] == 0.0
    assert signals["benchmark_location_query_role_boost"] == 0.0
    assert "LocationIntentPolicy" not in policy["reason_codes_by_policy"]


def test_rerank_policy_caps_broad_summary_without_role_specific_grounding() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "relationship", "family", "support"),
            entity_hits=("caroline",),
            relation_hits=("parent", "breakup", "family", "support"),
            relation_terms=("relationship", "status", "family", "support"),
            high_signal_relation_hit_count=1,
            broad_summary=True,
            source_locality_score=0.35,
            source_ref_count=8,
            turn_ref_count=12,
            answerability_score=0.48,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_satisfied",
                "source_provenance",
                "broad_summary_penalty",
                "low_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]
    assert score.boost == 0.24
    assert signals["benchmark_provenance_safety_cap_applied"] is True
    assert signals["benchmark_effective_boost_cap"] == 0.24
    assert "broad_summary_low_provenance_cap" in signals[
        "benchmark_provenance_safety_reason_codes"
    ]
    assert "low_answerability_cap" in signals[
        "benchmark_provenance_safety_reason_codes"
    ]


def test_rerank_policy_keeps_precise_direct_turn_above_broad_summary_cap() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "relationship", "family", "support"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("parent", "breakup", "family", "support"),
            relation_terms=("relationship", "status", "family", "support"),
            high_signal_relation_hit_count=1,
            direct_speaker_turn=True,
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
            answerability_score=0.92,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_satisfied",
                "direct_provenance",
                "high_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]
    assert score.boost > 0.24
    assert signals["benchmark_provenance_safety_cap_applied"] is False
    assert signals["benchmark_effective_boost_cap"] == signals[
        "benchmark_uncapped_boost_cap"
    ]


def test_rerank_policy_keeps_unmeasured_direct_relation_above_low_answerability_cap() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "relationship", "family", "support"),
            entity_hits=("caroline",),
            speaker_hits=("caroline",),
            relation_hits=("parent", "breakup", "family", "support"),
            relation_terms=("relationship", "status", "family", "support"),
            high_signal_relation_hit_count=1,
            direct_speaker_turn=True,
            source_locality_score=0.0,
            source_ref_count=1,
            turn_ref_count=1,
            answerability_score=0.48,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_satisfied",
                "source_provenance",
                "low_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]

    assert signals["benchmark_direct_speaker_relation_evidence"] is True
    assert signals["benchmark_provenance_safety_cap_applied"] is False
    assert "low_answerability_cap" not in signals[
        "benchmark_provenance_safety_reason_codes"
    ]
    assert signals["benchmark_effective_boost_cap"] == signals[
        "benchmark_uncapped_boost_cap"
    ]


def test_rerank_policy_caps_weak_locality_low_answerability_evidence() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "status", "support"),
            entity_hits=("caroline",),
            relation_hits=("status", "support", "family"),
            relation_terms=("relationship", "status", "support"),
            high_signal_relation_hit_count=0,
            source_locality_score=0.3,
            source_ref_count=6,
            turn_ref_count=0,
            answerability_score=0.44,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_partial",
                "source_provenance",
                "low_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]
    assert score.boost == 0.26
    assert signals["benchmark_provenance_safety_cap_applied"] is True
    assert signals["benchmark_provenance_safety_reason_codes"] == [
        "weak_source_locality_cap",
        "low_answerability_cap",
    ]


def test_rerank_policy_caps_stale_evidence_without_contrast_grounding() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("caroline", "status", "support"),
            entity_hits=("caroline",),
            relation_hits=("status", "support", "family"),
            relation_terms=("relationship", "status", "support"),
            high_signal_relation_hit_count=0,
            source_locality_score=0.9,
            source_ref_count=1,
            turn_ref_count=1,
            answerability_score=0.74,
            conflict_or_stale=True,
            stale_surface=True,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_partial",
                "source_provenance",
                "medium_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]
    assert signals["benchmark_contrast_support_boost"] == 0.0
    assert score.boost == 0.22
    assert signals["benchmark_provenance_safety_reason_codes"] == [
        "unsupported_stale_evidence_cap"
    ]


def test_rerank_policy_caps_missing_typed_profile_evidence() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("alex", "zyrtec", "medication", "morning"),
            entity_hits=("alex",),
            relation_hits=(
                "take",
                "zyrtec",
                "medication",
                "morning",
                "allergy",
                "daily",
            ),
            relation_terms=("take", "medication", "morning"),
            relation_categories=("health_profile",),
            source_locality_score=0.9,
            source_ref_count=1,
            turn_ref_count=1,
            answerability_score=0.62,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_satisfied",
                "source_provenance",
                "missing_health_profile_evidence",
                "medium_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]
    assert score.boost == 0.4
    assert signals["benchmark_effective_boost_cap"] == 0.4
    assert signals["benchmark_provenance_safety_reason_codes"] == [
        "missing_health_profile_evidence_cap"
    ]


def test_rerank_policy_prefers_complete_event_support_over_generic_partial_overlap() -> None:
    complete = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("morgan", "community", "event"),
            entity_hits=("morgan",),
            speaker_hits=("morgan",),
            relation_hits=("attended", "registered", "event"),
            relation_terms=("community", "event", "attended"),
            relation_categories=("participation_event",),
            relation_category_hits=("participation_event",),
            evidence_need=("event_support",),
            query_roles=("event_support",),
            direct_speaker_turn=True,
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
            answerability_score=0.78,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_satisfied",
                "source_provenance",
                "medium_answerability",
            ),
        )
    )
    partial = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("morgan", "community", "event"),
            entity_hits=("morgan",),
            relation_hits=("community", "activity", "people"),
            relation_terms=("community", "event", "attended"),
            relation_categories=("participation_event",),
            relation_category_hits=("activity",),
            evidence_need=("event_support",),
            query_roles=("event_support",),
            source_locality_score=1.0,
            source_ref_count=1,
            turn_ref_count=1,
            answerability_score=0.92,
            answerability_reason_codes=(
                "entity_satisfied",
                "relation_partial",
                "source_provenance",
                "missing_participation_event_evidence",
                "high_answerability",
            ),
        )
    )

    complete_signals = complete.signals["score_signals"]
    partial_signals = partial.signals["score_signals"]

    assert complete.boost > partial.boost
    assert partial.boost > 0
    assert complete_signals["benchmark_typed_relation_support_boost"] == 0.045
    assert complete_signals["benchmark_answerability_boost_eligible"] is True
    assert partial_signals["benchmark_typed_relation_support_boost"] == 0.0
    assert partial_signals["benchmark_answerability_boost_eligible"] is False
    assert "missing_participation_event_evidence_cap" in partial_signals[
        "benchmark_provenance_safety_reason_codes"
    ]


def test_rerank_policy_boosts_support_goal_category_without_named_entity() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("adoption", "agency", "support"),
            relation_terms=("adoption", "agency", "support"),
            relation_categories=("support_goal",),
            relation_category_hits=("support_goal",),
            evidence_need=("support_goal",),
            query_roles=("support_goal_support",),
            direct_speaker_turn=True,
            source_ref_count=1,
            turn_ref_count=1,
            answerability_score=0.78,
            answerability_reason_codes=(
                "relation_satisfied",
                "source_provenance",
                "medium_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]

    assert signals["benchmark_typed_relation_support_boost"] == 0.045
    assert signals["benchmark_typed_relation_query_role_boost"] == 0.02
    assert signals["benchmark_typed_relation_support_hit_roles"] == [
        "support_goal_support"
    ]
    assert "typed_relation_support" in policy["reason_codes_by_policy"][
        "TypedRelationSupportPolicy"
    ]
    assert "typed_relation_query_role_support" in policy["reason_codes_by_policy"][
        "TypedRelationSupportPolicy"
    ]


def test_rerank_policy_rejects_broad_support_goal_category_without_grounding() -> None:
    score = score_benchmark_rerank_candidate(
        _features(
            overlap_terms=("adoption", "agency", "support"),
            relation_terms=("adoption", "agency", "support"),
            relation_categories=("support_goal",),
            relation_category_hits=("support_goal",),
            evidence_need=("support_goal",),
            query_roles=("support_goal_support",),
            broad_summary=True,
            source_locality_score=0.35,
            answerability_score=0.42,
            answerability_reason_codes=(
                "relation_partial",
                "low_answerability",
            ),
        )
    )

    signals = score.signals["score_signals"]

    assert signals["benchmark_typed_relation_support_boost"] == 0.0
    assert signals["benchmark_typed_relation_query_role_boost"] == 0.0


def _features(**overrides: object) -> BenchmarkRerankFeatures:
    values = {
        "overlap_terms": (),
        "entity_hits": (),
        "speaker_hits": (),
        "relation_hits": (),
        "relation_terms": (),
        "query_has_entities": True,
        "high_signal_relation_hit_count": 0,
        "is_temporal_query": False,
        "has_temporal_surface": False,
        "has_sequence_surface": False,
        "is_preference_query": False,
        "has_preference_evidence": False,
        "has_visual_terms": False,
        "has_visual_evidence": False,
        "focused_turn_boost": 0.0,
        "has_multi_hop_markers": False,
    }
    values.update(overrides)
    return BenchmarkRerankFeatures(**values)
