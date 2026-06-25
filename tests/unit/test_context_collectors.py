import asyncio
from datetime import UTC, datetime

from infinity_context_core.application.context_collectors import (
    _HIGH_SIGNAL_EXPANSION_REASONS,
    _PROTECTED_EXPANSION_HEAD_REASONS,
    _bounded_derived_retrieval_queries,
    _canonical_fact_candidate_limit,
    _fused_ranked_keys,
    _keyword_candidate_pool_limit,
    _keyword_query_search_limit,
    _keyword_search_chunks,
    _protected_query_head_keys,
    _rank_facts_for_query,
)
from infinity_context_core.application.context_query_expansion import (
    QueryExpansion,
    QueryExpansionPlan,
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    KEYWORD_EXPANSION_SCORE_CAPS,
)
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryFact,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)


def test_rank_facts_for_query_prefers_specific_term_coverage_over_input_order() -> None:
    decoy = _fact(
        "fact_decoy",
        "QUALITY_DECOY_WRONG_MODEL: local canary uses GPT-3.5 legacy fallback.",
    )
    current = _fact(
        "fact_current",
        "QUALITY_FACT_MODEL_CURRENT: local interview canary uses GPT-5.4 mini.",
    )

    ranked = _rank_facts_for_query(
        (decoy, current),
        query_text="GPT-5.4 mini local interview canary current model",
        limit=1,
    )

    assert ranked == (current,)


def test_canonical_fact_candidate_limit_overfetches_before_relevance_ranking() -> None:
    assert _canonical_fact_candidate_limit(0) == 0
    assert _canonical_fact_candidate_limit(1) == 9
    assert _canonical_fact_candidate_limit(30) == 100


def test_keyword_candidate_pool_overfetches_across_bounded_query_families() -> None:
    assert _keyword_candidate_pool_limit(0) == 0
    assert _keyword_candidate_pool_limit(50) == 300
    assert _keyword_candidate_pool_limit(500) == 360


def test_keyword_query_search_limit_bounds_large_requests_per_variant() -> None:
    assert _keyword_query_search_limit(total_limit=0, candidate_limit=0) == 0
    assert _keyword_query_search_limit(total_limit=4, candidate_limit=24) == 20
    assert _keyword_query_search_limit(total_limit=50, candidate_limit=300) == 150
    assert _keyword_query_search_limit(total_limit=500, candidate_limit=360) == 180


def test_high_confidence_policy_bridges_have_retrieval_head_protection() -> None:
    deliberately_unprotected = {
        "identity_bridge",
    }
    protected_reasons = _HIGH_SIGNAL_EXPANSION_REASONS | _PROTECTED_EXPANSION_HEAD_REASONS
    unprotected = {
        reason
        for reason, score_cap in KEYWORD_EXPANSION_SCORE_CAPS.items()
        if reason.endswith("_bridge")
        and score_cap >= 0.96
        and reason not in protected_reasons
        and reason not in deliberately_unprotected
    }

    assert unprotected == set()


def test_protected_query_head_keys_keep_specialized_evidence_heads() -> None:
    rankings = {
        "0:original_query": ("generic_a", "generic_b"),
        "1:decomposition_event_context": ("event_noise",),
        "2:family_swimming_activity_bridge": ("d1_swimming", "generic_a"),
        "3:family_hike_activity_bridge": ("d16_hike", "generic_b"),
        "4:symbol_importance_bridge": ("d14_symbol", "generic_c"),
        "5:meteor_shower_feeling_bridge": ("d10_feeling", "generic_d"),
        "6:adoption_current_goal_bridge": ("d19_adoption", "generic_e"),
    }

    assert _protected_query_head_keys(rankings) == (
        "d1_swimming",
        "d16_hike",
        "d14_symbol",
        "d10_feeling",
        "d19_adoption",
    )


def test_protected_query_head_keys_keep_inventory_and_friend_place_heads() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:decomposition_inventory_list": ("d13_spain", "generic_a"),
        "2:travel_country_inventory_bridge": ("d8_england", "d13_spain"),
        "3:friend_place_shelter_inventory_bridge": ("d2_shelter",),
        "4:friend_place_gym_inventory_bridge": ("d19_gym",),
        "5:friend_place_church_inventory_bridge": ("d14_church",),
    }

    assert _protected_query_head_keys(rankings) == (
        "d13_spain",
        "d8_england",
        "d2_shelter",
        "d19_gym",
        "d14_church",
    )


def test_protected_query_head_keys_keep_multiple_animal_evidence_facets() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:animal_care_instruction_bridge": (
            "care_clean_feed_light",
            "care_followup",
            "care_noise",
        ),
        "2:animal_affinity_pet_store_bridge": (
            "affinity_pet_store",
            "affinity_followup",
        ),
        "3:generic_behavior_inference_bridge": (
            "behavior_exact",
            "behavior_followup",
        ),
    }

    assert _protected_query_head_keys(rankings) == (
        "care_clean_feed_light",
        "care_followup",
        "affinity_pet_store",
        "affinity_followup",
        "behavior_exact",
    )


