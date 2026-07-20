"""Focused source-sibling evidence classification rules."""

from __future__ import annotations

import re

from infinity_context_core.application.context_creative_work_count_exact_turns import (
    creative_work_count_answer_rank,
    creative_work_count_role_alignment_rank,
)
from infinity_context_core.application.context_english_lifestyle_inference import (
    english_lifestyle_answer_slot_and_rank,
    english_lifestyle_query_kind,
)
from infinity_context_core.application.context_food_inventory_exact_turns import (
    food_inventory_answer_support_applies,
    food_inventory_answer_support_rank,
    food_inventory_role_alignment_rank,
)
from infinity_context_core.application.context_generic_behavior_inference import (
    generic_behavior_inference_signal,
)
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
)
from infinity_context_core.application.context_recommendation_answer_support import (
    is_recommendation_list_reason,
    recommendation_list_answer_support_rank,
)
from infinity_context_core.application.context_relationship_status_evidence import (
    is_relationship_status_answer_evidence,
)
from infinity_context_core.application.context_relative_duration_evidence import (
    has_relative_duration_event_evidence,
)
from infinity_context_core.application.context_source_sibling_evidence_shared import (
    _is_collectible_object_source_sibling_answer_evidence,
    _is_common_interest_animal_affinity_answer_evidence,
    _is_common_interest_animal_affinity_window_answer_evidence,
    _is_precise_turn_retrieval_text,
    _query_person_matches_text,
)
from infinity_context_core.application.context_source_sibling_inventory_evidence import (
    source_sibling_inventory_answer_slot_count,
)
from infinity_context_core.application.context_source_sibling_patterns import (
    _ACTIVITY_COMPETITION_SOURCE_SIBLING_RE,
    _ACTIVITY_DIRECT_SOURCE_SIBLING_RE,
    _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS,
    _ACTIVITY_DURATION_SOURCE_SIBLING_SIGNAL_RE,
    _ANIMAL_CARE_INSTRUCTION_SOURCE_SIBLING_RE,
    _ANIMAL_DIET_EVIDENCE_SOURCE_SIBLING_RE,
    _BIRDWATCHING_CITY_SCHEDULE_ACCESS_SLOT_RE,
    _BIRDWATCHING_CITY_SCHEDULE_EQUIPMENT_SLOT_RE,
    _BIRDWATCHING_CITY_SCHEDULE_HOBBY_SLOT_RE,
    _BIRDWATCHING_CITY_SCHEDULE_PRESSURE_SLOT_RE,
    _BIRDWATCHING_CITY_SCHEDULE_SOURCE_SIBLING_RE,
    _BOOK_READING_INVENTORY_SOURCE_SIBLING_RE,
    _BUSINESS_COMMONALITY_DIRECT_SOURCE_SIBLING_RE,
    _CAREER_PATH_SOURCE_SIBLING_RE,
    _CAUSE_DIRECT_SOURCE_SIBLING_RE,
    _CHARITY_BRAND_SPONSORSHIP_SOURCE_SIBLING_RE,
    _CHURCH_FRIEND_ACTIVITY_SOURCE_SIBLING_RE,
    _CREATIVE_WORK_COUNT_SOURCE_SIBLING_REASONS,
    _CUSTOMER_EXPERIENCE_DIRECT_SOURCE_SIBLING_RE,
    _DEGREE_POLICY_SOURCE_SIBLING_RE,
    _DESTRESS_ACTIVITY_DIRECT_SOURCE_SIBLING_RE,
    _DIALOGUE_TURN_SPEAKER_RE,
    _ESCAPE_ACTIVITY_DIRECT_SOURCE_SIBLING_RE,
    _ESCAPE_ACTIVITY_SOURCE_SIBLING_QUERY_RE,
    _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS,
    _FREQUENCY_RECURRENCE_SOURCE_SIBLING_SIGNAL_RE,
    _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON,
    _GRAND_OPENING_SUPPORT_DIRECT_SOURCE_SIBLING_RE,
    _MEDIA_WATCHING_DIRECT_SOURCE_SIBLING_RE,
    _MEDIA_WATCHING_SOURCE_SIBLING_QUERY_RE,
    _MOVIE_SEEN_DIRECT_SOURCE_SIBLING_RE,
    _MOVIE_SEEN_SOURCE_SIBLING_QUERY_RE,
    _NAMED_PREFERENCE_DIRECT_SOURCE_SIBLING_RE,
    _NAMED_PREFERENCE_QUERY_STOPWORDS,
    _NAMED_PREFERENCE_QUERY_TOKEN_RE,
    _NAMED_PREFERENCE_SOURCE_SIBLING_QUERY_RE,
    _NICKNAME_DIRECT_SOURCE_SIBLING_RE,
    _NICKNAME_QUERY_RE,
    _OPINION_REACTION_ADOPTION_QUERY_RE,
    _OPINION_REACTION_ADOPTION_TEXT_RE,
    _OPINION_REACTION_SOURCE_SIBLING_QUERY_RE,
    _OPINION_REACTION_SOURCE_SIBLING_RE,
    _PET_ADJUSTMENT_DIRECT_SOURCE_SIBLING_RE,
    _PLACE_INVENTORY_SOURCE_SIBLING_QUERY_RE,
    _PLANNING_TOOL_USE_DIRECT_SOURCE_SIBLING_RE,
    _POST_EVENT_ACTIVITY_SOURCE_SIBLING_RE,
    _POST_EVENT_SUPPORT_APPRECIATION_SOURCE_SIBLING_RE,
    _POTTERY_TYPE_SOURCE_SIBLING_ACTION_RE,
    _POTTERY_TYPE_SOURCE_SIBLING_OBJECT_RE,
    _PUBLIC_OFFICE_MOTIVATION_SOURCE_SIBLING_RE,
    _PUBLIC_OFFICE_SOURCE_SIBLING_QUERY_RE,
    _RECOGNITION_AWARD_DIRECT_SOURCE_SIBLING_RE,
    _RECOGNITION_AWARD_SOURCE_SIBLING_QUERY_RE,
    _RECOGNITION_CERTIFICATE_VISUAL_SOURCE_SIBLING_RE,
    _RUNNING_REASON_SOURCE_SIBLING_RE,
    _STATE_ACTIVITY_SOURCE_SIBLING_CONTEXT_RE,
    _STUDY_TIME_MANAGEMENT_DIRECT_SOURCE_SIBLING_RE,
    _STUDY_TIME_MANAGEMENT_SOURCE_SIBLING_QUERY_RE,
    _SUPPORT_NETWORK_DIRECT_SOURCE_SIBLING_RE,
    _SUPPORT_NETWORK_SOURCE_SIBLING_REASONS,
    _TRIP_DESTINATION_DIRECT_SOURCE_SIBLING_RE,
    _TRIP_DESTINATION_NAMED_DIRECT_SOURCE_SIBLING_RE,
    _VOLUNTEER_CAREER_SOURCE_SIBLING_CONTEXT_RE,
    _VOLUNTEER_CAREER_SOURCE_SIBLING_SIGNAL_RE,
    _VOLUNTEERING_INVENTORY_SOURCE_SIBLING_RE,
    _VOLUNTEERING_SERVICE_ACTIVITY_SOURCE_SIBLING_RE,
)
from infinity_context_core.application.context_source_sibling_place_evidence import (
    is_country_destination_source_sibling_answer_evidence,
    is_country_inventory_place_inference_query,
    is_place_inference_source_sibling_answer_evidence,
    is_query_destination_source_sibling_anchor,
    is_themed_location_source_sibling_answer_evidence,
)
from infinity_context_core.application.context_travel_hobby_writing_evidence import (
    is_travel_hobby_writing_source_sibling_answer_evidence,
)

