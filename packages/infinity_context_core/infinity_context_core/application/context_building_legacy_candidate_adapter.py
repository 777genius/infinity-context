"""Legacy query-vocabulary adapter for feature-owned candidate planning and fusion."""

from __future__ import annotations

from infinity_context_core.application.context_query_expansion import (
    QueryExpansion,
    QueryExpansionPlan,
)
from infinity_context_core.features.context_building.public import (
    CandidateQuery,
    CandidateQueryPolicy,
    CandidateRanking,
    fuse_ranked_candidate_keys,
    protected_candidate_head_keys,
    select_candidate_queries,
)

_MAX_DERIVED_RETRIEVAL_QUERIES = 8
_FUSION_RANK_CONSTANT = 60.0
_FUSION_MAX_RANK_PER_QUERY = 50
_FUSION_MULTI_EVIDENCE_MAX_RANK_PER_QUERY = 120
_HIGH_SIGNAL_DECOMPOSITION_REASONS = frozenset(
    {
        "decomposition_activity_duration",
        "decomposition_activity_participation",
        "decomposition_artifact_evidence",
        "decomposition_commonality",
        "decomposition_counterfactual_evidence",
        "decomposition_event_context",
        "decomposition_event_sequence",
        "decomposition_evidence_reason",
        "decomposition_frequency_recurrence",
        "decomposition_inventory_list",
        "decomposition_knowledge_update_current",
        "decomposition_knowledge_update_previous",
        "decomposition_lgbtq_pride_event",
        "decomposition_lgbtq_school_speech_event",
        "decomposition_lgbtq_support_group_event",
        "decomposition_relative_time",
        "decomposition_relocation_context",
        "decomposition_relocation_destination",
        "decomposition_relationship_status",
        "decomposition_source_evidence",
        "decomposition_state_transition",
        "decomposition_temporal_change",
    }
)
_HIGH_SIGNAL_EXPANSION_REASONS = frozenset(
    {
        "activity_aggregation_bridge",
        "activity_competition_evidence_bridge",
        "activity_visual_selfcare_bridge",
        "adoption_current_goal_bridge",
        "allergy_condition_inference_bridge",
        "animal_affinity_pet_store_bridge",
        "animal_care_instruction_bridge",
        "animal_diet_evidence_bridge",
        "animal_habitat_setup_bridge",
        "attribute_calm_resourcefulness_bridge",
        "attribute_family_support_bridge",
        "attribute_rescue_purpose_bridge",
        "attribute_service_helpfulness_bridge",
        "audio_transcript_evidence_bridge",
        "ally_support_bridge",
        "birdwatching_city_schedule_bridge",
        "book_reading_list_bridge",
        "beach_count_activity_bridge",
        "beach_or_mountains_inference_bridge",
        "business_commonality_bridge",
        "business_networking_event_bridge",
        "business_opening_timeline_bridge",
        "business_promotion_event_bridge",
        "business_store_promotion_event_bridge",
        "business_start_reason_bridge",
        "store_promotion_inventory_bridge",
        "camping_detail_bridge",
        "camping_location_bridge",
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
        "charity_brand_sponsorship_bridge",
        "charity_tournament_count_bridge",
        "children_preference_bridge",
        "community_membership_bridge",
        "community_membership_support_bridge",
        "commonality_interest_bridge",
        "conversation_transcript_evidence_bridge",
        "counseling_services_interest_bridge",
        "counseling_workshop_bridge",
        "current_state_temporal_bridge",
        "degree_policy_inference_bridge",
        "endorsement_gear_brand_bridge",
        "education_career_field_bridge",
        "event_participation_bridge",
        "event_participation_help_bridge",
        "exercise_activity_inventory_bridge",
        "family_activity_bridge",
        "food_recipe_detail_bridge",
        "food_recipe_recommendation_bridge",
        "family_hike_detail_bridge",
        "family_hike_activity_bridge",
        "family_museum_activity_bridge",
        "family_motivation_context_bridge",
        "family_painting_activity_bridge",
        "family_swimming_activity_bridge",
        "food_preference_bridge",
        "fitness_activity_bridge",
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
        "friends_team_inference_bridge",
        "generic_behavior_inference_bridge",
        "gaming_medium_bridge",
        "game_win_count_bridge",
        "general_temporal_event_bridge",
        "health_lifestyle_bridge",
        "hiking_trail_count_bridge",
        "hobby_interest_bridge",
        "instrument_play_bridge",
        "item_purchase_bridge",
        "letter_count_bridge",
        "lgbtq_community_participation_bridge",
        "lgbtq_pride_event_bridge",
        "lgbtq_school_event_bridge",
        "lgbtq_support_group_event_bridge",
        "meteor_shower_feeling_bridge",
        "national_park_inference_bridge",
        "military_service_willingness_bridge",
        "patriotic_service_inference_bridge",
        "pet_count_bridge",
        "pet_inventory_bridge",
        "political_inference_bridge",
        "pottery_type_bridge",
        "post_athletic_career_bridge",
        "public_office_service_bridge",
        "opinion_reaction_bridge",
        "research_topic_bridge",
        "relocation_willingness_inference_bridge",
        "relationship_duration_bridge",
        "relationship_origin_bridge",
        "relationship_status_bridge",
        "religious_inference_bridge",
        "screenplay_count_bridge",
        "safe_supportive_place_goal_bridge",
        "shelter_comfort_reason_bridge",
        "skill_teaching_inventory_bridge",
        "source_evidence_bridge",
        "speaker_turn_bridge",
        "state_residence_inference_bridge",
        "state_transition_bridge",
        "stale_state_temporal_bridge",
        "sports_activity_bridge",
        "support_career_motivation_bridge",
        "support_counterfactual_bridge",
        "support_network_bridge",
        "support_origin_bridge",
        "support_population_bridge",
        "support_role_fit_bridge",
        "symbol_importance_bridge",
        "temporal_event_detail_bridge",
        "transgender_conference_event_bridge",
        "transgender_poetry_event_bridge",
        "transgender_youth_center_event_bridge",
        "tournament_count_bridge",
        "travel_country_inventory_bridge",
        "video_transcript_evidence_bridge",
        "visual_text_evidence_bridge",
        "volunteer_career_inference_bridge",
        "volunteering_people_inventory_bridge",
        "volunteering_inventory_bridge",
        "yoga_delay_gaming_bridge",
    }
)
_BROAD_AGGREGATION_EXPANSION_REASONS = frozenset(
    {
        "event_participation_bridge",
    }
)
_MULTI_EVIDENCE_PROTECTED_HEAD_REASONS = frozenset(
    {
        "animal_affinity_pet_store_bridge",
        "animal_care_instruction_bridge",
        "animal_diet_evidence_bridge",
        "animal_habitat_setup_bridge",
        "board_game_inventory_bridge",
        "birdwatching_city_schedule_bridge",
        "business_networking_event_bridge",
        "business_opening_timeline_bridge",
        "business_promotion_event_bridge",
        "business_store_promotion_event_bridge",
        "customer_experience_bridge",
        "destress_activity_bridge",
        "family_activity_bridge",
        "grand_opening_support_bridge",
        "game_detail_bridge",
        "game_win_count_bridge",
        "inspiration_source_bridge",
        "item_purchase_bridge",
        "pet_adjustment_bridge",
        "planning_tool_use_bridge",
        "post_athletic_career_bridge",
        "recognition_award_bridge",
        "skill_teaching_inventory_bridge",
        "store_promotion_inventory_bridge",
        "symbol_importance_bridge",
        "themed_location_destination_anchor_bridge",
        "themed_location_destination_bridge",
        "food_recipe_recommendation_bridge",
        "fundraiser_event_inventory_bridge",
        "volunteering_people_inventory_bridge",
        "volunteering_inventory_bridge",
        "wellness_activity_effect_bridge",
    }
)
_PROTECTED_EXPANSION_HEAD_REASONS = frozenset(
    {
        "adverse_trip_bridge",
        "adoption_current_milestone_bridge",
        "age_birthday_bridge",
        "allergy_inventory_bridge",
        "animal_career_inference_bridge",
        "art_style_bridge",
        "artifact_inventory_bridge",
        "attribute_trait_inventory_bridge",
        "birthplace_origin_bridge",
        "book_suggestion_bridge",
        "career_intent_bridge",
        "cause_awareness_event_bridge",
        "cause_event_inventory_bridge",
        "childhood_possession_inventory_bridge",
        "children_books_inference_bridge",
        "children_count_event_bridge",
        "children_name_inventory_bridge",
        "choice_reason_bridge",
        "church_friend_activity_inventory_bridge",
        "classical_music_preference_bridge",
        "creative_work_submission_bridge",
        "creative_writing_inventory_bridge",
        "creative_writing_career_bridge",
        "travel_hobby_writing_bridge",
        "current_occupation_bridge",
        "current_recommendation_bridge",
        "current_residence_bridge",
        "deadline_commitment_bridge",
        "dog_activity_care_bridge",
        "entity_relation_inventory_bridge",
        "family_hardship_support_bridge",
        "family_origin_bridge",
        "favorite_preference_bridge",
        "followup_task_bridge",
        "future_plan_timing_bridge",
        "gotcha_failure_bridge",
        "hike_count_activity_bridge",
        "music_artist_answer_bridge",
        "music_artist_band_bridge",
        "negative_experience_support_bridge",
        "negative_preference_bridge",
        "preference_reason_bridge",
        "nickname_bridge",
        "organization_summary_bridge",
        "painting_inventory_bridge",
        "person_summary_bridge",
        "event_summary_bridge",
        "pet_acquisition_date_bridge",
        "personality_authenticity_bridge",
        "pet_memory_bridge",
        "personality_drive_bridge",
        "personality_thoughtfulness_bridge",
        "personality_trait_bridge",
        "project_summary_bridge",
        "post_event_activity_timing_bridge",
        "possession_gift_object_bridge",
        "recommendation_source_bridge",
        "relocation_destination_bridge",
        "relocation_origin_bridge",
        "repeated_test_attempt_bridge",
        "running_reason_bridge",
        "running_reason_question_bridge",
        "shared_painted_subject_bridge",
        "shoe_usage_bridge",
        "study_time_management_bridge",
        "trip_destination_bridge",
        "vehicle_interest_bridge",
        "vehicle_issue_bridge",
    }
)