def test_protected_query_head_keys_keep_commonality_heads() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:business_commonality_bridge": ("job_business_match", "generic_b"),
        "2:commonality_interest_bridge": ("shared_hobby_match", "generic_c"),
        "3:decomposition_commonality": ("shared_clause_match", "generic_d"),
    }

    assert _protected_query_head_keys(rankings) == (
        "job_business_match",
        "shared_hobby_match",
        "shared_clause_match",
    )


def test_protected_query_head_keys_keep_personality_trait_heads() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:personality_trait_bridge": ("trait_match", "generic_b"),
        "2:personality_thoughtfulness_bridge": ("thoughtful_match", "generic_c"),
        "3:personality_authenticity_bridge": ("authentic_match", "generic_d"),
        "4:personality_drive_bridge": ("drive_match", "generic_e"),
        "5:attribute_trait_inventory_bridge": ("attribute_match", "generic_f"),
        "6:attribute_description_bridge": ("generic_attribute",),
    }

    assert _protected_query_head_keys(rankings) == (
        "trait_match",
        "thoughtful_match",
        "authentic_match",
        "drive_match",
        "attribute_match",
    )


def test_protected_query_head_keys_keep_recommendation_and_negative_heads() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:adverse_trip_bridge": ("adverse_trip_match", "generic_b"),
        "2:book_suggestion_bridge": ("book_suggestion_match", "generic_c"),
        "3:children_books_inference_bridge": ("children_books_match", "generic_d"),
        "4:current_recommendation_bridge": ("current_recommendation_match", "generic_e"),
        "5:recommendation_source_bridge": ("recommendation_source_match", "generic_f"),
        "6:negative_experience_support_bridge": ("negative_support_match", "generic_g"),
        "7:negative_preference_bridge": ("negative_preference_match", "generic_h"),
    }

    assert _protected_query_head_keys(rankings) == (
        "adverse_trip_match",
        "book_suggestion_match",
        "children_books_match",
        "current_recommendation_match",
        "recommendation_source_match",
        "negative_support_match",
        "negative_preference_match",
    )


def test_protected_query_head_keys_keep_bio_location_heads() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:age_birthday_bridge": ("age_match", "generic_b"),
        "2:birthplace_origin_bridge": ("birthplace_match", "generic_c"),
        "3:current_residence_bridge": ("residence_match", "generic_d"),
        "4:current_occupation_bridge": ("occupation_match", "generic_e"),
        "5:family_origin_bridge": ("family_origin_match", "generic_f"),
        "6:relocation_origin_bridge": ("move_from_match", "generic_g"),
        "7:relocation_destination_bridge": ("move_to_match", "generic_h"),
        "8:identity_bridge": ("identity_generic",),
    }

    assert _protected_query_head_keys(rankings) == (
        "age_match",
        "birthplace_match",
        "residence_match",
        "occupation_match",
        "family_origin_match",
        "move_from_match",
        "move_to_match",
    )


def test_protected_query_head_keys_keep_inventory_object_heads() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:allergy_inventory_bridge": ("allergy_match", "generic_b"),
        "2:children_count_event_bridge": ("children_match", "generic_c"),
        "3:hike_count_activity_bridge": ("hike_count_match", "generic_d"),
        "4:music_artist_answer_bridge": ("artist_match", "generic_e"),
        "5:music_artist_band_bridge": ("band_match", "generic_f"),
        "6:painting_inventory_bridge": ("painting_match", "generic_g"),
        "7:possession_gift_object_bridge": ("gift_match", "generic_h"),
        "8:shared_painted_subject_bridge": ("shared_subject_match", "generic_i"),
        "9:shoe_usage_bridge": ("shoe_match", "generic_j"),
        "10:trip_destination_bridge": ("trip_match", "generic_k"),
    }

    assert _protected_query_head_keys(rankings) == (
        "allergy_match",
        "children_match",
        "hike_count_match",
        "artist_match",
        "band_match",
        "painting_match",
        "gift_match",
        "shared_subject_match",
        "shoe_match",
        "trip_match",
    )


def test_protected_query_head_keys_keep_running_reason_heads() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:running_reason_bridge": ("running_reason_match", "generic_b"),
        "2:running_reason_question_bridge": ("running_question_match", "generic_c"),
    }

    assert _protected_query_head_keys(rankings) == (
        "running_reason_match",
        "running_question_match",
    )


def test_protected_query_head_keys_keep_classical_music_head() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:classical_music_preference_bridge": ("classical_music_match", "generic_b"),
    }

    assert _protected_query_head_keys(rankings) == ("classical_music_match",)


def test_protected_query_head_keys_keep_task_failure_and_inference_heads() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:adoption_current_milestone_bridge": ("adoption_match", "generic_b"),
        "2:animal_career_inference_bridge": ("animal_career_match", "generic_c"),
        "3:art_style_bridge": ("art_style_match", "generic_d"),
        "4:career_intent_bridge": ("career_intent_match", "generic_e"),
        "5:deadline_commitment_bridge": ("deadline_match", "generic_f"),
        "6:followup_task_bridge": ("followup_match", "generic_g"),
        "7:gotcha_failure_bridge": ("failure_match", "generic_h"),
        "8:post_event_activity_timing_bridge": ("post_event_match", "generic_i"),
    }

    assert _protected_query_head_keys(rankings) == (
        "adoption_match",
        "animal_career_match",
        "art_style_match",
        "career_intent_match",
        "deadline_match",
        "followup_match",
        "failure_match",
        "post_event_match",
    )


