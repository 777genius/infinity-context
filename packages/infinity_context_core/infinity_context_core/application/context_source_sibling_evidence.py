"""Source-sibling answer-evidence classification."""

from __future__ import annotations

from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
)
from infinity_context_core.application.context_recommendation_answer_support import (
    is_recommendation_list_reason,
    recommendation_role_alignment_rank,
)
from infinity_context_core.application.context_relationship_status_evidence import (
    is_relationship_status_answer_evidence,
    relationship_status_answer_rank,
)
from infinity_context_core.application.context_relative_duration_evidence import (
    has_relative_duration_event_evidence,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_source_sibling_evidence_rules import (
    _is_activity_competition_source_sibling_strong_for_reason,
    _is_activity_duration_source_sibling_strong,
    _is_animal_diet_evidence_source_sibling_strong_for_reason,
    _is_book_reading_inventory_source_sibling_strong,
    _is_charity_brand_sponsorship_source_sibling_strong,
    _is_church_friend_activity_inventory_source_sibling_strong,
    _is_creative_work_count_source_sibling_answer_evidence,
    _is_creative_work_count_source_sibling_scope,
    _is_direct_source_sibling_answer_evidence,
    _is_english_lifestyle_inference_source_sibling_answer_evidence,
    _is_frequency_recurrence_source_sibling_strong,
    _is_recognition_award_direct_source_sibling,
    _is_running_reason_source_sibling_strong_for_reason,
    _is_support_network_source_sibling_strong_for_reason,
    _is_volunteering_inventory_source_sibling_strong_for_reason,
    _is_volunteering_service_activity_source_sibling_strong_for_reason,
)
from infinity_context_core.application.context_source_sibling_evidence_shared import (
    _is_activity_companion_answer_evidence,
    _is_board_game_direct_answer_evidence,
    _is_board_game_source_sibling_scope,
    _is_cause_awareness_source_sibling_strong_for_reason,
    _is_children_preference_source_sibling_strong_for_reason,
    _is_classical_music_preference_source_sibling_strong_for_reason,
    _is_collectible_object_source_sibling_answer_evidence,
    _is_common_interest_animal_affinity_window_answer_evidence,
    _is_common_interest_direct_answer_evidence,
    _is_gaming_medium_direct_answer_evidence,
    _is_gaming_medium_source_sibling_scope,
    _is_movie_seen_direct_answer_evidence,
    _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason,
    _is_outdoor_preference_source_sibling_strong_for_reason,
    _is_pet_acquisition_answer_evidence,
    _is_precise_turn_retrieval_text,
    _is_sentimental_reminder_source_sibling_strong_for_reason,
    _is_temporal_event_answer_evidence,
    _is_temporal_source_sibling_strong,
    _query_person_matches_text,
)
from infinity_context_core.application.context_source_sibling_inventory_evidence import (
    source_sibling_inventory_answer_slot_count,
)
from infinity_context_core.application.context_source_sibling_patterns import (
    _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS,
    _COMMON_INTEREST_SOURCE_SIBLING_REASONS,
    _CUSTOMER_EXPERIENCE_DIRECT_SOURCE_SIBLING_RE,
    _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS,
    _GRAND_OPENING_SUPPORT_DIRECT_SOURCE_SIBLING_RE,
    _MOVIE_SEEN_QUESTION_ONLY_SOURCE_SIBLING_RE,
    _MOVIE_SEEN_SOURCE_SIBLING_QUERY_RE,
    _PET_ADJUSTMENT_DIRECT_SOURCE_SIBLING_RE,
    _PLANNING_TOOL_USE_DIRECT_SOURCE_SIBLING_RE,
    _RELATED_TURN_ANCHOR_RE,
)
from infinity_context_core.application.context_source_sibling_place_evidence import (
    country_destination_answer_support_rank,
    is_country_destination_source_sibling_answer_evidence,
)
from infinity_context_core.application.context_travel_hobby_writing_evidence import (
    TRAVEL_HOBBY_WRITING_REASON,
    is_travel_hobby_writing_source_sibling_answer_evidence,
)


def source_sibling_related_turn_anchor_evidence(
    *,
    relevance: QueryRelevance,
    text: str,
) -> bool:
    return _RELATED_TURN_ANCHOR_RE.search(text) is not None and (
        relevance.distinctive_term_hits >= 2
        or relevance.unique_term_hits >= 3
        or relevance.hit_ratio >= 0.25
    )


def source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason == "pet_adjustment_bridge":
        return (
            _query_person_matches_text(
                expansion_query=expansion_query,
                text=text,
            )
            and _PET_ADJUSTMENT_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
        )
    if expansion_reason == "planning_tool_use_bridge":
        return (
            _query_person_matches_text(
                expansion_query=expansion_query,
                text=text,
            )
            and _PLANNING_TOOL_USE_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
        )
    if expansion_reason == "customer_experience_bridge":
        return (
            _query_person_matches_text(
                expansion_query=expansion_query,
                text=text,
            )
            and _CUSTOMER_EXPERIENCE_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
        )
    if expansion_reason == "grand_opening_support_bridge":
        return (
            _query_person_matches_text(
                expansion_query=expansion_query,
                text=text,
            )
            and _GRAND_OPENING_SUPPORT_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
        )
    if is_relationship_status_answer_evidence(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        )
    if _is_english_lifestyle_inference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        text=text,
    ):
        return True
    if expansion_reason == "charity_brand_sponsorship_bridge":
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and _is_charity_brand_sponsorship_source_sibling_strong(text)
    if expansion_reason == TRAVEL_HOBBY_WRITING_REASON:
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and is_travel_hobby_writing_source_sibling_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason == "recognition_award_bridge":
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and _is_recognition_award_direct_source_sibling(text)
    if expansion_reason == "church_friend_activity_inventory_bridge":
        return _query_person_matches_text(
            expansion_query=expansion_query,
            text=text,
        ) and _is_church_friend_activity_inventory_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    aggregation_slot_count = aggregation_answer_slot_count(
        query=expansion_query,
        text=text,
    )
    if aggregation_slot_count > 0:
        if (
            source_sibling_inventory_answer_slot_count(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=text,
            )
            > 0
        ):
            return _query_person_matches_text(
                expansion_query=expansion_query,
                text=text,
            )
        if _is_movie_seen_direct_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        ):
            return True
        if expansion_reason in _COMMON_INTEREST_SOURCE_SIBLING_REASONS:
            if (
                _MOVIE_SEEN_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
                and _MOVIE_SEEN_QUESTION_ONLY_SOURCE_SIBLING_RE.search(text) is not None
            ):
                return False
            if _is_common_interest_animal_affinity_window_answer_evidence(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=text,
            ):
                return True
            return _query_person_matches_text(
                expansion_query=expansion_query, text=text
            ) and _is_precise_turn_retrieval_text(text)
        if _is_board_game_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        ):
            return _is_board_game_direct_answer_evidence(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=text,
            )
        if _is_gaming_medium_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        ):
            return _is_gaming_medium_direct_answer_evidence(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=text,
            )
        if _is_creative_work_count_source_sibling_scope(expansion_reason):
            return _is_creative_work_count_source_sibling_answer_evidence(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=text,
            )
        return True
    if _is_common_interest_direct_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_collectible_object_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_board_game_direct_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_gaming_medium_direct_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_temporal_source_sibling_strong(
        expansion_query=expansion_query,
        text=text,
    ):
        return True
    if _is_temporal_event_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_pet_acquisition_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_cause_awareness_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if (
        expansion_reason in _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS
        and _is_frequency_recurrence_source_sibling_strong(text)
    ):
        return True
    if (
        expansion_reason in _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS
        and _is_activity_duration_source_sibling_strong(
            text,
            expansion_query=expansion_query,
        )
    ):
        return True
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    if has_relative_duration_event_evidence(
        query=expansion_query,
        query_reason=expansion_reason,
        text=text,
    ):
        return True
    return (
        _is_book_reading_inventory_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_activity_competition_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_activity_companion_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_church_friend_activity_inventory_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_volunteering_inventory_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_volunteering_service_activity_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_classical_music_preference_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_sentimental_reminder_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_collectible_object_source_sibling_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_outdoor_preference_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_children_preference_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_animal_diet_evidence_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_running_reason_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_support_network_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_direct_source_sibling_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
    )


def source_sibling_answer_evidence_role_rank(
    *,
    query_text: str,
    expansion_reason: str,
    text: str,
) -> int:
    """Return a direction rank for answer evidence where the query encodes roles."""

    if is_country_destination_source_sibling_answer_evidence(
        expansion_query=query_text,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return country_destination_answer_support_rank(
            expansion_query=query_text,
            text=text,
            has_exact_turn=_is_precise_turn_retrieval_text(text),
        )
    if is_relationship_status_answer_evidence(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return relationship_status_answer_rank(text)
    if not is_recommendation_list_reason(expansion_reason):
        return 0
    return recommendation_role_alignment_rank(
        text=text,
        query=query_text,
        query_reason=expansion_reason,
    )
