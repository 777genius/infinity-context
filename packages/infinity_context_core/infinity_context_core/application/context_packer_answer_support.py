# Compatibility imports intentionally remain public module attributes.

# ruff: noqa: F401

"""Compatibility exports and candidate orchestration for answer-support packing."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import (
    context_rank_key,
    diagnostic_retrieval_sources,
)
from infinity_context_core.application.context_food_inventory_exact_turns import (
    food_inventory_answer_support_applies,
    food_inventory_answer_support_rank,
    food_inventory_role_alignment_rank,
)
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
)
from infinity_context_core.application.context_packer_answer_support_content import (
    _CHARITY_BRAND_CONCRETE_DEAL_RE,
    _TRANSGENDER_YOUTH_CENTER_EVENT_DIRECT_RE,
    _activity_answer_content_rank,
    _animal_care_instruction_content_rank,
    _answer_object_rank,
    _birdwatching_city_schedule_answer_content_rank,
    _book_suggestion_answer_content_rank,
    _business_commonality_answer_content_rank,
    _cause_event_answer_content_rank,
    _charity_brand_sponsorship_answer_content_rank,
    _childhood_possession_answer_content_rank,
    _children_preference_answer_content_rank,
    _classical_music_preference_answer_content_rank,
    _collectible_object_answer_content_rank,
    _creative_work_submission_answer_content_rank,
    _creative_writing_inventory_answer_content_rank,
    _degree_policy_answer_content_rank,
    _friend_place_shelter_answer_content_rank,
    _inspiration_source_answer_content_rank,
    _music_artist_answer_content_rank,
    _outdoor_nature_memory_answer_content_rank,
    _pottery_type_answer_content_rank,
    _precise_answer_content_rank,
    _precise_turn_answer_support_rank,
    _public_office_service_answer_content_rank,
    _recognition_award_answer_content_rank,
    _relocation_willingness_answer_content_rank,
    _screenplay_rejection_answer_content_rank,
    _sentimental_reminder_answer_content_rank,
    _support_career_motivation_content_rank,
    _transgender_youth_center_event_answer_content_rank,
    _volunteer_career_answer_content_rank,
)
from infinity_context_core.application.context_packer_answer_support_evidence import (
    _ACTIVITY_COMPETITION_ATTITUDE_QUERY_RE,
    _ACTIVITY_COMPETITION_ATTITUDE_REPLY_RE,
    _ACTIVITY_COMPETITION_DANCER_REPLY_RE,
    _ACTIVITY_COMPETITION_VISUAL_ANSWER_RE,
    _ACTIVITY_COMPETITION_VISUAL_QUERY_RE,
    _COMMON_INTEREST_ANIMAL_ANSWER_QUERY_RE,
    _COMMON_INTEREST_ANIMAL_FALSE_FRIEND_RE,
    _COMMON_INTEREST_EXPLICIT_ANIMAL_CHOICE_RE,
    _EN_SHARED_VOLUNTEERING_QUERY_RE,
    _NEUTRAL_FIRST_MENTION_RANK,
    _RELATIONSHIP_STATUS_QUESTION_ONLY_RE,
    _RELATIONSHIP_STATUS_SELF_DISCLOSURE_RE,
    _SHARED_VOLUNTEERING_FIRST_MENTION_SLOTS,
    _SHARED_VOLUNTEERING_QUERY_REASONS,
    _activity_competition_visual_answer_rank,
    _answer_support_animal_evidence_family_slot,
    _answer_support_career_family_slot,
    _answer_support_common_interest_family_slot,
    _answer_support_inventory_family_slot,
    _birdwatching_city_schedule_exact_turn_rank,
    _business_dialogue_marker_answer_support_rank,
    _career_exact_turn_answer_support_rank,
    _common_interest_animal_answer_shape_rank,
    _common_interest_answer_support_rank,
    _common_interest_direct_evidence_rank,
    _common_interest_first_mention_rank,
    _common_interest_movie_seen_query_rank,
    _is_cause_inventory_answer_support_item,
    _is_direct_outdoor_activity_answer_support_item,
    _is_exact_animal_evidence_answer_family,
    _is_exact_business_direct_answer_support_item,
    _is_exact_cause_inventory_answer_support_item,
    _is_exact_common_interest_answer_support_item,
    _is_exact_conversational_support_family,
    _is_exact_inspiration_source_answer_support_item,
    _is_exact_named_game_inventory_answer_support_item,
    _is_exact_named_preference_answer_support_item,
    _is_exact_precise_content_answer_support_item,
    _is_exact_screenplay_rejection_answer_support_item,
    _is_exact_themed_location_inference_answer_support_item,
    _is_relationship_status_direct_answer_support_item,
    _is_single_exact_cause_inventory_answer_support_item,
    _marker_coverage_answer_support_rank,
    _recognition_award_visual_answer_rank,
    _relationship_status_answer_support_rank,
    _shared_volunteering_first_mention_rank,
)
from infinity_context_core.application.context_packer_answer_support_families import (
    _answer_support_diversity_family,
    _answer_support_source_group_limit,
    _answer_support_source_group_reason_key,
    _broad_turn_family_source_group,
    _broad_turn_source_group_counts,
    _exact_answer_support_marker_slot,
    _inventory_slot_precedes_marker_coverage,
    _is_count_aggregation_reason,
    _is_weak_vector_requirement_candidate,
    _marker_coverage_family_source_group,
    _marker_coverage_source_group_counts,
    _pet_acquisition_named_object_source_groups,
    _pet_acquisition_named_object_terms,
)
from infinity_context_core.application.context_packer_answer_support_locations import (
    _STATE_RESIDENCE_ANSWER_EVIDENCE_REASONS,
    _STATE_RESIDENCE_MAP_TRAIL_RE,
    _country_destination_answer_support_rank,
    _is_direct_place_area_state_answer_support_item,
    _is_exact_country_destination_answer_support_item,
    _is_exact_place_area_state_answer_support_item,
    _is_exact_place_inference_answer_support_item,
    _is_exact_query_destination_answer_support_item,
    _is_state_residence_geo_answer_support_item,
    _place_area_state_answer_support_rank,
    _place_area_state_query_applies,
    _place_area_state_query_wants_concrete_state,
    _state_residence_answer_support_rank,
)
from infinity_context_core.application.context_packer_answer_support_ordering import (
    _answer_support_coverage_family_slot,
    _answer_support_coverage_family_slot_priority,
    _answer_support_family_item_key,
    _answer_support_family_item_key_for_query,
    _answer_support_family_priority,
    _answer_support_query_focus_priority,
    _ordered_answer_support_families_for_query,
    _round_robin_inventory_slot_families,
)
from infinity_context_core.application.context_packer_answer_support_patterns import (
    _ACTIVITY_CONTEXT_RE,
    _ACTIVITY_DIRECT_PARTICIPATION_RE,
    _ANIMAL_CARE_DIRECT_INSTRUCTION_RE,
    _ANIMAL_CARE_GENERIC_HABITAT_RE,
    _ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS,
    _ANSWER_SUPPORT_EXCLUDED_QUERY_REASONS,
    _BIRDWATCHING_CITY_SCHEDULE_CONTENT_RE,
    _BOOK_SUGGESTION_DIRECT_RE,
    _BROAD_EVIDENCE_ANSWER_SUPPORT_REASONS,
    _BUSINESS_DIRECT_JOB_LOSS_RE,
    _BUSINESS_DIRECT_START_REASON_RE,
    _CHILDHOOD_POSSESSION_DIRECT_RE,
    _CHILDHOOD_POSSESSION_OBJECT_RE,
    _CHILDREN_PREFERENCE_CONTEXT_RE,
    _CHILDREN_PREFERENCE_DIRECT_RE,
    _CLASSICAL_MUSIC_PREFERENCE_DIRECT_RE,
    _COLLECTIBLE_OBJECT_CONTEXT_RE,
    _COLLECTIBLE_OBJECT_DIRECT_RE,
    _COMMON_INTEREST_ANIMAL_AFFINITY_SLOT_RE,
    _COMMON_INTEREST_INSPIRATIONAL_AFFINITY_SLOT_RE,
    _COMMON_INTEREST_MOVIE_QUESTION_ONLY_RE,
    _COMMON_INTEREST_MOVIE_SEEN_QUERY_RE,
    _COMMON_INTEREST_MOVIE_SEEN_SLOT_RE,
    _COMMON_INTEREST_MOVIE_SLOT_RE,
    _COMMON_INTEREST_PERSONAL_DESSERT_PREFERENCE_RE,
    _COMMON_INTEREST_PERSONAL_HOBBY_SLOT_RE,
    _COMMON_INTEREST_SELF_DESSERT_EVIDENCE_RE,
    _COMMON_INTEREST_SHARED_DESSERT_BRIDGE_RE,
    _COUNT_AGGREGATION_COVERAGE_REASONS,
    _CREATIVE_WORK_SUBMISSION_DIRECT_RE,
    _CREATIVE_WRITING_INVENTORY_DIRECT_RE,
    _DEGREE_COMPLETION_TEMPORAL_QUERY_RE,
    _DIALOGUE_MARKER_RE,
    _DIRECT_EVIDENCE_QUERY_FOCUS_REASONS,
    _DIVERSITY_FAMILY_PRIORITY,
    _DIVERSITY_PRECISE_TURN_REASONS,
    _EXACT_PRECISE_CONTENT_TURN_REASONS,
    _INSPIRATION_SOURCE_CONTEXT_RE,
    _INSPIRATION_SOURCE_DIRECT_RE,
    _INSPIRATION_SOURCE_QUERY_RE,
    _INVENTORY_FRIEND_PLACE_DIRECT_RE,
    _INVENTORY_FRIEND_PLACE_SHELTER_ACTIVITY_REPEAT_RE,
    _INVENTORY_FRIEND_PLACE_SHELTER_ANCHOR_RE,
    _INVENTORY_SHELTER_SLOT_RE,
    _MAX_ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON,
    _MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS,
    _MAX_ANSWER_SUPPORT_EVENT_SLOT_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON,
    _MAX_ANSWER_SUPPORT_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON,
    _MAX_INVENTORY_ANSWER_SUPPORT_DIVERSITY_ITEMS,
    _MILITARY_SERVICE_GOAL_DIRECT_RE,
    _MUSIC_ARTIST_DIRECT_ANSWER_RE,
    _MUSIC_EVENT_ATTENDANCE_QUERY_RE,
    _NAMED_ACQUISITION_OBJECT_QUERY_RE,
    _OUTDOOR_NATURE_MEMORY_CONTEXT_RE,
    _OUTDOOR_NATURE_MEMORY_DIRECT_RE,
    _PET_ACQUISITION_DATE_ANCHOR_SUPPORT_RE,
    _PET_ACQUISITION_OBJECT_ANCHOR_RE,
    _PLACE_AREA_DIRECT_LOCATION_RE,
    _PLACE_AREA_LANDMARK_LOCATION_RE,
    _PLACE_AREA_STATE_FUTURE_RE,
    _PLACE_AREA_STATE_QUERY_RE,
    _PLACE_AREA_STATE_VISIT_RE,
    _POTTERY_TYPE_DIRECT_MADE_OBJECT_RE,
    _POTTERY_TYPE_FRIENDSHIP_COMPANION_RE,
    _POTTERY_TYPE_GENERIC_ANSWER_OBJECT_RE,
    _POTTERY_TYPE_PROJECT_COMPANION_RE,
    _PRECISE_TURN_ANSWER_SUPPORT_REASONS,
    _PUBLIC_OFFICE_SERVICE_DIRECT_RE,
    _QUERY_OBJECT_TOKEN_RE,
    _RECOGNITION_CERTIFICATE_QUERY_RE,
    _RECOGNITION_CERTIFICATE_VISUAL_ANSWER_RE,
    _SCREENPLAY_REJECTION_DIRECT_RE,
    _SENTIMENTAL_REMINDER_CONTEXT_RE,
    _SENTIMENTAL_REMINDER_DIRECT_RE,
    _SUPPORT_CAREER_MOTIVATION_CONTEXT_RE,
    _SUPPORT_CAREER_MOTIVATION_DIRECT_RE,
    _TEMPORAL_ANSWER_SUPPORT_QUERY_RE,
    _TEMPORAL_ANSWER_SUPPORT_REASONS,
    _TEMPORAL_DIRECT_ANSWER_RE,
    _TEMPORAL_QUERY_OBJECT_STOPWORDS,
)
from infinity_context_core.application.context_packer_answer_support_slots import (
    _activity_answer_slot,
    _aggregation_marker_coverage_slot,
    _animal_evidence_answer_slot,
    _animal_evidence_answer_slot_from_family,
    _animal_evidence_answer_slot_priority_for_family,
    _animal_evidence_slot_for_text,
    _book_reading_answer_content_rank,
    _broad_evidence_turn_slot,
    _business_commonality_answer_slot,
    _career_answer_slot,
    _career_answer_slot_from_family,
    _career_answer_slot_priority,
    _cause_event_answer_slot,
    _charity_brand_sponsorship_answer_slot,
    _common_interest_answer_slot,
    _common_interest_answer_slot_from_family,
    _common_interest_answer_slot_priority,
    _degree_policy_answer_slot,
    _family_activity_answer_object_rank,
    _general_activity_answer_slot_for_text,
    _inference_answer_slot,
    _inventory_answer_slot,
    _inventory_answer_slot_for_text,
    _inventory_answer_slot_from_family,
    _inventory_list_answer_object_rank,
    _is_activity_participation_answer_reason,
    _is_common_interest_answer_reason,
    _is_community_participation_reason,
    _is_conversational_support_turn,
    _is_count_aggregation_coverage_item,
    _is_family_activity_reason,
    _is_inventory_list_reason,
    _is_pottery_type_inventory_item,
    _is_pottery_type_reason,
    _is_support_network_reason,
    _pottery_type_answer_object_rank,
    _support_network_answer_object_rank,
    _travel_country_inventory_slot_for_text,
)
from infinity_context_core.application.context_packer_answer_support_temporal import (
    _degree_completion_temporal_answer_support_rank,
    _is_degree_completion_temporal_answer_support_item,
    _is_exact_temporal_query_object_family,
    _is_pet_acquisition_date_anchor_answer_support_item,
    _is_temporal_answer_support_item,
    _pet_acquisition_date_anchor_answer_support_rank,
    _temporal_answer_support_query_object_hits,
    _temporal_answer_support_source_span_rank,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _answer_support_activity_family_slot,
    _answer_support_exact_query_object_hits,
    _answer_support_query_reason,
    _answer_support_source_group,
    _artifact_diversity_hint,
    _compound_diversity_family,
    _diagnostic_list,
    _diagnostic_score_signals,
    _diagnostic_signal_text,
    _diagnostic_signal_truthy,
    _diagnostic_text,
    _diversity_family_base,
    _exact_marker_should_precede_inventory,
    _first_dialogue_marker,
    _has_any_exact_turn_source_ref,
    _has_derived_source_group_ref,
    _has_primary_exact_turn_source_ref,
    _inventory_first_mention_rank,
    _is_business_commonality_reason,
    _numeric_signal,
    _primary_exact_turn_marker,
    _primary_exact_turn_source_id,
    _source_group_key,
    _source_key,
    _typed_diversity_family,
)
from infinity_context_core.application.context_packer_inventory_slots import (
    _answer_support_exact_turn_alignment_rank,
    _exercise_activity_answer_content_rank,
    _inventory_answer_slot_priority_for_family,
    _painting_inventory_answer_content_rank,
)
from infinity_context_core.application.context_recommendation_answer_support import (
    is_concrete_recommendation_answer,
    is_recommendation_list_reason,
    recommendation_family_priority,
    recommendation_list_answer_support_rank,
    recommendation_query_focus_applies,
    recommendation_role_alignment_rank,
)
from infinity_context_core.application.context_relationship_status_evidence import (
    is_relationship_status_answer_evidence,
    relationship_status_answer_rank,
)
from infinity_context_core.application.context_source_sibling_place_evidence import (
    country_destination_answer_support_rank,
    is_country_destination_source_sibling_answer_evidence,
    is_place_inference_source_sibling_answer_evidence,
    is_query_destination_source_sibling_anchor,
    is_themed_location_source_sibling_answer_evidence,
    query_destination_places,
)
from infinity_context_core.application.context_source_siblings import (
    _query_person_matches_text as _source_sibling_query_person_matches_text,
)
from infinity_context_core.application.context_source_siblings import (
    is_named_preference_source_sibling_answer_evidence,
)
from infinity_context_core.application.context_state_residence_inference import (
    state_residence_inference_signal,
)
from infinity_context_core.application.context_travel_hobby_writing_evidence import (
    TRAVEL_HOBBY_WRITING_REASON,
    travel_hobby_writing_answer_rank,
)
from infinity_context_core.application.dto import ContextItem


def _diversity_candidates(items: list[ContextItem]) -> dict[str, ContextItem]:
    candidates: dict[str, ContextItem] = {}
    for item in items:
        family = _diversity_family(item)
        existing = candidates.get(family)
        if existing is None or _diversity_candidate_item_key(item) < (
            _diversity_candidate_item_key(existing)
        ):
            candidates[family] = item
    return candidates

def _ordered_diversity_families(candidates: dict[str, ContextItem]) -> tuple[str, ...]:
    priority = {family: index for index, family in enumerate(_DIVERSITY_FAMILY_PRIORITY)}
    return tuple(
        sorted(
            candidates,
            key=lambda family: (
                priority.get(_diversity_family_base(family), len(priority)),
                context_rank_key(candidates[family]),
                family,
            ),
        )
    )

def _diversity_family(item: ContextItem) -> str:
    if item.item_type == "anchor":
        return _typed_diversity_family(
            "anchor",
            _diagnostic_text(item, "anchor_kind"),
        )
    if item.item_type == "extraction_artifact":
        return _typed_diversity_family(
            "extraction_artifact",
            _artifact_diversity_hint(item),
        )
    if item.item_type in _DIVERSITY_FAMILY_PRIORITY:
        return item.item_type
    return item.item_type or "unknown"

def _diversity_candidate_item_key(item: ContextItem) -> tuple[object, ...]:
    query_reason = _answer_support_query_reason(item)
    broad_window_rank = 1
    if (
        query_reason in _DIVERSITY_PRECISE_TURN_REASONS
        and _has_primary_exact_turn_source_ref(item)
    ) or (
        query_reason in _BROAD_EVIDENCE_ANSWER_SUPPORT_REASONS
        and len(item.source_refs) > 1
    ):
        broad_window_rank = 0
    return (
        broad_window_rank,
        context_rank_key(item),
    )

def _answer_support_diversity_candidates(
    items: list[ContextItem],
    *,
    query: str = "",
) -> dict[str, ContextItem]:
    candidates: dict[str, ContextItem] = {}
    for item in items:
        family = _answer_support_diversity_family(item)
        if not family:
            continue
        existing = candidates.get(family)
        if existing is None or _answer_support_family_item_key_for_query(
            item, query=query
        ) < (
            _answer_support_family_item_key_for_query(existing, query=query)
        ):
            candidates[family] = item
    return candidates

def _answer_support_source_ref_ids_sample(
    ordered_families: tuple[str, ...],
    candidates: dict[str, ContextItem],
) -> tuple[str, ...]:
    source_ids: list[str] = []
    for family in ordered_families:
        item = candidates.get(family)
        if item is None:
            continue
        source_id = _primary_exact_turn_source_id(item) or _source_key(item)
        source_id = source_id.strip()
        if source_id and source_id not in source_ids:
            source_ids.append(source_id)
        if len(source_ids) >= 40:
            return tuple(source_ids)
    return tuple(source_ids)

def _answer_support_selected_source_ref_ids_sample(
    selected: tuple[ContextItem, ...],
) -> tuple[str, ...]:
    source_ids: list[str] = []
    for item in selected:
        if not _answer_support_diversity_family(item):
            continue
        for ref in item.source_refs:
            source_id = str(ref.source_id).strip()
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)
            if len(source_ids) >= 40:
                return tuple(source_ids)
    return tuple(source_ids)

def _answer_support_selected_families_sample(
    selected: tuple[ContextItem, ...],
) -> tuple[str, ...]:
    families: list[str] = []
    for item in selected:
        family = _answer_support_diversity_family(item)
        if family and family not in families:
            families.append(family)
        if len(families) >= 40:
            return tuple(families)
    return tuple(families)

def _ordered_answer_support_families(candidates: dict[str, ContextItem]) -> tuple[str, ...]:
    return _ordered_answer_support_families_for_query(candidates, query="")

def _answer_support_item_limit(candidates: dict[str, ContextItem]) -> int:
    inventory_slots_by_reason: dict[str, set[str]] = {}
    animal_slots_by_reason: dict[str, set[str]] = {}
    common_interest_exact_family_counts_by_reason: dict[str, int] = {}
    exact_marker_reasons: set[str] = set()
    has_pet_acquisition_support = False
    travel_country_exact_family_count = 0
    recommendation_exact_family_count = 0
    for family, item in candidates.items():
        query_reason = _answer_support_query_reason(item)
        if query_reason == "pet_acquisition_date_bridge":
            has_pet_acquisition_support = True
        if is_concrete_recommendation_answer(
            text=item.text,
            query_reason=query_reason,
        ) and _has_any_exact_turn_source_ref(item):
            recommendation_exact_family_count += 1
        if _diversity_family_base(family) == "query_reason_exact_marker_source_group":
            exact_marker_reasons.add(query_reason.replace("_", "-"))
        reason = query_reason.replace("_", "-")
        if (
            reason == "travel-country-inventory-bridge"
            and _travel_country_inventory_slot_for_text(item.text)
            and _has_any_exact_turn_source_ref(item)
        ):
            travel_country_exact_family_count += 1
        if slot := _answer_support_inventory_family_slot(family):
            inventory_slots_by_reason.setdefault(reason, set()).add(slot)
        if animal_slot := _answer_support_animal_evidence_family_slot(family):
            animal_slots_by_reason.setdefault(reason, set()).add(animal_slot)
        if (
            _answer_support_common_interest_family_slot(family)
            and _is_exact_common_interest_answer_support_item(item)
        ):
            common_interest_exact_family_counts_by_reason[reason] = (
                common_interest_exact_family_counts_by_reason.get(reason, 0) + 1
            )
    if "pottery-type-bridge" in exact_marker_reasons:
        return _MAX_INVENTORY_ANSWER_SUPPORT_DIVERSITY_ITEMS
    if has_pet_acquisition_support:
        return _MAX_INVENTORY_ANSWER_SUPPORT_DIVERSITY_ITEMS
    if any(
        count > _MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS
        for count in common_interest_exact_family_counts_by_reason.values()
    ):
        return _MAX_INVENTORY_ANSWER_SUPPORT_DIVERSITY_ITEMS
    if travel_country_exact_family_count > _MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS:
        return _MAX_INVENTORY_ANSWER_SUPPORT_DIVERSITY_ITEMS
    if recommendation_exact_family_count > _MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS:
        return _MAX_INVENTORY_ANSWER_SUPPORT_DIVERSITY_ITEMS
    if any(
        len(slots) > _MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS
        for slots in inventory_slots_by_reason.values()
    ):
        return _MAX_INVENTORY_ANSWER_SUPPORT_DIVERSITY_ITEMS
    if any(
        len(slots) > _MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS
        for slots in animal_slots_by_reason.values()
    ):
        return _MAX_INVENTORY_ANSWER_SUPPORT_DIVERSITY_ITEMS
    return _MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS
