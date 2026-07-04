"""Policy scoring for memory-comparison benchmark rerank candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from infinity_context_server.memory_comparison_rerank_policies import (
    score_rerank_policy_contributions,
)


@dataclass(frozen=True)
class BenchmarkRerankFeatures:
    """Question-only candidate features used by benchmark rerank policies."""

    overlap_terms: tuple[str, ...]
    entity_hits: tuple[str, ...]
    speaker_hits: tuple[str, ...]
    relation_hits: tuple[str, ...]
    relation_terms: tuple[str, ...]
    query_has_entities: bool
    high_signal_relation_hit_count: int
    is_temporal_query: bool
    has_temporal_surface: bool
    has_sequence_surface: bool
    is_preference_query: bool
    has_preference_evidence: bool
    has_visual_terms: bool
    has_visual_evidence: bool
    focused_turn_boost: float
    has_multi_hop_markers: bool
    relation_categories: tuple[str, ...] = ()
    relation_category_hits: tuple[str, ...] = ()
    relation_category_coverage_ratio: float = 0.0
    exact_count_evidence: bool = False
    list_item_count: int = 0
    policy_boosts: Mapping[str, float] = field(default_factory=dict)
    shape_boosts: Mapping[str, float] = field(default_factory=dict)
    source_type: str = "unknown"
    source_ref_count: int = 0
    turn_ref_count: int = 0
    source_ref_density: float = 0.0
    source_locality_score: float = 1.0
    direct_speaker_turn: bool = False
    broad_summary: bool = False
    conflict_or_stale: bool = False
    negation_surface: bool = False
    currentness_surface: bool = False
    stale_surface: bool = False
    contrast_surface: bool = False
    answerability_score: float = 0.0
    answerability_reason_codes: tuple[str, ...] = ()
    evidence_need: tuple[str, ...] = ()
    query_roles: tuple[str, ...] = ()
    temporal_query_terms: tuple[str, ...] = ()
    current_state_query: bool = False
    time_intent_kind: str = ""
    has_duration_surface: bool = False
    has_relative_time_surface: bool = False
    has_explicit_time_surface: bool = False
    has_explicit_time_content_surface: bool = False
    has_temporal_sequence_surface: bool = False
    covered_answer_unit_shapes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkRerankScore:
    """Final bounded boost and diagnostics for a rerank candidate."""

    boost: float
    signals: dict[str, object]


def score_benchmark_rerank_candidate(
    features: BenchmarkRerankFeatures,
) -> BenchmarkRerankScore:
    policy_plan = score_rerank_policy_contributions(features)
    score_signals = policy_plan.score_signals
    temporal_boost = _float_signal(score_signals, "benchmark_temporal_text_boost")
    temporal_sequence_boost = _float_signal(
        score_signals,
        "benchmark_temporal_sequence_boost",
    )
    currentness_boost = _float_signal(
        score_signals,
        "benchmark_currentness_support_boost",
    )
    preference_boost = _float_signal(
        score_signals,
        "benchmark_preference_evidence_boost",
    )
    visual_boost = _float_signal(score_signals, "benchmark_visual_evidence_boost")
    answerability_boost = _float_signal(
        score_signals,
        "benchmark_answerability_boost",
    )
    speaker_grounding_boost = _float_signal(
        score_signals,
        "benchmark_speaker_grounding_boost",
    )
    temporal_role_support_boost = _float_signal(
        score_signals,
        "benchmark_temporal_role_support_boost",
    )
    contrast_support_boost = _float_signal(
        score_signals,
        "benchmark_contrast_support_boost",
    )
    location_support_boost = _float_signal(
        score_signals,
        "benchmark_location_support_boost",
    ) + _float_signal(score_signals, "benchmark_location_query_role_boost")
    value_answer_shape_boost = _float_signal(
        score_signals,
        "benchmark_value_answer_shape_boost",
    ) + _float_signal(score_signals, "benchmark_value_query_role_boost")
    count_list_answer_shape_boost = _float_signal(
        score_signals,
        "benchmark_count_answer_shape_boost",
    ) + _float_signal(
        score_signals,
        "benchmark_list_answer_shape_boost",
    ) + _float_signal(score_signals, "benchmark_count_list_query_role_boost")
    typed_relation_support_boost = _float_signal(
        score_signals,
        "benchmark_typed_relation_support_boost",
    ) + _float_signal(score_signals, "benchmark_typed_relation_query_role_boost")
    strong_relation_evidence = _bool_signal(
        score_signals,
        "benchmark_strong_relation_evidence",
    )
    direct_speaker_relation_evidence = _bool_signal(
        score_signals,
        "benchmark_direct_speaker_relation_evidence",
    )
    rich_direct_speaker_relation_evidence = _bool_signal(
        score_signals,
        "benchmark_rich_direct_speaker_relation_evidence",
    )
    focused_relation_density_boost = _float_signal(
        score_signals,
        "benchmark_focused_relation_density_boost",
    )
    relation_coverage_boost = _float_signal(
        score_signals,
        "benchmark_relation_coverage_boost",
    )
    policy_boosts = _rounded_boosts(features.policy_boosts)
    shape_boosts = _rounded_boosts(features.shape_boosts)
    boost_cap = _boost_cap(
        features=features,
        focused_turn_boost=features.focused_turn_boost,
        focused_relation_density_boost=focused_relation_density_boost,
        relation_coverage_boost=relation_coverage_boost,
        strong_relation_evidence=strong_relation_evidence,
        rich_direct_speaker_relation_evidence=rich_direct_speaker_relation_evidence,
        direct_speaker_relation_evidence=direct_speaker_relation_evidence,
        temporal_boost=temporal_boost,
        temporal_sequence_boost=temporal_sequence_boost,
        currentness_boost=currentness_boost,
        preference_boost=preference_boost,
        visual_boost=visual_boost,
        answerability_boost=answerability_boost,
        speaker_grounding_boost=speaker_grounding_boost,
        temporal_role_support_boost=temporal_role_support_boost,
        contrast_support_boost=contrast_support_boost,
        location_support_boost=location_support_boost,
        value_answer_shape_boost=value_answer_shape_boost,
        count_list_answer_shape_boost=count_list_answer_shape_boost,
        typed_relation_support_boost=typed_relation_support_boost,
        policy_boosts=policy_boosts,
        shape_boosts=shape_boosts,
    )
    uncapped_boost_cap = boost_cap
    boost_cap, safety_reason_codes = _apply_provenance_safety_cap(
        boost_cap,
        features=features,
        score_signals=score_signals,
    )
    total_boost = max(0.0, min(boost_cap, policy_plan.total_score))
    score_signals = {
        **score_signals,
        "benchmark_uncapped_boost_cap": round(uncapped_boost_cap, 6),
        "benchmark_effective_boost_cap": round(boost_cap, 6),
        "benchmark_provenance_safety_cap_applied": bool(safety_reason_codes),
        "benchmark_provenance_safety_reason_codes": list(safety_reason_codes),
    }
    return BenchmarkRerankScore(
        boost=round(total_boost, 6),
        signals={
            "overlap_terms": list(features.overlap_terms),
            "entity_hits": list(features.entity_hits),
            "speaker_hits": list(features.speaker_hits),
            "score_signals": score_signals,
            "policy_contributions": policy_plan.to_diagnostics(),
        },
    )


def _relation_boost(features: BenchmarkRerankFeatures) -> float:
    relation_hit_count = len(features.relation_hits)
    if relation_hit_count >= 4:
        return 0.16 if features.entity_hits or not features.query_has_entities else 0.14
    if relation_hit_count >= 3:
        return 0.14 if features.entity_hits or not features.query_has_entities else 0.105
    if features.relation_hits and (
        features.entity_hits or not features.query_has_entities
    ):
        return 0.11 if relation_hit_count >= 2 else 0.055
    if relation_hit_count >= 2:
        return 0.075
    return 0.0


def _relation_coverage_boost(features: BenchmarkRerankFeatures) -> float:
    if features.high_signal_relation_hit_count >= 2:
        return 0.065
    relation_hit_count = len(features.relation_hits)
    if relation_hit_count >= 10:
        return 0.12
    if relation_hit_count >= 8:
        return 0.09
    if relation_hit_count >= 6:
        return 0.055
    return 0.0


def _focused_relation_density_boost(features: BenchmarkRerankFeatures) -> float:
    if features.focused_turn_boost <= 0:
        return 0.0
    if {"write", "career"}.issubset(set(features.relation_terms)):
        return 0.0
    relation_hit_count = len(features.relation_hits)
    if relation_hit_count >= 5 and features.high_signal_relation_hit_count >= 1:
        return 0.08
    if relation_hit_count >= 4:
        return 0.06
    if relation_hit_count >= 3 and features.high_signal_relation_hit_count >= 1:
        return 0.05
    return 0.0


def _boost_cap(
    *,
    features: BenchmarkRerankFeatures,
    focused_turn_boost: float,
    focused_relation_density_boost: float,
    relation_coverage_boost: float,
    strong_relation_evidence: bool,
    rich_direct_speaker_relation_evidence: bool,
    direct_speaker_relation_evidence: bool,
    temporal_boost: float,
    temporal_sequence_boost: float,
    currentness_boost: float,
    preference_boost: float,
    visual_boost: float,
    answerability_boost: float,
    speaker_grounding_boost: float,
    temporal_role_support_boost: float,
    contrast_support_boost: float,
    location_support_boost: float,
    value_answer_shape_boost: float,
    count_list_answer_shape_boost: float,
    typed_relation_support_boost: float,
    policy_boosts: Mapping[str, float],
    shape_boosts: Mapping[str, float],
) -> float:
    high_confidence_policy_keys = {
        "benchmark_outdoor_park_preference_boost",
        "benchmark_support_motivation_boost",
        "benchmark_identity_visual_identity_boost",
        "benchmark_political_context_boost",
        "benchmark_adoption_agency_support_boost",
        "benchmark_conference_plan_time_boost",
        "benchmark_relationship_status_context_boost",
    }
    medium_confidence_policy_keys = {
        "benchmark_research_goal_boost",
        "benchmark_excited_outcome_boost",
        "benchmark_song_preference_boost",
        "benchmark_writing_affinity_boost",
        "benchmark_current_goal_context_boost",
        "benchmark_registration_event_boost",
        "benchmark_symbolic_meaning_boost",
        "benchmark_participation_event_boost",
        "benchmark_emotion_response_boost",
    }
    if (
        any(policy_boosts.get(key, 0.0) > 0 for key in high_confidence_policy_keys)
        or any(shape_boosts.values())
    ):
        return 0.62
    if any(policy_boosts.get(key, 0.0) > 0 for key in medium_confidence_policy_keys):
        return 0.62
    if (
        focused_turn_boost > 0
        and focused_relation_density_boost > 0
        and features.source_locality_score >= 0.95
        and not features.broad_summary
    ):
        return 0.62
    if (
        typed_relation_support_boost > 0
        and features.direct_speaker_turn
        and features.relation_category_coverage_ratio >= 1.0
        and features.relation_hits
        and not features.broad_summary
        and (
            features.source_locality_score >= 0.65
            or _has_unmeasured_source_ref_locality(features)
        )
    ):
        return 0.6
    if focused_relation_density_boost > 0 and strong_relation_evidence:
        return 0.6
    if relation_coverage_boost >= 0.09 and strong_relation_evidence:
        return 0.58
    if relation_coverage_boost >= 0.055 and strong_relation_evidence:
        return 0.54
    if focused_turn_boost > 0 and strong_relation_evidence:
        return 0.56
    if focused_turn_boost > 0:
        return 0.52
    if strong_relation_evidence:
        return 0.5
    if rich_direct_speaker_relation_evidence:
        return 0.46
    if direct_speaker_relation_evidence:
        return 0.42
    if temporal_role_support_boost > 0 and (
        temporal_boost > 0 or temporal_sequence_boost > 0
    ):
        return 0.46
    if location_support_boost > 0:
        return 0.46
    if value_answer_shape_boost > 0:
        return 0.46
    if count_list_answer_shape_boost > 0:
        return 0.46
    if typed_relation_support_boost > 0:
        return 0.46
    if speaker_grounding_boost > 0:
        return 0.4
    if answerability_boost > 0:
        return 0.4
    if contrast_support_boost > 0 or currentness_boost > 0:
        return 0.4
    if (
        visual_boost > 0
        or focused_turn_boost > 0
        or preference_boost > 0
        or temporal_boost > 0
        or temporal_sequence_boost > 0
        or currentness_boost > 0
        or contrast_support_boost > 0
        or location_support_boost > 0
        or value_answer_shape_boost > 0
        or count_list_answer_shape_boost > 0
        or typed_relation_support_boost > 0
    ):
        return 0.38
    return 0.28


def _apply_provenance_safety_cap(
    boost_cap: float,
    *,
    features: BenchmarkRerankFeatures,
    score_signals: Mapping[str, object],
) -> tuple[float, tuple[str, ...]]:
    safety_cap, reason_codes = _provenance_safety_cap(
        features,
        score_signals=score_signals,
    )
    if safety_cap is None:
        return boost_cap, ()
    return min(boost_cap, safety_cap), reason_codes


def _provenance_safety_cap(
    features: BenchmarkRerankFeatures,
    *,
    score_signals: Mapping[str, object],
) -> tuple[float | None, tuple[str, ...]]:
    caps: list[tuple[float, str]] = []
    if features.broad_summary and not _has_role_specific_grounding(
        features,
        score_signals=score_signals,
    ):
        caps.append((0.24, "broad_summary_low_provenance_cap"))
    if (
        0 < features.source_locality_score < 0.45
        and not _has_precise_grounding(features, score_signals=score_signals)
    ):
        caps.append((0.3, "weak_source_locality_cap"))
    if (
        features.answerability_score > 0
        and features.answerability_score < 0.55
        and not _has_role_specific_grounding(features, score_signals=score_signals)
    ):
        caps.append((0.26, "low_answerability_cap"))
    if _stale_only_current_state_evidence(features):
        caps.append((0.28, "stale_only_current_state_cap"))
    answerability_reasons = set(features.answerability_reason_codes)
    missing_evidence_caps = {
        "missing_causal_evidence": 0.4,
        "missing_contrast_evidence": 0.4,
        "missing_registration_event_evidence": 0.4,
        "missing_symbolic_meaning_evidence": 0.4,
        "missing_participation_event_evidence": 0.4,
        "missing_emotion_response_evidence": 0.4,
        "missing_communication_evidence": 0.4,
        "missing_exchange_evidence": 0.4,
        "missing_favorite_preference_evidence": 0.28,
        "missing_preference_evidence": 0.4,
        "missing_status_profile_evidence": 0.4,
        "missing_activity_evidence": 0.4,
        "missing_activity_profile_evidence": 0.4,
        "missing_current_goal_evidence": 0.4,
        "missing_location_transition_evidence": 0.3,
        "missing_support_goal_evidence": 0.4,
        "missing_identity_profile_evidence": 0.4,
        "missing_commitment_profile_evidence": 0.4,
        "missing_contact_profile_evidence": 0.4,
        "missing_diet_profile_evidence": 0.4,
        "missing_duration_temporal_evidence": 0.4,
        "missing_education_profile_evidence": 0.4,
        "missing_employment_profile_evidence": 0.4,
        "missing_explicit_temporal_evidence": 0.4,
        "missing_age_profile_evidence": 0.4,
        "missing_alias_profile_evidence": 0.4,
        "missing_date_profile_evidence": 0.32,
        "missing_health_profile_evidence": 0.4,
        "missing_pet_profile_evidence": 0.4,
        "missing_relative_temporal_evidence": 0.4,
        "missing_sequence_temporal_evidence": 0.4,
        "missing_skill_profile_evidence": 0.4,
        "missing_temporal_evidence": 0.4,
        "missing_vehicle_profile_evidence": 0.4,
        "missing_visual_evidence": 0.4,
    }
    for reason, cap in missing_evidence_caps.items():
        if reason in answerability_reasons:
            caps.append((cap, f"{reason}_cap"))
    if features.conflict_or_stale and not _has_contrast_grounding(score_signals):
        caps.append((0.22, "unsupported_stale_evidence_cap"))
    if not caps:
        return None, ()
    safety_cap = min(cap for cap, _reason in caps)
    return safety_cap, tuple(reason for _cap, reason in caps)


def _has_precise_grounding(
    features: BenchmarkRerankFeatures,
    *,
    score_signals: Mapping[str, object],
) -> bool:
    if not features.direct_speaker_turn:
        return False
    if (
        features.source_locality_score < 0.65
        and not _has_unmeasured_source_ref_locality(features)
    ):
        return False
    return bool(
        _bool_signal(score_signals, "benchmark_rich_direct_speaker_relation_evidence")
        or _bool_signal(score_signals, "benchmark_direct_speaker_relation_evidence")
        or features.high_signal_relation_hit_count > 0
    )


def _has_role_specific_grounding(
    features: BenchmarkRerankFeatures,
    *,
    score_signals: Mapping[str, object],
) -> bool:
    if _has_precise_grounding(features, score_signals=score_signals):
        return True
    if _float_signal(score_signals, "benchmark_visual_evidence_boost") > 0:
        return True
    if _float_signal(score_signals, "benchmark_preference_evidence_boost") > 0 and (
        features.relation_hits or features.high_signal_relation_hit_count > 0
    ):
        return True
    if _float_signal(score_signals, "benchmark_temporal_role_support_boost") > 0:
        return bool(
            features.has_duration_surface
            or features.has_relative_time_surface
            or features.has_explicit_time_content_surface
            or features.has_temporal_sequence_surface
        )
    if _float_signal(score_signals, "benchmark_location_support_boost") > 0:
        return bool(
            "location_transition" in set(features.relation_category_hits)
            and features.relation_hits
        )
    if _float_signal(score_signals, "benchmark_typed_relation_support_boost") > 0:
        return bool(features.relation_category_hits and features.relation_hits)
    if (
        any(float(value) > 0 for value in features.shape_boosts.values())
        and features.direct_speaker_turn
        and (
            features.source_locality_score >= 0.65
            or _has_unmeasured_source_ref_locality(features)
        )
        and not features.broad_summary
    ):
        return True
    return bool(_has_contrast_grounding(score_signals))


def _has_unmeasured_source_ref_locality(features: BenchmarkRerankFeatures) -> bool:
    return bool(
        features.source_locality_score <= 0
        and (features.source_ref_count > 0 or features.turn_ref_count > 0)
    )


def _has_contrast_grounding(score_signals: Mapping[str, object]) -> bool:
    return (
        _float_signal(score_signals, "benchmark_contrast_support_boost") > 0
        or _float_signal(score_signals, "benchmark_currentness_support_boost") > 0
    )


def _rounded_boosts(boosts: Mapping[str, float]) -> dict[str, float]:
    return {key: round(float(value), 6) for key, value in boosts.items()}


def _float_signal(signals: Mapping[str, object], key: str) -> float:
    value = signals.get(key)
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _stale_only_current_state_evidence(features: BenchmarkRerankFeatures) -> bool:
    return bool(
        features.current_state_query
        and features.stale_surface
        and not features.currentness_surface
    )


def _bool_signal(signals: Mapping[str, object], key: str) -> bool:
    return signals.get(key) is True