def test_protected_query_head_keys_keep_friend_team_inference_head() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:friends_team_inference_bridge": ("team_friend_match", "generic_b"),
        "2:degree_policy_inference_bridge": ("degree_policy_match", "generic_c"),
        "3:counseling_workshop_bridge": ("workshop_match", "generic_d"),
        "4:education_career_field_bridge": ("education_field_match", "generic_e"),
        "5:political_inference_bridge": ("political_values_match", "generic_f"),
        "6:allergy_condition_inference_bridge": ("allergy_match", "generic_g"),
        "7:beach_or_mountains_inference_bridge": ("outdoor_geo_match", "generic_h"),
        "8:support_counterfactual_bridge": ("support_counterfactual_match", "generic_i"),
    }

    assert _protected_query_head_keys(rankings) == (
        "team_friend_match",
        "degree_policy_match",
        "workshop_match",
        "education_field_match",
        "political_values_match",
        "allergy_match",
        "outdoor_geo_match",
        "support_counterfactual_match",
    )


def test_protected_query_head_keys_keep_temporal_state_heads() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:decomposition_knowledge_update_current": ("current_decomp", "generic_b"),
        "2:current_state_temporal_bridge": ("current_bridge", "generic_c"),
        "3:decomposition_knowledge_update_previous": ("stale_decomp", "generic_d"),
        "4:stale_state_temporal_bridge": ("stale_bridge", "generic_e"),
        "5:decomposition_state_transition": ("transition_decomp", "generic_f"),
        "6:state_transition_bridge": ("transition_bridge", "generic_g"),
        "7:decomposition_counterfactual_evidence": (
            "counterfactual_decomp",
            "generic_h",
        ),
    }

    assert _protected_query_head_keys(rankings) == (
        "current_decomp",
        "current_bridge",
        "stale_decomp",
        "stale_bridge",
        "transition_decomp",
        "transition_bridge",
        "counterfactual_decomp",
    )


def test_protected_query_head_keys_keep_duration_and_frequency_heads() -> None:
    rankings = {
        "0:original_query": ("generic_a",),
        "1:decomposition_activity_duration": ("d4_duration", "generic_a"),
        "2:decomposition_frequency_recurrence": ("d9_frequency", "generic_b"),
    }

    assert _protected_query_head_keys(rankings) == ("d4_duration", "d9_frequency")


def test_bounded_retrieval_queries_prioritize_specific_bridges_over_decomposition() -> None:
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query="clause", reason="decomposition_clause"),
            QueryExpansion(query="support", reason="decomposition_inference_support"),
            QueryExpansion(query="aggregate", reason="decomposition_attribute_aggregation"),
        ),
        expansions=(
            QueryExpansion(query="traits", reason="personality_trait_bridge"),
            QueryExpansion(query="thoughtful", reason="personality_thoughtfulness_bridge"),
            QueryExpansion(query="authentic", reason="personality_authenticity_bridge"),
            QueryExpansion(query="drive", reason="personality_drive_bridge"),
        ),
    )

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=6)

    assert [query.reason for query in selected] == [
        "original_query",
        "personality_trait_bridge",
        "personality_thoughtfulness_bridge",
        "personality_authenticity_bridge",
        "personality_drive_bridge",
        "decomposition_clause",
    ]


def test_bounded_retrieval_queries_select_direct_negative_preference_bridge() -> None:
    plan = build_query_expansion_plan("What does Morgan dislike?")

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=4)

    assert [query.reason for query in selected] == [
        "original_query",
        "negative_preference_bridge",
    ]


def test_bounded_retrieval_queries_select_recommendation_source_bridge() -> None:
    plan = build_query_expansion_plan("What recommendation did Alex make recently?")

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=4)

    assert [query.reason for query in selected] == [
        "original_query",
        "recommendation_source_bridge",
        "decomposition_action_role",
    ]


def test_bounded_retrieval_queries_keep_exercise_inventory_for_activity_query() -> None:
    plan = build_query_expansion_plan("What exercise activities does Alex do?")

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=6)

    assert [query.reason for query in selected] == [
        "original_query",
        "decomposition_event_context",
        "decomposition_activity_participation",
        "activity_visual_selfcare_bridge",
        "exercise_activity_inventory_bridge",
        "hobby_interest_bridge",
    ]


def test_bounded_retrieval_queries_select_running_reason_question_bridge() -> None:
    plan = build_query_expansion_plan("What was Alex running for?")

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=4)

    assert [query.reason for query in selected] == [
        "original_query",
        "running_reason_question_bridge",
        "running_reason_bridge",
    ]


def test_bounded_retrieval_queries_select_vivaldi_preference_bridge() -> None:
    plan = build_query_expansion_plan("Would Melanie likely enjoy Vivaldi?")

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=4)

    assert [query.reason for query in selected] == [
        "original_query",
        "classical_music_preference_bridge",
        "decomposition_inference_support",
    ]