_ACTIVITY_EVENT_DURATION_CONTEXT_FAMILY_RES = (
    re.compile(
        r"\b(?:commut\w*|travel\w*|journeys?|trips?|driv\w*|rode|rides?|"
        r"flights?|transit|transport\w*)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:run\w*|walk\w*|hik\w*|cycl\w*|workouts?|exercis\w*)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meetings?|appointments?|classes?|sessions?|practice\w*|training)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:events?|handoffs?|deliver\w*|maintenance|repairs?|install\w*)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:volunteer\w*|work(?:ed|ing|s)?|jobs?|shifts?)\b",
        re.IGNORECASE,
    ),
)
_ACTIVITY_EVENT_DURATION_SOURCE_SIBLING_SIGNAL_RE = re.compile(
    r"\b(?:takes?|took|lasts?|lasted|spends?|spent|required?)\b.{0,80}"
    r"\b(?:about\s+|around\s+|roughly\s+|nearly\s+|almost\s+|over\s+)?"
    r"(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|half)\s*"
    r"(?:minutes?|mins?|hours?|hrs?)\b|"
    r"\b(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|half)\s*"
    r"(?:minutes?|mins?|hours?|hrs?)\b.{0,48}\b(?:each\s+way|one[- ]way|round\s+trip)\b",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_EVENT_DURATION_ADVICE_RE = re.compile(
    r"\b(?:should|could|might|may|recommend\w*|suggest\w*|"
    r"allow|budget|plan|set\s+aside|give\s+(?:yourself|them|us)|aim\s+for)\b"
    r".{0,100}\b(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|half)\s*(?:minutes?|mins?|hours?|hrs?)\b",
    re.IGNORECASE | re.DOTALL,
)


def _is_pottery_type_source_sibling_strong(text: str) -> bool:
    return (
        _POTTERY_TYPE_SOURCE_SIBLING_OBJECT_RE.search(text) is not None
        and _POTTERY_TYPE_SOURCE_SIBLING_ACTION_RE.search(text) is not None
    )


def _is_animal_care_instruction_source_sibling_strong(text: str) -> bool:
    return _ANIMAL_CARE_INSTRUCTION_SOURCE_SIBLING_RE.search(text) is not None


def _is_animal_diet_evidence_source_sibling_strong(text: str) -> bool:
    return _ANIMAL_DIET_EVIDENCE_SOURCE_SIBLING_RE.search(text) is not None


def _is_animal_diet_evidence_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "animal_diet_evidence_bridge"
        and _is_animal_diet_evidence_source_sibling_strong(text)
    )


def _is_pottery_type_source_sibling_reason(expansion_reason: str) -> bool:
    return expansion_reason.replace("_", "-") in {
        "pottery-type-bridge",
        "decomposition-inventory-list",
    }


def _is_pottery_type_source_sibling_scope(*, expansion_reason: str, expansion_query: str) -> bool:
    if expansion_reason == "pottery_type_bridge":
        return True
    if expansion_reason != "decomposition_inventory_list":
        return False
    return _POTTERY_TYPE_SOURCE_SIBLING_OBJECT_RE.search(expansion_query) is not None


def _is_pottery_type_observation_companion_text(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    if not _is_pottery_type_source_sibling_reason(expansion_reason):
        return False
    return _is_pottery_type_source_sibling_strong(text) and "related turns:" in text.lower()


def _is_running_reason_source_sibling_strong(text: str) -> bool:
    return _RUNNING_REASON_SOURCE_SIBLING_RE.search(text) is not None


def _is_running_reason_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return expansion_reason in {
        "running_reason_bridge",
        "running_reason_question_bridge",
    } and _is_running_reason_source_sibling_strong(text)


def _is_volunteer_career_source_sibling_strong(text: str) -> bool:
    return (
        _VOLUNTEER_CAREER_SOURCE_SIBLING_CONTEXT_RE.search(text) is not None
        and _VOLUNTEER_CAREER_SOURCE_SIBLING_SIGNAL_RE.search(text) is not None
    )


def _is_charity_brand_sponsorship_source_sibling_strong(text: str) -> bool:
    return _CHARITY_BRAND_SPONSORSHIP_SOURCE_SIBLING_RE.search(text) is not None


def _is_career_path_source_sibling_strong(text: str) -> bool:
    return _CAREER_PATH_SOURCE_SIBLING_RE.search(text) is not None


def _is_english_lifestyle_inference_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    text: str,
) -> bool:
    if not english_lifestyle_query_kind(expansion_query):
        return False
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    slot, rank = english_lifestyle_answer_slot_and_rank(
        text,
        query=expansion_query,
    )
    return bool(slot) and rank == 0


