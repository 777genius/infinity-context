"""Keyword chunk scoring and source boost policy."""

from __future__ import annotations

from infinity_context_core.application.context_ranking_reason_policy import (
    ACTIVITY_OBSERVATION_SOURCE_REASONS,
    CONTEXT_ITEM_REASON_PRIORITY,
    DERIVED_SUMMARY_SOURCE_MIN_DISTINCTIVE_HITS,
    DERIVED_SUMMARY_SOURCE_REASONS,
    KEYWORD_EXPANSION_REASON_BOOSTS,
    KEYWORD_EXPANSION_SCORE_CAPS,
)
from infinity_context_core.application.context_relevance import QueryRelevance

_DERIVED_SUMMARY_SOURCE_BOOST = 0.06
_DERIVED_SUMMARY_SOURCE_CAP = 0.985
_ACTIVITY_DERIVED_SUMMARY_SOURCE_BOOST = 0.09
_ACTIVITY_DERIVED_SUMMARY_SOURCE_CAP = 0.99
_ACTIVITY_DERIVED_SUMMARY_STRONG_HITS = 10
_DERIVED_SUMMARY_SOURCE_SUFFIXES = (":observation", ":summary", ":events")
_ACTIVITY_EVIDENCE_SOURCE_SUFFIXES = (":turn", ":observation", ":summary", ":events")
_ATTRIBUTE_EVIDENCE_SOURCE_SUFFIXES = (":turn", ":observation", ":events")
_PRECISE_EVIDENCE_SOURCE_REASONS = frozenset(
    {
        "adoption_current_goal_bridge",
        "adoption_current_milestone_bridge",
        "allergy_condition_inference_bridge",
        "allergy_inventory_bridge",
        "business_networking_event_bridge",
        "business_opening_timeline_bridge",
        "business_promotion_event_bridge",
        "business_store_promotion_event_bridge",
        "business_start_reason_bridge",
        "book_reading_list_bridge",
        "charity_brand_sponsorship_bridge",
        "charity_tournament_count_bridge",
        "children_count_event_bridge",
        "choice_reason_bridge",
        "business_commonality_bridge",
        "store_promotion_inventory_bridge",
        "degree_policy_inference_bridge",
        "exercise_activity_inventory_bridge",
        "endorsement_gear_brand_bridge",
        "gaming_medium_bridge",
        "hiking_trail_count_bridge",
        "hobby_interest_bridge",
        "instrument_play_bridge",
        "letter_count_bridge",
        "meteor_shower_feeling_bridge",
        "national_park_inference_bridge",
        "patriotic_service_inference_bridge",
        "pet_count_bridge",
        "pet_inventory_bridge",
        "personality_authenticity_bridge",
        "personality_drive_bridge",
        "personality_thoughtfulness_bridge",
        "personality_trait_bridge",
        "post_athletic_career_bridge",
        "running_reason_bridge",
        "running_reason_question_bridge",
        "screenplay_count_bridge",
        "shelter_comfort_reason_bridge",
        "state_residence_inference_bridge",
        "symbol_importance_bridge",
        "temporal_event_detail_bridge",
        "future_plan_timing_bridge",
        "tournament_count_bridge",
        "volunteer_career_inference_bridge",
        "yoga_delay_gaming_bridge",
    }
)
_TURN_ONLY_EVIDENCE_SOURCE_REASONS = frozenset(
    {
        "personality_authenticity_bridge",
        "personality_drive_bridge",
        "personality_thoughtfulness_bridge",
        "personality_trait_bridge",
        "national_park_inference_bridge",
        "state_residence_inference_bridge",
    }
)
_ACTIVITY_OBSERVATION_MIN_DISTINCTIVE_HITS = 8


def keyword_chunk_score(
    relevance: QueryRelevance,
    *,
    query_expansion_reason: str,
) -> float:
    distinctive_boost = min(0.028, relevance.distinctive_term_hits * 0.007)
    phrase_boost = min(0.018, relevance.phrase_bigram_hits * 0.006)
    frequency_boost = min(0.014, relevance.capped_frequency_hits * 0.0015)
    expansion_boost = 0.004 if query_expansion_reason != "original_query" else 0.0
    reason_boost = KEYWORD_EXPANSION_REASON_BOOSTS.get(query_expansion_reason, 0.0)
    score_cap = KEYWORD_EXPANSION_SCORE_CAPS.get(query_expansion_reason, 0.93)
    return min(
        score_cap,
        round(
            0.75
            + relevance.score_boost
            + distinctive_boost
            + phrase_boost
            + frequency_boost
            + expansion_boost
            + reason_boost,
            4,
        ),
    )


def keyword_chunk_source_score_boost(
    relevance: QueryRelevance,
    *,
    query_expansion_reason: str,
    source_external_id: str,
) -> float:
    """Prefer compact derived observations/summaries for broad aggregation answers."""

    if query_expansion_reason not in DERIVED_SUMMARY_SOURCE_REASONS:
        return 0.0
    normalized_source_id = source_external_id.casefold()
    if query_expansion_reason in ACTIVITY_OBSERVATION_SOURCE_REASONS:
        allowed_suffixes = _ACTIVITY_EVIDENCE_SOURCE_SUFFIXES
    elif query_expansion_reason in _TURN_ONLY_EVIDENCE_SOURCE_REASONS:
        allowed_suffixes = (":turn",)
    elif (
        query_expansion_reason.startswith("attribute_")
        or query_expansion_reason in _PRECISE_EVIDENCE_SOURCE_REASONS
    ):
        allowed_suffixes = _ATTRIBUTE_EVIDENCE_SOURCE_SUFFIXES
    else:
        allowed_suffixes = _DERIVED_SUMMARY_SOURCE_SUFFIXES
    if not normalized_source_id.endswith(allowed_suffixes):
        return 0.0
    min_hits = DERIVED_SUMMARY_SOURCE_MIN_DISTINCTIVE_HITS.get(
        query_expansion_reason,
        _ACTIVITY_OBSERVATION_MIN_DISTINCTIVE_HITS,
    )
    if relevance.distinctive_term_hits < min_hits:
        return 0.0
    if (
        query_expansion_reason in ACTIVITY_OBSERVATION_SOURCE_REASONS
        and relevance.distinctive_term_hits >= _ACTIVITY_DERIVED_SUMMARY_STRONG_HITS
    ):
        return _ACTIVITY_DERIVED_SUMMARY_SOURCE_BOOST
    return _DERIVED_SUMMARY_SOURCE_BOOST


def query_expansion_reason_priority(reason: str) -> int:
    return CONTEXT_ITEM_REASON_PRIORITY.get(reason, 0)


def apply_keyword_chunk_source_score_boost(
    score: float,
    relevance: QueryRelevance,
    *,
    query_expansion_reason: str,
    source_external_id: str,
) -> tuple[float, float]:
    boost = keyword_chunk_source_score_boost(
        relevance,
        query_expansion_reason=query_expansion_reason,
        source_external_id=source_external_id,
    )
    if boost <= 0:
        return score, 0.0
    cap = (
        _ACTIVITY_DERIVED_SUMMARY_SOURCE_CAP
        if (
            query_expansion_reason in ACTIVITY_OBSERVATION_SOURCE_REASONS
            and boost >= _ACTIVITY_DERIVED_SUMMARY_SOURCE_BOOST
        )
        else _DERIVED_SUMMARY_SOURCE_CAP
    )
    return (
        min(cap, round(score + boost, 4)),
        boost,
    )