def _bounded_derived_retrieval_queries(
    plan: QueryExpansionPlan | None,
    *,
    fallback: str,
    limit: int = _MAX_DERIVED_RETRIEVAL_QUERIES,
) -> tuple[QueryExpansion, ...]:
    raw_queries = tuple(
        plan.retrieval_queries
        if plan is not None
        else (QueryExpansion(query=fallback, reason="original_query"),)
    )
    raw_queries = _drop_ally_support_identity_noise(raw_queries)
    family_activity_mode = any(
        query.reason == "family_activity_bridge" for query in raw_queries
    )
    candidates = tuple(
        _candidate_query(
            query,
            family_activity_mode=family_activity_mode,
        )
        for query in raw_queries
    )
    fallback_query = _candidate_query(
        QueryExpansion(query=fallback, reason="original_query"),
        family_activity_mode=family_activity_mode,
    )
    return tuple(
        QueryExpansion(query=query.query, reason=query.key)
        for query in select_candidate_queries(
            candidates,
            fallback=fallback_query,
            limit=limit,
        )
    )


def _candidate_query(
    query: QueryExpansion,
    *,
    family_activity_mode: bool,
) -> CandidateQuery:
    return CandidateQuery(
        query=query.query,
        key=query.reason,
        selection_priority=_retrieval_query_selection_priority(
            query,
            family_activity_mode=family_activity_mode,
        ),
        policy=_query_policy_for_reason(query.reason),
    )