def test_bounded_retrieval_queries_select_direct_career_and_art_bridges() -> None:
    career = build_query_expansion_plan("What career does Alex want?")
    art = build_query_expansion_plan("What art style does Alex like?")
    animal = build_query_expansion_plan("What animal career would Alex like?")

    assert [query.reason for query in _bounded_derived_retrieval_queries(
        career,
        fallback="fallback",
        limit=4,
    )] == [
        "original_query",
        "career_intent_bridge",
    ]
    assert [query.reason for query in _bounded_derived_retrieval_queries(
        art,
        fallback="fallback",
        limit=4,
    )] == [
        "original_query",
        "art_style_bridge",
    ]
    assert [query.reason for query in _bounded_derived_retrieval_queries(
        animal,
        fallback="fallback",
        limit=4,
    )] == [
        "original_query",
        "animal_career_inference_bridge",
        "decomposition_inference_support",
        "decomposition_current_preference_or_goal",
    ]


def test_bounded_retrieval_queries_select_origin_from_bridge() -> None:
    plan = build_query_expansion_plan("Where is Alex from?")

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=4)

    assert [query.reason for query in selected] == [
        "original_query",
        "decomposition_relocation_context",
        "birthplace_origin_bridge",
    ]


def test_bounded_retrieval_queries_select_person_summary_bridge() -> None:
    plan = build_query_expansion_plan("Who is Alex?")

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=4)

    assert [query.reason for query in selected] == [
        "original_query",
        "person_summary_bridge",
    ]


def test_bounded_retrieval_queries_keep_high_signal_decomposition() -> None:
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query="relative", reason="decomposition_relative_time"),
            QueryExpansion(query="clause", reason="decomposition_clause"),
        ),
        expansions=(
            QueryExpansion(query="bridge-one", reason="source_evidence_bridge"),
            QueryExpansion(query="bridge-two", reason="visual_text_evidence_bridge"),
            QueryExpansion(query="bridge-three", reason="audio_transcript_evidence_bridge"),
            QueryExpansion(query="bridge-four", reason="video_transcript_evidence_bridge"),
        ),
    )

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=4)

    assert [query.reason for query in selected] == [
        "original_query",
        "decomposition_relative_time",
        "source_evidence_bridge",
        "visual_text_evidence_bridge",
    ]


def test_bounded_retrieval_queries_keep_duration_and_frequency_decomposition() -> None:
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query="generic clause", reason="decomposition_clause"),
            QueryExpansion(query="duration evidence", reason="decomposition_activity_duration"),
            QueryExpansion(query="frequency evidence", reason="decomposition_frequency_recurrence"),
        ),
        expansions=(
            QueryExpansion(query="visual evidence", reason="visual_text_evidence_bridge"),
            QueryExpansion(query="audio evidence", reason="audio_transcript_evidence_bridge"),
        ),
    )

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=3)

    assert [query.reason for query in selected] == [
        "original_query",
        "decomposition_activity_duration",
        "decomposition_frequency_recurrence",
    ]


def test_bounded_retrieval_queries_keep_activity_and_children_preference_bridges() -> None:
    broad_family_activity = _bounded_derived_retrieval_queries(
        build_query_expansion_plan("What activities has Melanie done with her family?"),
        fallback="fallback",
    )
    activity = _bounded_derived_retrieval_queries(
        build_query_expansion_plan("What activities does Melanie partake in?"),
        fallback="fallback",
        limit=6,
    )
    family_activity = _bounded_derived_retrieval_queries(
        build_query_expansion_plan("What activities has Melanie done with her family?"),
        fallback="fallback",
        limit=6,
    )
    family_hike = _bounded_derived_retrieval_queries(
        build_query_expansion_plan("What does Melanie do with her family on hikes?"),
        fallback="fallback",
        limit=4,
    )
    kids_like = _bounded_derived_retrieval_queries(
        build_query_expansion_plan("What do Melanie's kids like?"),
        fallback="fallback",
        limit=3,
    )

    assert "decomposition_activity_participation" in {
        query.reason for query in activity
    }
    assert "activity_aggregation_bridge" in {query.reason for query in activity}
    assert "family_activity_bridge" in {query.reason for query in family_activity}
    assert "family_painting_activity_bridge" in {
        query.reason for query in family_activity
    }
    assert "activity_visual_selfcare_bridge" in {
        query.reason for query in broad_family_activity
    }
    assert "family_hike_detail_bridge" in {query.reason for query in family_hike}
    assert "children_preference_bridge" in {query.reason for query in kids_like}


def test_bounded_retrieval_queries_keep_inventory_friend_place_slots() -> None:
    travel = _bounded_derived_retrieval_queries(
        build_query_expansion_plan("What European countries has Maria been to?"),
        fallback="fallback",
        limit=3,
    )
    friends = _bounded_derived_retrieval_queries(
        build_query_expansion_plan("Where has Maria made friends?"),
        fallback="fallback",
        limit=6,
    )

    assert [query.reason for query in travel] == [
        "original_query",
        "decomposition_inventory_list",
        "travel_country_inventory_bridge",
    ]
    assert {
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
    }.issubset({query.reason for query in friends})