def _is_direct_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    normalized_reason = expansion_reason.replace("_", "-")
    if (
        normalized_reason == "commonality-interest-bridge"
        and _MOVIE_SEEN_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
        and _MOVIE_SEEN_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    ):
        return True
    if _is_common_interest_animal_affinity_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_common_interest_animal_affinity_window_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_creative_work_count_source_sibling_answer_evidence(
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
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    if has_relative_duration_event_evidence(
        query=expansion_query,
        query_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_relationship_status_answer_evidence(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if (
        source_sibling_inventory_answer_slot_count(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
        > 0
    ):
        return True
    if food_inventory_answer_support_applies(
        query=expansion_query,
        query_reason=expansion_reason,
    ):
        return (
            food_inventory_role_alignment_rank(
                text=text,
                query=expansion_query,
                query_reason=expansion_reason,
            )
            <= 1
            and food_inventory_answer_support_rank(
                text=text,
                query=expansion_query,
                query_reason=expansion_reason,
                has_exact_turn=True,
            )
            <= 1
        )
    if (
        is_recommendation_list_reason(expansion_reason)
        and recommendation_list_answer_support_rank(
            text=text,
            query_reason=expansion_reason,
        )
        <= 2
    ):
        return True
    if normalized_reason == "item-purchase-bridge":
        return has_item_purchase_object_evidence(text)
    if normalized_reason in {
        "business-commonality-bridge",
        "business-start-reason-bridge",
    }:
        return _BUSINESS_COMMONALITY_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if (
        normalized_reason == "public-office-service-bridge"
        or _PUBLIC_OFFICE_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    ):
        return _PUBLIC_OFFICE_MOTIVATION_SOURCE_SIBLING_RE.search(text) is not None
    if (
        normalized_reason == "recognition-award-bridge"
        or _RECOGNITION_AWARD_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    ):
        return _is_recognition_award_direct_source_sibling(text)
    if normalized_reason == "planning-tool-use-bridge":
        return _PLANNING_TOOL_USE_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason == "customer-experience-bridge":
        return _CUSTOMER_EXPERIENCE_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason == "grand-opening-support-bridge":
        return _GRAND_OPENING_SUPPORT_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason == "charity-brand-sponsorship-bridge":
        return _is_charity_brand_sponsorship_source_sibling_strong(text)
    if normalized_reason == "travel-hobby-writing-bridge":
        return is_travel_hobby_writing_source_sibling_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
    if normalized_reason == "pet-adjustment-bridge":
        return _PET_ADJUSTMENT_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason == "post-event-emotion-bridge":
        return _POST_EVENT_SUPPORT_APPRECIATION_SOURCE_SIBLING_RE.search(text) is not None
    if _is_opinion_reaction_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if normalized_reason == "destress-activity-bridge":
        return _DESTRESS_ACTIVITY_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason in {
        "activity-aggregation-bridge",
        "decomposition-activity-participation",
        "family-activity-bridge",
    }:
        return _ACTIVITY_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if (
        normalized_reason == "nickname-bridge"
        or _NICKNAME_QUERY_RE.search(expansion_query) is not None
    ):
        return _NICKNAME_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if _is_named_preference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_place_inference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_themed_location_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_query_destination_source_sibling_anchor(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_country_destination_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if (
        normalized_reason == "study-time-management-bridge"
        or _STUDY_TIME_MANAGEMENT_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    ):
        return _STUDY_TIME_MANAGEMENT_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if is_query_destination_source_sibling_anchor(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _MEDIA_WATCHING_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None:
        return _MEDIA_WATCHING_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if _ESCAPE_ACTIVITY_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None:
        return _ESCAPE_ACTIVITY_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if _is_named_preference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_place_inference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_themed_location_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if is_query_destination_source_sibling_anchor(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if normalized_reason in {
        "cause-education-infrastructure-inventory-bridge",
        "cause-veterans-inventory-bridge",
    }:
        return _CAUSE_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if _PLACE_INVENTORY_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None:
        if is_country_inventory_place_inference_query(expansion_query):
            return False
        return _TRIP_DESTINATION_NAMED_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    if normalized_reason == "trip-destination-bridge":
        return _TRIP_DESTINATION_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    return False


def _is_opinion_reaction_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if (
        expansion_reason.replace("_", "-") != "opinion-reaction-bridge"
        and _OPINION_REACTION_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is None
    ):
        return False
    if not _is_precise_turn_retrieval_text(text) and _DIALOGUE_TURN_SPEAKER_RE.search(text) is None:
        return False
    if _OPINION_REACTION_SOURCE_SIBLING_RE.search(text) is None:
        return False
    return not (
        _OPINION_REACTION_ADOPTION_QUERY_RE.search(expansion_query) is not None
        and _OPINION_REACTION_ADOPTION_TEXT_RE.search(text) is None
    )


def _is_creative_work_count_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if not _is_creative_work_count_source_sibling_scope(expansion_reason):
        return False
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    if not _is_precise_turn_retrieval_text(text):
        return False
    return (
        creative_work_count_role_alignment_rank(
            text=text,
            query=expansion_query,
            query_reason=expansion_reason,
        )
        <= 1
        and creative_work_count_answer_rank(
            text=text,
            query=expansion_query,
            query_reason=expansion_reason,
            has_exact_turn=True,
        )
        <= 1
    )


def _is_creative_work_count_source_sibling_scope(expansion_reason: str) -> bool:
    return expansion_reason.replace("_", "-") in _CREATIVE_WORK_COUNT_SOURCE_SIBLING_REASONS


def _is_named_preference_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if (
        expansion_reason != "decomposition_inference_support"
        and _NAMED_PREFERENCE_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is None
    ):
        return False
    if _NAMED_PREFERENCE_DIRECT_SOURCE_SIBLING_RE.search(text) is None:
        return False
    text_casefold = text.casefold()
    return any(
        phrase in text_casefold for phrase in _named_preference_query_phrases(expansion_query)
    )


def is_named_preference_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return _is_named_preference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )


def _named_preference_query_phrases(expansion_query: str) -> tuple[str, ...]:
    tokens = tuple(
        token.casefold().strip("+-'")
        for token in _NAMED_PREFERENCE_QUERY_TOKEN_RE.findall(expansion_query)
    )
    content_tokens = tuple(
        token
        for token in tokens
        if len(token) >= 3 and token not in _NAMED_PREFERENCE_QUERY_STOPWORDS
    )
    phrases: list[str] = []
    for width in (3, 2):
        if len(content_tokens) < width:
            continue
        for index in range(0, len(content_tokens) - width + 1):
            phrase = " ".join(content_tokens[index : index + width])
            if phrase not in phrases:
                phrases.append(phrase)
    return tuple(phrases)


def _is_support_network_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason in _SUPPORT_NETWORK_SOURCE_SIBLING_REASONS
        and _SUPPORT_NETWORK_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_book_reading_inventory_source_sibling_strong(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason
        in {
            "book_reading_list_bridge",
            "creative_writing_career_bridge",
            "decomposition_inventory_list",
        }
        and _BOOK_READING_INVENTORY_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_activity_competition_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "activity_competition_evidence_bridge"
        and _ACTIVITY_COMPETITION_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_church_friend_activity_inventory_source_sibling_strong(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason
        in {"church_friend_activity_inventory_bridge", "decomposition_inventory_list"}
        and _CHURCH_FRIEND_ACTIVITY_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_volunteering_inventory_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason
        in {"volunteering_inventory_bridge", "volunteering_people_inventory_bridge"}
        and _VOLUNTEERING_INVENTORY_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_volunteering_service_activity_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason in {"volunteering_inventory_bridge", "decomposition_inventory_list"}
        and _VOLUNTEERING_SERVICE_ACTIVITY_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_recognition_award_direct_source_sibling(text: str) -> bool:
    return (
        _RECOGNITION_AWARD_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
        or _RECOGNITION_CERTIFICATE_VISUAL_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_degree_policy_source_sibling_strong(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason != "degree_policy_inference_bridge":
        return False
    return _DEGREE_POLICY_SOURCE_SIBLING_RE.search(text) is not None


def _is_post_event_activity_source_sibling_strong(text: str) -> bool:
    return _POST_EVENT_ACTIVITY_SOURCE_SIBLING_RE.search(text) is not None


def _is_temporal_state_source_sibling_strong(
    *,
    expansion_reason: str,
    text: str,
    expansion_query: str = "",
) -> bool:
    if expansion_reason in _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS:
        return _is_activity_duration_source_sibling_strong(
            text,
            expansion_query=expansion_query,
        )
    if expansion_reason in _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS:
        return _is_frequency_recurrence_source_sibling_strong(text)
    return False


def _is_activity_duration_source_sibling_strong(
    text: str,
    *,
    expansion_query: str = "",
) -> bool:
    ongoing_duration = (
        _STATE_ACTIVITY_SOURCE_SIBLING_CONTEXT_RE.search(text) is not None
        and _ACTIVITY_DURATION_SOURCE_SIBLING_SIGNAL_RE.search(text) is not None
    )
    if ongoing_duration:
        return True
    return bool(expansion_query) and _is_activity_event_duration_source_sibling_strong(
        expansion_query=expansion_query,
        text=text,
    )


def _is_activity_event_duration_source_sibling_strong(
    *,
    expansion_query: str,
    text: str,
) -> bool:
    if _STATE_ACTIVITY_SOURCE_SIBLING_CONTEXT_RE.search(text) is None:
        return False
    if _ACTIVITY_EVENT_DURATION_SOURCE_SIBLING_SIGNAL_RE.search(text) is None:
        return False
    if _ACTIVITY_EVENT_DURATION_ADVICE_RE.search(text) is not None:
        return False
    query_families = _activity_event_context_families(expansion_query)
    text_families = _activity_event_context_families(text)
    if not query_families or not text_families:
        return False
    generic_family = len(_ACTIVITY_EVENT_DURATION_CONTEXT_FAMILY_RES) - 1
    specific_query_families = query_families - {generic_family}
    return bool((specific_query_families or query_families).intersection(text_families))


def _activity_event_context_families(value: str) -> set[int]:
    return {
        index
        for index, pattern in enumerate(_ACTIVITY_EVENT_DURATION_CONTEXT_FAMILY_RES)
        if pattern.search(value) is not None
    }


def _is_frequency_recurrence_source_sibling_strong(text: str) -> bool:
    return (
        _STATE_ACTIVITY_SOURCE_SIBLING_CONTEXT_RE.search(text) is not None
        and _FREQUENCY_RECURRENCE_SOURCE_SIBLING_SIGNAL_RE.search(text) is not None
    )


def _is_birdwatching_city_schedule_source_sibling_strong(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "birdwatching_city_schedule_bridge"
        and _BIRDWATCHING_CITY_SCHEDULE_SOURCE_SIBLING_RE.search(text) is not None
    )


def _birdwatching_city_schedule_slot_count(text: str) -> int:
    slots = 0
    for pattern in (
        _BIRDWATCHING_CITY_SCHEDULE_ACCESS_SLOT_RE,
        _BIRDWATCHING_CITY_SCHEDULE_EQUIPMENT_SLOT_RE,
        _BIRDWATCHING_CITY_SCHEDULE_PRESSURE_SLOT_RE,
        _BIRDWATCHING_CITY_SCHEDULE_HOBBY_SLOT_RE,
    ):
        if pattern.search(text) is not None:
            slots += 1
    return slots


def _is_generic_behavior_source_sibling_strong(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason != _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON:
        return False
    if (
        generic_behavior_inference_signal(query=expansion_query, text=text).reason
        == "inference_behavior_evidence"
    ):
        return True
    # Score caps do not receive the winning expansion query. This strict fallback
    # keeps concrete behavior turns uncapped while still rejecting topic-only text.
    return (
        generic_behavior_inference_signal(query=text, text=text).reason
        == "inference_behavior_evidence"
    )