def _drop_ally_support_identity_noise(
    queries: tuple[QueryExpansion, ...],
) -> tuple[QueryExpansion, ...]:
    reasons = {query.reason for query in queries}
    if not {
        "ally_support_bridge",
        "decomposition_ally_support_evidence",
        "identity_bridge",
    }.issubset(reasons):
        return queries
    return tuple(query for query in queries if query.reason != "identity_bridge")


def _retrieval_query_selection_priority(
    query: QueryExpansion,
    *,
    family_activity_mode: bool = False,
) -> int:
    if query.reason == "original_query":
        return 0
    if family_activity_mode:
        if query.reason in {
            "activity_visual_selfcare_bridge",
            "family_activity_bridge",
            "family_museum_activity_bridge",
            "family_painting_activity_bridge",
            "family_swimming_activity_bridge",
        }:
            return 1
        if query.reason in _HIGH_SIGNAL_DECOMPOSITION_REASONS:
            return 2
    if query.reason in {
        "activity_visual_selfcare_bridge",
        "family_activity_bridge",
        "family_museum_activity_bridge",
        "family_painting_activity_bridge",
        "family_swimming_activity_bridge",
    }:
        return 1
    if query.reason == "exercise_activity_inventory_bridge":
        return 1
    if query.reason in _HIGH_SIGNAL_DECOMPOSITION_REASONS:
        return 1
    if query.reason == "decomposition_inference_support":
        return 4
    if query.reason in _BROAD_AGGREGATION_EXPANSION_REASONS:
        return 1
    if query.reason == "health_lifestyle_bridge":
        return 4
    if query.reason == "decomposition_ally_support_evidence":
        return 3
    if query.reason in {
        "activity_aggregation_bridge",
        "family_motivation_context_bridge",
        "hobby_interest_bridge",
    }:
        return 3
    if query.reason in _HIGH_SIGNAL_EXPANSION_REASONS:
        return 2
    if query.reason.startswith("decomposition_"):
        return 4
    return 3