def test_bounded_retrieval_queries_keep_cause_inventory_bridges() -> None:
    selected = _bounded_derived_retrieval_queries(
        build_query_expansion_plan("What causes does John feel passionate about supporting?"),
        fallback="fallback",
        limit=4,
    )

    assert [query.reason for query in selected] == [
        "original_query",
        "decomposition_inventory_list",
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
    ]


def test_bounded_retrieval_queries_prioritize_high_signal_evidence_bridges() -> None:
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query="relative", reason="decomposition_relative_time"),
            QueryExpansion(query="clause", reason="decomposition_clause"),
        ),
        expansions=(
            QueryExpansion(query="personality", reason="personality_trait_bridge"),
            QueryExpansion(
                query="conversation",
                reason="conversation_transcript_evidence_bridge",
            ),
            QueryExpansion(query="source", reason="source_evidence_bridge"),
        ),
    )

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=5)

    assert [query.reason for query in selected] == [
        "original_query",
        "decomposition_relative_time",
        "conversation_transcript_evidence_bridge",
        "source_evidence_bridge",
        "personality_trait_bridge",
    ]


def test_bounded_retrieval_queries_prioritize_support_causality_bridges() -> None:
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query="generic clause", reason="decomposition_clause"),
        ),
        expansions=(
            QueryExpansion(query="career", reason="career_intent_bridge"),
            QueryExpansion(
                query="support made counseling matter",
                reason="support_career_motivation_bridge",
            ),
            QueryExpansion(query="blessed support journey", reason="support_origin_bridge"),
            QueryExpansion(query="safe mentor support", reason="support_role_fit_bridge"),
        ),
    )

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=4)

    assert [query.reason for query in selected] == [
        "original_query",
        "support_career_motivation_bridge",
        "support_origin_bridge",
        "support_role_fit_bridge",
    ]


def test_bounded_retrieval_queries_prioritize_animal_career_bridge() -> None:
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query="after event", reason="decomposition_event_sequence"),
            QueryExpansion(query="clause", reason="decomposition_clause"),
        ),
        expansions=(
            QueryExpansion(query="career", reason="career_intent_bridge"),
            QueryExpansion(query="animal care", reason="animal_career_inference_bridge"),
            QueryExpansion(
                query="care instructions",
                reason="animal_care_instruction_bridge",
            ),
            QueryExpansion(
                query="diet vegetables insects",
                reason="animal_diet_evidence_bridge",
            ),
            QueryExpansion(
                query="new tank habitat",
                reason="animal_habitat_setup_bridge",
            ),
            QueryExpansion(
                query="pet store joy peace",
                reason="animal_affinity_pet_store_bridge",
            ),
            QueryExpansion(query="after", reason="after_event_temporal_bridge"),
        ),
    )

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=6)

    assert [query.reason for query in selected] == [
        "original_query",
        "decomposition_event_sequence",
        "animal_care_instruction_bridge",
        "animal_diet_evidence_bridge",
        "animal_habitat_setup_bridge",
        "animal_affinity_pet_store_bridge",
    ]


def test_bounded_retrieval_queries_prioritize_camping_detail_bridge() -> None:
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query="when", reason="decomposition_temporal_answer"),
            QueryExpansion(query="clause", reason="decomposition_clause"),
        ),
        expansions=(
            QueryExpansion(query="camping", reason="camping_detail_bridge"),
            QueryExpansion(query="after", reason="after_event_temporal_bridge"),
            QueryExpansion(query="source", reason="source_evidence_bridge"),
        ),
    )

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=5)

    assert [query.reason for query in selected] == [
        "original_query",
        "camping_detail_bridge",
        "source_evidence_bridge",
        "after_event_temporal_bridge",
        "decomposition_temporal_answer",
    ]


def test_bounded_retrieval_queries_keep_attribute_facets_before_generic_noise() -> None:
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query="aggregate", reason="decomposition_attribute_aggregation"),
            QueryExpansion(query="clause", reason="decomposition_clause"),
        ),
        expansions=(
            QueryExpansion(query="generic", reason="attribute_description_bridge"),
            QueryExpansion(query="family", reason="attribute_family_support_bridge"),
            QueryExpansion(query="calm", reason="attribute_calm_resourcefulness_bridge"),
            QueryExpansion(query="service", reason="attribute_service_helpfulness_bridge"),
            QueryExpansion(query="rescue", reason="attribute_rescue_purpose_bridge"),
            QueryExpansion(query="noise", reason="personality_trait_bridge"),
        ),
    )

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=6)

    assert [query.reason for query in selected] == [
        "original_query",
        "attribute_family_support_bridge",
        "attribute_calm_resourcefulness_bridge",
        "attribute_service_helpfulness_bridge",
        "attribute_rescue_purpose_bridge",
        "attribute_description_bridge",
    ]


