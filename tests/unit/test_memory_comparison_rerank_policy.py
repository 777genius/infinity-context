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
        )
    )

    signals = score.signals["score_signals"]
    policy = score.signals["policy_contributions"]
    assert score.boost == 0.6
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