def _retrieval_query_rank_key(index: int, query: QueryExpansion) -> str:
    return f"{index}:{query.reason}"


def _protected_query_head_keys(rankings: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return protected_candidate_head_keys(_candidate_rankings(rankings))


def _fused_ranked_keys(
    rankings: dict[str, tuple[str, ...]],
    *,
    limit: int,
) -> tuple[str, ...]:
    return fuse_ranked_candidate_keys(
        _candidate_rankings(rankings),
        limit=limit,
        rank_constant=_FUSION_RANK_CONSTANT,
    )


def _candidate_rankings(
    rankings: dict[str, tuple[str, ...]],
) -> tuple[CandidateRanking, ...]:
    return tuple(
        CandidateRanking(
            ranked_keys=ranked_keys,
            policy=_query_policy_for_reason(_reason_from_ranking_key(ranking_key)),
        )
        for ranking_key, ranked_keys in rankings.items()
    )


def _reason_from_ranking_key(ranking_key: str) -> str:
    _, _, reason = ranking_key.partition(":")
    return reason


def _query_policy_for_reason(reason: str) -> CandidateQueryPolicy:
    return CandidateQueryPolicy(
        weight=_retrieval_query_fusion_weight_for_reason(reason),
        max_rank=_fusion_max_rank_for_reason(reason),
        protected_head_count=_protected_query_head_limit_for_reason(reason),
    )


def _protected_query_head_limit_for_reason(reason: str) -> int:
    if reason == "food_recipe_recommendation_bridge":
        return 3
    if reason == "store_promotion_inventory_bridge":
        return 4
    if reason == "business_networking_event_bridge":
        return 2
    if reason == "business_promotion_event_bridge":
        return 3
    if reason == "business_store_promotion_event_bridge":
        return 2
    if reason == "business_opening_timeline_bridge":
        return 2
    if reason in _MULTI_EVIDENCE_PROTECTED_HEAD_REASONS:
        return 2
    if _protect_query_head_for_reason(reason):
        return 1
    return 0


def _protect_query_head_for_reason(reason: str) -> bool:
    return (
        reason in _HIGH_SIGNAL_EXPANSION_REASONS
        or reason in _PROTECTED_EXPANSION_HEAD_REASONS
        or reason in _BROAD_AGGREGATION_EXPANSION_REASONS
        or reason
        in {
            "decomposition_activity_participation",
            "decomposition_activity_duration",
            "decomposition_artifact_evidence",
            "decomposition_commonality",
            "decomposition_counterfactual_evidence",
            "decomposition_frequency_recurrence",
            "decomposition_inventory_list",
            "decomposition_knowledge_update_current",
            "decomposition_knowledge_update_previous",
            "decomposition_lgbtq_pride_event",
            "decomposition_lgbtq_school_speech_event",
            "decomposition_lgbtq_support_group_event",
            "decomposition_relationship_status",
            "decomposition_source_evidence",
            "decomposition_state_transition",
        }
    )


def _fusion_max_rank_for_reason(reason: str) -> int:
    if (
        reason in _MULTI_EVIDENCE_PROTECTED_HEAD_REASONS
        or reason == "decomposition_relationship_status"
    ):
        return _FUSION_MULTI_EVIDENCE_MAX_RANK_PER_QUERY
    return _FUSION_MAX_RANK_PER_QUERY


def _fusion_max_rank_for_query(ranking_key: str) -> int:
    return _fusion_max_rank_for_reason(_reason_from_ranking_key(ranking_key))


def _retrieval_query_fusion_weight_for_reason(reason: str) -> float:
    if reason == "original_query":
        return 1.5
    if reason in _HIGH_SIGNAL_EXPANSION_REASONS:
        return 1.12
    if reason in _HIGH_SIGNAL_DECOMPOSITION_REASONS:
        return 1.0
    if reason.startswith("decomposition_"):
        return 0.7
    return 1.0


def _retrieval_query_fusion_weight(ranking_key: str) -> float:
    return _retrieval_query_fusion_weight_for_reason(
        _reason_from_ranking_key(ranking_key)
    )