def test_bounded_retrieval_queries_keep_specialized_event_bridges() -> None:
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query="event context", reason="decomposition_event_context"),
            QueryExpansion(query="pride slot", reason="decomposition_lgbtq_pride_event"),
            QueryExpansion(query="support slot", reason="decomposition_lgbtq_support_group_event"),
            QueryExpansion(query="school slot", reason="decomposition_lgbtq_school_speech_event"),
            QueryExpansion(query="aggregate", reason="decomposition_attribute_aggregation"),
        ),
        expansions=(
            QueryExpansion(query="events", reason="event_participation_bridge"),
            QueryExpansion(query="pride", reason="lgbtq_pride_event_bridge"),
            QueryExpansion(query="support", reason="lgbtq_support_group_event_bridge"),
            QueryExpansion(query="school", reason="lgbtq_school_event_bridge"),
            QueryExpansion(query="conversation", reason="conversation_transcript_evidence_bridge"),
            QueryExpansion(query="meeting", reason="meeting_evidence_bridge"),
        ),
    )

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=6)

    assert [query.reason for query in selected] == [
        "original_query",
        "decomposition_event_context",
        "decomposition_lgbtq_pride_event",
        "decomposition_lgbtq_support_group_event",
        "decomposition_lgbtq_school_speech_event",
        "event_participation_bridge",
    ]


def test_bounded_retrieval_queries_keep_lgbtq_event_slots_for_real_query_plan() -> None:
    plan = build_query_expansion_plan("What LGBTQ+ events has Caroline participated in?")

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=6)

    assert [query.reason for query in selected] == [
        "original_query",
        "decomposition_event_context",
        "decomposition_lgbtq_pride_event",
        "decomposition_lgbtq_support_group_event",
        "decomposition_lgbtq_school_speech_event",
        "event_participation_bridge",
    ]


def test_bounded_retrieval_queries_keep_transgender_event_bridges_for_real_query_plan() -> None:
    plan = build_query_expansion_plan("What transgender-specific events has Caroline attended?")

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=6)

    assert [query.reason for query in selected] == [
        "original_query",
        "decomposition_event_context",
        "event_participation_bridge",
        "transgender_poetry_event_bridge",
        "transgender_conference_event_bridge",
        "transgender_youth_center_event_bridge",
    ]


def test_bounded_retrieval_queries_keep_specific_considered_attribute_bridges() -> None:
    religious = build_query_expansion_plan("Would Caroline be considered religious?")
    ally = build_query_expansion_plan(
        "Would Melanie be considered an ally to the transgender community?"
    )

    assert [query.reason for query in _bounded_derived_retrieval_queries(
        religious,
        fallback="fallback",
        limit=4,
    )] == [
        "original_query",
        "religious_inference_bridge",
        "decomposition_inference_support",
    ]
    assert [query.reason for query in _bounded_derived_retrieval_queries(
        ally,
        fallback="fallback",
        limit=4,
    )] == [
        "original_query",
        "ally_support_bridge",
        "identity_bridge",
        "decomposition_identity_attribute",
    ]


def test_bounded_retrieval_queries_keep_generic_behavior_inference_bridge() -> None:
    plan = build_query_expansion_plan("Would Alex be considered reliable?")

    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            plan,
            fallback="fallback",
            limit=3,
        )
    ] == [
        "original_query",
        "generic_behavior_inference_bridge",
        "decomposition_inference_support",
    ]


def test_bounded_retrieval_queries_prioritize_commonality_bridges() -> None:
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query="generic clause", reason="decomposition_clause"),
            QueryExpansion(query="common people", reason="decomposition_commonality"),
        ),
        expansions=(
            QueryExpansion(query="shared hobbies", reason="commonality_interest_bridge"),
            QueryExpansion(
                query="lost jobs own business",
                reason="business_commonality_bridge",
            ),
        ),
    )

    selected = _bounded_derived_retrieval_queries(plan, fallback="fallback", limit=4)

    assert [query.reason for query in selected] == [
        "original_query",
        "decomposition_commonality",
        "commonality_interest_bridge",
        "business_commonality_bridge",
    ]


def test_bounded_retrieval_queries_prioritize_friend_team_inference_bridge() -> None:
    plan = build_query_expansion_plan("Does Nate have friends besides Joanna?")
    degree = build_query_expansion_plan("What might John's degree be in?")
    workshop = build_query_expansion_plan(
        "What kind of counseling workshop did Melanie attend recently?"
    )

    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            plan,
            fallback="fallback",
            limit=3,
        )
    ] == [
        "original_query",
        "friends_team_inference_bridge",
    ]
    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            degree,
            fallback="fallback",
            limit=2,
        )
    ] == [
        "original_query",
        "degree_policy_inference_bridge",
    ]
    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            workshop,
            fallback="fallback",
            limit=3,
        )
    ] == [
        "original_query",
        "decomposition_event_context",
        "counseling_workshop_bridge",
    ]


