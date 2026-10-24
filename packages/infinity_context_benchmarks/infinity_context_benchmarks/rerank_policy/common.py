"""Benchmark-owned common scoring policy."""

from __future__ import annotations

from collections.abc import Mapping

from infinity_context_benchmarks.rerank_policy.contracts import RerankPolicyFeatures


def _rounded_boosts(boosts: Mapping[str, float]) -> dict[str, float]:
    return {key: round(float(value), 6) for key, value in boosts.items()}


def _has_measured_locality_below(
    features: RerankPolicyFeatures,
    threshold: float,
) -> bool:
    return 0 < features.source_locality_score < threshold


def _has_precise_or_unmeasured_source_provenance(
    features: RerankPolicyFeatures,
) -> bool:
    if features.broad_summary:
        return False
    if features.direct_speaker_turn:
        return True
    if features.source_locality_score >= 0.65:
        return True
    return bool(
        features.source_locality_score <= 0
        and (features.source_ref_count > 0 or features.turn_ref_count > 0)
    )


def _has_positive_boost(boosts: Mapping[str, float]) -> bool:
    return any(float(value) > 0 for value in boosts.values())


def _has_missing_required_answer_evidence(features: RerankPolicyFeatures) -> bool:
    return bool(
        set(features.answerability_reason_codes).intersection(
            _MISSING_REQUIRED_ANSWER_EVIDENCE_REASONS
        )
    )


_MISSING_REQUIRED_ANSWER_EVIDENCE_REASONS = frozenset(
    {
        "missing_action_event_evidence",
        "missing_activity_evidence",
        "missing_activity_profile_evidence",
        "missing_age_profile_evidence",
        "missing_alias_profile_evidence",
        "missing_causal_evidence",
        "missing_commitment_profile_evidence",
        "missing_community_membership_evidence",
        "missing_communication_evidence",
        "missing_contact_profile_evidence",
        "missing_contrast_evidence",
        "missing_current_goal_evidence",
        "missing_date_profile_evidence",
        "missing_diet_profile_evidence",
        "missing_duration_temporal_evidence",
        "missing_education_profile_evidence",
        "missing_emotion_response_evidence",
        "missing_employment_profile_evidence",
        "missing_exchange_evidence",
        "missing_explicit_temporal_evidence",
        "missing_favorite_preference_evidence",
        "missing_health_profile_evidence",
        "missing_identity_profile_evidence",
        "missing_location_transition_evidence",
        "missing_participation_event_evidence",
        "missing_pet_profile_evidence",
        "missing_preference_evidence",
        "missing_relative_temporal_evidence",
        "missing_registration_event_evidence",
        "missing_sequence_temporal_evidence",
        "missing_skill_profile_evidence",
        "missing_status_profile_evidence",
        "missing_support_goal_evidence",
        "missing_symbolic_meaning_evidence",
        "missing_temporal_evidence",
        "missing_vehicle_profile_evidence",
        "missing_visual_evidence",
    }
)


def _reason_codes(*pairs: tuple[str, float]) -> tuple[str, ...]:
    return tuple(reason for reason, score in pairs if score > 0)