def test_bounded_retrieval_queries_prioritize_high_signal_inference_bridges() -> None:
    education = build_query_expansion_plan(
        "What fields would Caroline be likely to pursue in her educaton?"
    )
    political = build_query_expansion_plan("What would Caroline's political leaning likely be?")
    allergy = build_query_expansion_plan(
        "What underlying condition might Joanna have based on her allergies?"
    )
    outdoor = build_query_expansion_plan("Does John live close to a beach or the mountains?")
    support_counterfactual = build_query_expansion_plan(
        "Would Caroline still want to pursue counseling as a career if she hadn't "
        "received support growing up?"
    )

    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            education,
            fallback="fallback",
            limit=4,
        )
    ] == [
        "original_query",
        "education_career_field_bridge",
        "decomposition_inference_support",
        "decomposition_current_preference_or_goal",
    ]
    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            political,
            fallback="fallback",
            limit=3,
        )
    ] == [
        "original_query",
        "political_inference_bridge",
        "decomposition_inference_support",
    ]
    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            allergy,
            fallback="fallback",
            limit=3,
        )
    ] == [
        "original_query",
        "allergy_condition_inference_bridge",
        "decomposition_inference_support",
    ]
    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            outdoor,
            fallback="fallback",
            limit=2,
        )
    ] == [
        "original_query",
        "beach_or_mountains_inference_bridge",
    ]
    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            support_counterfactual,
            fallback="fallback",
            limit=6,
        )
    ] == [
        "original_query",
        "decomposition_counterfactual_evidence",
        "support_career_motivation_bridge",
        "support_origin_bridge",
        "generic_behavior_inference_bridge",
        "support_counterfactual_bridge",
    ]


def test_bounded_retrieval_queries_prioritize_temporal_state_bridges() -> None:
    current = build_query_expansion_plan("Which Atlas provider is current?")
    stale = build_query_expansion_plan("Which Atlas provider is no longer valid?")
    transition = build_query_expansion_plan("What did Atlas switch from LocalAI to?")

    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            current,
            fallback="fallback",
            limit=3,
        )
    ] == [
        "original_query",
        "decomposition_knowledge_update_current",
        "current_state_temporal_bridge",
    ]
    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            stale,
            fallback="fallback",
            limit=3,
        )
    ] == [
        "original_query",
        "decomposition_knowledge_update_previous",
        "stale_state_temporal_bridge",
    ]
    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            transition,
            fallback="fallback",
            limit=4,
        )
    ] == [
        "original_query",
        "decomposition_temporal_change",
        "decomposition_state_transition",
        "state_transition_bridge",
    ]


def test_bounded_retrieval_queries_keep_russian_relationship_bridges() -> None:
    duration = build_query_expansion_plan("Как давно Алекс знает Марию?")
    status = build_query_expansion_plan("Алекс и Мария друзья?")
    connected = build_query_expansion_plan("Как Алекс связан с Марией?")
    friends_besides = build_query_expansion_plan("Есть ли у Нейта друзья помимо Жанны?")

    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            duration,
            fallback="fallback",
            limit=4,
        )
    ] == [
        "original_query",
        "relationship_duration_bridge",
    ]
    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            status,
            fallback="fallback",
            limit=4,
        )
    ] == [
        "original_query",
        "decomposition_relationship_status",
        "relationship_status_bridge",
        "decomposition_clause",
    ]
    assert [
        query.reason
        for query in _bounded_derived_retrieval_queries(
            connected,
            fallback="fallback",
            limit=4,
        )
    ] == [
        "original_query",
        "decomposition_relationship_status",
        "relationship_status_bridge",
    ]
    assert "relationship_status_bridge" not in {
        query.reason
        for query in _bounded_derived_retrieval_queries(
            friends_besides,
            fallback="fallback",
            limit=4,
        )
    }


def test_fused_ranked_keys_weights_original_query_over_decomposition_noise() -> None:
    ranked = _fused_ranked_keys(
        {
            "0:original_query": ("exact",),
            "1:decomposition_clause": ("decoy",),
            "2:decomposition_inference_support": ("decoy",),
        },
        limit=2,
    )

    assert ranked == ("exact", "decoy")


def test_fused_ranked_keys_weights_high_signal_evidence_over_noisy_decomposition() -> None:
    ranked = _fused_ranked_keys(
        {
            "0:decomposition_clause": ("broad_decoy",),
            "1:conversation_transcript_evidence_bridge": ("transcript_hit",),
        },
        limit=2,
    )

    assert ranked == ("transcript_hit", "broad_decoy")


def test_keyword_search_chunks_uses_weighted_rrf_across_query_variants() -> None:
    exact = _chunk("chunk_exact", "Atlas exact original decision.")
    decoy = _chunk("chunk_decoy", "Broad support text from weak decompositions.")
    uow = _FakeKeywordSearchUow(
        {
            "original": [exact],
            "broad one": [decoy],
            "broad two": [decoy],
        }
    )
    plan = QueryExpansionPlan(
        original_query="original",
        decompositions=(
            QueryExpansion(query="broad one", reason="decomposition_clause"),
            QueryExpansion(query="broad two", reason="decomposition_inference_support"),
        ),
        expansions=(),
    )

    result = asyncio.run(
        _keyword_search_chunks(
            uow,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=plan.retrieval_queries,
            limit=2,
        )
    )

    assert result == (exact, decoy)
    assert uow.chunks.searched_queries == ["original", "broad one", "broad two"]


def test_keyword_search_chunks_preserves_second_animal_care_facet_head() -> None:
    care_primary = _chunk(
        "care_primary",
        "Nate keeps the reptile area clean and checks the tank every day.",
    )
    care_followup = _chunk(
        "care_followup",
        "Nate says to feed them properly and make sure they get enough light.",
    )
    care_noise = _chunk("care_noise", "General pet store inventory notes.")
    broad_decoy = _chunk(
        "broad_decoy",
        "A generic gaming career conversation without animal care evidence.",
    )
    uow = _FakeKeywordSearchUow(
        {
            "alternative career after gaming": [broad_decoy],
            "care instructions": [care_primary, care_followup, care_noise],
            "broad after event": [broad_decoy],
        }
    )
    plan = QueryExpansionPlan(
        original_query="alternative career after gaming",
        decompositions=(
            QueryExpansion(query="broad after event", reason="decomposition_clause"),
        ),
        expansions=(
            QueryExpansion(
                query="care instructions",
                reason="animal_care_instruction_bridge",
            ),
        ),
    )

    result = asyncio.run(
        _keyword_search_chunks(
            uow,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=plan.retrieval_queries,
            limit=1,
        )
    )

    assert result[:2] == (care_primary, care_followup)
    assert broad_decoy in result


def test_rank_facts_for_query_uses_normalized_lexical_variants() -> None:
    decoy = _fact(
        "fact_decoy",
        "Проект Apollo обсуждал релиз без участия Алекса.",
    )
    current = _fact(
        "fact_current",
        "Встреча с Алексом по проекту Атлас завершилась решением сохранить запись.",
    )

    ranked = _rank_facts_for_query(
        (decoy, current),
        query_text="встречу Алекс проектом Атласом",
        limit=1,
    )

    assert ranked == (current,)


def test_rank_facts_for_query_uses_bounded_typo_match_for_long_terms() -> None:
    decoy = _fact(
        "fact_decoy",
        "Caroline shared an unrelated update about art, family and daily plans.",
    )
    current = _fact(
        "fact_current",
        "Caroline plans to continue her education and explore mental health counseling.",
    )

    ranked = _rank_facts_for_query(
        (decoy, current),
        query_text="What fields would Caroline pursue in her educaton?",
        limit=1,
    )

    assert ranked == (current,)


def test_rank_facts_for_query_prefers_phrase_signal_over_loose_decoy_terms() -> None:
    target = _fact(
        "fact_graphiti",
        "LONGMEM_DECISION_GRAPHITI: Graphiti remains the temporal fact engine.",
    )
    decoy = _fact(
        "fact_obsidian",
        "LONGMEM_DECOY_OBSIDIAN: Obsidian 3D graph is the primary runtime engine.",
    )

    ranked = _rank_facts_for_query(
        (decoy, target),
        query_text="primary runtime temporal fact engine Graphiti Obsidian 3D graph",
        limit=1,
    )

    assert ranked == (target,)


def test_rank_facts_for_query_drops_long_query_with_single_weak_hit() -> None:
    weak = _fact(
        "fact_warranty",
        "Billing warranty terms are tracked separately from project memories.",
    )

    ranked = _rank_facts_for_query(
        (weak,),
        query_text="unrelated yakutsk cooking recipe quantum aquarium warranty",
        limit=1,
    )

    assert ranked == ()


class _FakeKeywordSearchUow:
    def __init__(self, results_by_query: dict[str, list[MemoryChunk]]) -> None:
        self.chunks = _FakeKeywordChunks(results_by_query)


class _FakeKeywordChunks:
    def __init__(self, results_by_query: dict[str, list[MemoryChunk]]) -> None:
        self._results_by_query = results_by_query
        self.searched_queries: list[str] = []

    async def keyword_search(
        self,
        *,
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None,
        query: str,
        limit: int,
    ) -> list[MemoryChunk]:
        del space_id, memory_scope_ids, thread_id
        self.searched_queries.append(query)
        return list(self._results_by_query.get(query, ()))[:limit]


def _chunk(chunk_id: str, text: str) -> MemoryChunk:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryChunk.create(
        chunk_id=MemoryChunkId(chunk_id),
        space_id=SpaceId("space_test"),
        memory_scope_id=MemoryScopeId("scope_test"),
        document_id=MemoryDocumentId(f"{chunk_id}_document"),
        source_type="document",
        source_external_id=f"{chunk_id}_source",
        source_hash=f"{chunk_id}_hash",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=text,
        normalized_text=text.casefold(),
        sequence=1,
        char_start=0,
        char_end=len(text),
        token_estimate=8,
        now=now,
    )


def _fact(fact_id: str, text: str) -> MemoryFact:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryFact.create(
        fact_id=MemoryFactId(fact_id),
        space_id=SpaceId("space_test"),
        memory_scope_id=MemoryScopeId("scope_test"),
        text=text,
        kind=MemoryKind.NOTE,
        source_refs=(SourceRef(source_type="manual", source_id=f"{fact_id}_source"),),
        now=now,
    )
