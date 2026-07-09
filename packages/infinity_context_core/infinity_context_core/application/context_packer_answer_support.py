"""Answer-support policy helpers for context packing."""

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
from infinity_context_core.application.context_packer_answer_support_utils import (
    _answer_support_activity_family_slot,
    _answer_support_exact_query_object_hits,
    _artifact_diversity_hint,
    _compound_diversity_family,
    _diagnostic_list,
    _diagnostic_score_signals,
    _diagnostic_signal_text,
    _diagnostic_signal_truthy,
    _diagnostic_text,
    _diversity_family_base,
    _has_any_exact_turn_source_ref,
    _has_primary_exact_turn_source_ref,
    _inventory_first_mention_rank,
    _numeric_signal,
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

_EN_SHARED_VOLUNTEERING_QUERY_RE = re.compile(
    r"\b(?:both|common|shared|mutual)\b(?=.{0,160}\bvolunteer(?:ed|ing|s)?\b)|"
    r"\bvolunteer(?:ed|ing|s)?\b(?=.{0,160}\b(?:both|common|shared|mutual)\b)|"
    r"\bwhat\s+type\s+of\s+volunteering\b",
    re.IGNORECASE | re.DOTALL,
)
_SHARED_VOLUNTEERING_QUERY_REASONS = frozenset(
    {
        "decomposition-inventory-list",
        "volunteering-inventory-bridge",
    }
)
_SHARED_VOLUNTEERING_FIRST_MENTION_SLOTS = frozenset(
    {
        "shelter",
        "shelter_activity",
        "shelter_anchor",
        "shelter_service_activity",
    }
)
_RELATIONSHIP_STATUS_SELF_DISCLOSURE_RE = re.compile(
    r"\b(?:my|our)\s+(?:husband|wife|spouse|boyfriend|girlfriend|fianc[eé]e?|"
    r"romantic\s+partner|life\s+partner)\b|"
    r"\b(?:i|we)\s+(?:got\s+married|am\s+married|are\s+married|was\s+married|"
    r"were\s+married)\b|"
    r"\b(?:i'm|we're)\s+married\b|"
    r"\bwhere\s+i\s+got\s+married\b",
    re.IGNORECASE,
)
_RELATIONSHIP_STATUS_QUESTION_ONLY_RE = re.compile(
    r"\b(?:are\s+you\s+married|have\s+you\s+been\s+married|"
    r"how\s+long\s+have\s+you\s+been\s+married|"
    r"what\s+do\s+you\s+value\s+in\s+your\s+relationship|"
    r"do\s+you\s+have\s+(?:a\s+)?(?:husband|wife|spouse|partner))\?",
    re.IGNORECASE,
)
_NEUTRAL_FIRST_MENTION_RANK = (9999, 9999)


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


def _ordered_answer_support_families_for_query(
    candidates: dict[str, ContextItem],
    *,
    query: str,
) -> tuple[str, ...]:
    marker_source_group_counts = _marker_coverage_source_group_counts(candidates)
    broad_turn_source_group_counts = _broad_turn_source_group_counts(candidates)
    pet_acquisition_named_object_source_groups = (
        _pet_acquisition_named_object_source_groups(
            candidates,
            query=query,
        )
    )
    ordered = tuple(
        sorted(
            candidates,
            key=lambda family: (
                _answer_support_query_focus_priority(
                    family,
                    item=candidates[family],
                    query=query,
                ),
                _answer_support_family_priority(
                    family,
                    item=candidates[family],
                    query=query,
                    marker_source_group_counts=marker_source_group_counts,
                    broad_turn_source_group_counts=broad_turn_source_group_counts,
                    pet_acquisition_named_object_source_groups=(
                        pet_acquisition_named_object_source_groups
                    ),
                ),
                _answer_support_family_item_key_for_query(candidates[family], query=query),
                family,
            ),
        )
    )
    return _round_robin_inventory_slot_families(
        ordered,
        candidates=candidates,
        query=query,
    )


def _answer_support_query_focus_priority(
    family: str,
    *,
    item: ContextItem,
    query: str,
) -> int:
    query_reason = _answer_support_query_reason(item)
    if (
        _recognition_award_visual_answer_rank(
            item,
            query=query,
            query_reason=query_reason,
        )
        == 0
    ):
        return -4
    if recommendation_query_focus_applies(
        text=item.text,
        query=query,
        query_reason=query_reason,
        has_exact_turn=_has_any_exact_turn_source_ref(item),
    ):
        return -3
    if (
        food_inventory_answer_support_applies(
            query=query,
            query_reason=query_reason,
        )
        and food_inventory_answer_support_rank(
            text=item.text,
            query=query,
            query_reason=query_reason,
            has_exact_turn=_has_any_exact_turn_source_ref(item),
        )
        == 0
        and food_inventory_role_alignment_rank(
            text=item.text,
            query=query,
            query_reason=query_reason,
        )
        <= 1
    ):
        return -3
    if (
        query_reason in _DIRECT_EVIDENCE_QUERY_FOCUS_REASONS
        and _has_any_exact_turn_source_ref(item)
        and _precise_answer_content_rank(item, query_reason=query_reason) == 0
    ):
        return -3
    if (
        _diversity_family_base(family)
        in {
            "query_reason_inventory_slot",
            "query_reason_inventory_slot_source_group",
        }
        and _is_cause_inventory_answer_support_item(item)
    ):
        return -4
    if (
        _diversity_family_base(family)
        in {
            "query_reason_animal_evidence_slot",
            "query_reason_animal_evidence_slot_source_group",
        }
        and _has_any_exact_turn_source_ref(item)
    ):
        return -3
    if _is_degree_completion_temporal_answer_support_item(item, query=query):
        return -3
    if _is_exact_business_direct_answer_support_item(item):
        return -3
    if _is_exact_screenplay_rejection_answer_support_item(item):
        return -3
    if _is_exact_common_interest_answer_support_item(item):
        return -3
    if _is_exact_named_preference_answer_support_item(item, query=query):
        return -4
    if _is_exact_place_inference_answer_support_item(item, query=query):
        return -4
    if _is_exact_themed_location_inference_answer_support_item(item, query=query):
        return -4
    if _is_exact_query_destination_answer_support_item(item, query=query):
        return -5
    if _is_exact_country_destination_answer_support_item(item, query=query):
        return -5
    if (
        query_reason == TRAVEL_HOBBY_WRITING_REASON
        and _has_any_exact_turn_source_ref(item)
        and travel_hobby_writing_answer_rank(item.text) <= 1
    ):
        return -6 + travel_hobby_writing_answer_rank(item.text)
    country_destination_rank = _country_destination_answer_support_rank(
        item,
        query=query,
    )
    if country_destination_rank < 5:
        return -4 + country_destination_rank
    if _is_direct_place_area_state_answer_support_item(
        item,
        query=query,
        family=family,
    ):
        return -3
    if _is_state_residence_geo_answer_support_item(item, query=query):
        return -3
    if _is_direct_outdoor_activity_answer_support_item(
        item,
        query=query,
        family=family,
    ):
        return -3
    if (
        query_reason == "item_purchase_bridge"
        and _answer_support_inventory_family_slot(family)
        and has_item_purchase_object_evidence(item.text)
        and _has_any_exact_turn_source_ref(item)
    ):
        return -3
    if (
        _answer_support_query_reason(item).replace("_", "-")
        == "travel-country-inventory-bridge"
        and _travel_country_inventory_slot_for_text(item.text)
        and _has_any_exact_turn_source_ref(item)
    ):
        return -3
    if _is_exact_named_game_inventory_answer_support_item(family, item=item):
        return -3
    if query_reason.replace("_", "-") == "book-reading-list-bridge" and (
        _diversity_family_base(family)
        in {
            "query_reason_marker_coverage_source_group",
            "temporal_source_sibling_marker",
            "temporal_source_sibling_marker_source_group",
        }
    ):
        return 2
    if not query or _MUSIC_EVENT_ATTENDANCE_QUERY_RE.search(query) is None:
        return 0
    query_reason = _answer_support_query_reason(item).replace("_", "-")
    if query_reason not in {
        "classical-music-preference-bridge",
        "music-event-inventory-bridge",
    }:
        return 0
    if _diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
        "query_reason_marker_coverage_source_group",
        "query_reason_source_group",
        "temporal_source_sibling_marker", "temporal_source_sibling_marker_source_group",
    }:
        return 0
    slot = _inventory_answer_slot_for_text(item.text)
    if slot in {"music_live_event", "music_violin_concert"}:
        return -2
    if slot == "music_event":
        return -1
    return 0


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


def _round_robin_inventory_slot_families(
    families: tuple[str, ...],
    *,
    candidates: dict[str, ContextItem],
    query: str = "",
) -> tuple[str, ...]:
    if query and _PLACE_AREA_STATE_QUERY_RE.search(query) is not None:
        return families
    coverage_positions = tuple(
        index
        for index, family in enumerate(families)
        if _answer_support_coverage_family_slot(family)
    )
    if len(coverage_positions) < 3:
        return families
    slot_counts: dict[str, int] = {}
    ranked: list[tuple[int, int, int, str]] = []
    for index in coverage_positions:
        family = families[index]
        slot = _answer_support_coverage_family_slot(family)
        coverage_round = slot_counts.get(slot, 0)
        slot_counts[slot] = coverage_round + 1
        slot_priority = _answer_support_coverage_family_slot_priority(family)
        if (
            slot.startswith("common_interest:")
            and _is_exact_common_interest_answer_support_item(candidates[family])
            and _common_interest_direct_evidence_rank(
                candidates[family],
                query_reason=_answer_support_query_reason(candidates[family]),
            )
            == 0
        ):
            slot_priority -= 2
        if _is_single_exact_cause_inventory_answer_support_item(candidates[family]):
            coverage_round = 0
        elif slot_priority < 0:
            coverage_round = max(0, coverage_round - 2)
        elif slot_priority >= 3:
            coverage_round += 2
        ranked.append((coverage_round, slot_priority, index, family))
    reranked_inventory = iter(family for _, _, _, family in sorted(ranked))
    inventory_position_set = set(coverage_positions)
    return tuple(
        next(reranked_inventory) if index in inventory_position_set else family
        for index, family in enumerate(families)
    )


def _answer_support_coverage_family_slot(family: str) -> str:
    inventory_slot = _answer_support_inventory_family_slot(family)
    if inventory_slot:
        return f"inventory:{inventory_slot}"
    animal_slot = _answer_support_animal_evidence_family_slot(family)
    if animal_slot:
        return f"animal:{animal_slot}"
    common_interest_slot = _answer_support_common_interest_family_slot(family)
    if common_interest_slot:
        return f"common_interest:{common_interest_slot}"
    activity_slot = _answer_support_activity_family_slot(family)
    if activity_slot:
        return f"activity:{activity_slot}"
    career_slot = _answer_support_career_family_slot(family)
    if career_slot:
        return f"career:{career_slot}"
    return ""


def _answer_support_coverage_family_slot_priority(family: str) -> int:
    inventory_slot = _answer_support_inventory_family_slot(family)
    if inventory_slot:
        return _inventory_answer_slot_priority_for_family(
            inventory_slot,
            family=family,
        )
    animal_slot = _answer_support_animal_evidence_family_slot(family)
    if animal_slot:
        return _animal_evidence_answer_slot_priority_for_family(
            animal_slot,
            family=family,
        )
    common_interest_slot = _answer_support_common_interest_family_slot(family)
    if common_interest_slot:
        return _common_interest_answer_slot_priority(common_interest_slot)
    career_slot = _answer_support_career_family_slot(family)
    if career_slot:
        return _career_answer_slot_priority(career_slot)
    return 0


def _answer_support_inventory_family_slot(family: str) -> str:
    if _diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return ""
    return _inventory_answer_slot_from_family(family)


def _answer_support_animal_evidence_family_slot(family: str) -> str:
    if _diversity_family_base(family) not in {
        "query_reason_animal_evidence_slot",
        "query_reason_animal_evidence_slot_source_group",
    }:
        return ""
    return _animal_evidence_answer_slot_from_family(family)


def _answer_support_career_family_slot(family: str) -> str:
    if _diversity_family_base(family) not in {
        "query_reason_career_slot",
        "query_reason_career_slot_marker_source_group",
        "query_reason_career_slot_source_group",
    }:
        return ""
    return _career_answer_slot_from_family(family)


def _answer_support_common_interest_family_slot(family: str) -> str:
    if _diversity_family_base(family) not in {
        "query_reason_common_interest_slot",
        "query_reason_common_interest_slot_source_group",
        "query_reason_common_interest_slot_marker_source_group",
    }:
        return ""
    return _common_interest_answer_slot_from_family(family)


def _relationship_status_answer_support_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if not is_relationship_status_answer_evidence(
        expansion_reason=query_reason,
        text=item.text,
    ):
        return 9
    if query and not _source_sibling_query_person_matches_text(
        expansion_query=query,
        text=item.text,
    ):
        return 8
    answer_rank = relationship_status_answer_rank(item.text)
    if answer_rank >= 9:
        return answer_rank
    if _RELATIONSHIP_STATUS_SELF_DISCLOSURE_RE.search(item.text) is not None:
        return answer_rank
    if _RELATIONSHIP_STATUS_QUESTION_ONLY_RE.search(item.text) is not None:
        return min(8, answer_rank + 5)
    if _has_any_exact_turn_source_ref(item):
        return min(8, answer_rank + 1)
    return min(8, answer_rank + 2)


def _is_relationship_status_direct_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    return (
        _relationship_status_answer_support_rank(
            item,
            query=query,
            query_reason=_answer_support_query_reason(item),
        )
        <= 1
    )


def _answer_support_family_priority(
    family: str,
    *,
    item: ContextItem,
    query: str,
    marker_source_group_counts: dict[str, int],
    broad_turn_source_group_counts: dict[str, int],
    pet_acquisition_named_object_source_groups: frozenset[str] = frozenset(),
) -> int:
    base = _diversity_family_base(family)
    recommendation_priority = recommendation_family_priority(
        text=item.text,
        query=query,
        query_reason=_answer_support_query_reason(item),
    )
    if recommendation_priority is not None:
        return recommendation_priority
    relationship_status_rank = _relationship_status_answer_support_rank(
        item,
        query=query,
        query_reason=_answer_support_query_reason(item),
    )
    if relationship_status_rank < 9:
        return -5 + relationship_status_rank
    if (
        base
        in {
            "query_reason_inventory_slot",
            "query_reason_inventory_slot_source_group",
        }
        and _is_cause_inventory_answer_support_item(item)
    ):
        if _has_primary_exact_turn_source_ref(item) and len(item.source_refs) == 1:
            return -5
        if _has_any_exact_turn_source_ref(item) and len(item.source_refs) == 1:
            return -4
        return -3
    if _is_pet_acquisition_date_anchor_answer_support_item(item):
        if _answer_support_source_group(item) in pet_acquisition_named_object_source_groups:
            return -3
        return -1
    if base in {
        "query_reason_animal_evidence_slot",
        "query_reason_animal_evidence_slot_source_group",
    }:
        return _animal_evidence_answer_slot_priority_for_family(
            _animal_evidence_answer_slot_from_family(family),
            family=family,
        ) - (2 if _has_any_exact_turn_source_ref(item) else 0)
    if _is_exact_named_game_inventory_answer_support_item(family, item=item):
        return -3
    if _is_exact_named_preference_answer_support_item(item, query=query):
        return -4
    if _is_exact_place_inference_answer_support_item(item, query=query):
        return -4
    if _is_exact_themed_location_inference_answer_support_item(item, query=query):
        return -4
    if _is_exact_query_destination_answer_support_item(item, query=query):
        return -5
    if _is_exact_country_destination_answer_support_item(item, query=query):
        return -5
    country_destination_rank = _country_destination_answer_support_rank(
        item,
        query=query,
    )
    if country_destination_rank < 5:
        return -4 + country_destination_rank
    if _is_exact_business_direct_answer_support_item(item):
        return -3
    if base in {
        "query_reason_common_interest_slot",
        "query_reason_common_interest_slot_source_group",
        "query_reason_common_interest_slot_marker_source_group",
    }:
        slot_priority = _common_interest_answer_slot_priority(
            _common_interest_answer_slot_from_family(family)
        )
        direct_evidence_adjustment = (
            3
            if (
                _is_exact_common_interest_answer_support_item(item)
                and _common_interest_direct_evidence_rank(
                    item,
                    query_reason=_answer_support_query_reason(item),
                )
                == 0
            )
            else 0
        )
        return (
            slot_priority
            - (2 if _has_any_exact_turn_source_ref(item) else 1)
            - direct_evidence_adjustment
        )
    if _answer_support_exact_query_object_hits(item, query=query):
        return -1
    if _is_degree_completion_temporal_answer_support_item(item, query=query):
        return -3
    if _is_state_residence_geo_answer_support_item(item, query=query):
        return -3
    if _is_exact_precise_content_answer_support_item(item):
        return -2
    if base in {
        "temporal_source_sibling_marker",
        "temporal_source_sibling_marker_source_group",
    }:
        return 2
    if base == "query_reason_count_coverage_source_group":
        return 0
    if (
        base == "query_reason_broad_turn_source_group"
        and _numeric_signal(
            _diagnostic_score_signals(item).get("book_author_preference_world_evidence")
        )
        >= 3
        and broad_turn_source_group_counts.get(_broad_turn_family_source_group(family), 0) > 1
    ):
        return 0
    if base in {
        "query_reason_activity_slot",
        "query_reason_activity_slot_source_group",
    }:
        if _answer_support_query_reason(item) in {
            "art_style_bridge",
            "painting_inventory_bridge",
        }:
            return _inventory_answer_slot_priority_for_family(
                _answer_support_activity_family_slot(family),
                family=family,
            )
        return 0
    if base == "query_reason_exact_marker_source_group" and _is_conversational_support_turn(
        item
    ):
        return 0
    if base == "query_reason_exact_marker_source_group":
        return 2
    query_reason = _answer_support_query_reason(item)
    if query_reason == "support_origin_bridge":
        if _precise_answer_content_rank(item, query_reason=query_reason) == 0:
            return -5 if _has_any_exact_turn_source_ref(item) else -3
        return -1
    if (
        query_reason == "support_career_motivation_bridge"
        and _precise_answer_content_rank(item, query_reason=query_reason) == 0
    ):
        return 0
    if (
        _is_support_network_reason(query_reason)
        and _support_network_answer_object_rank(item.text) == 0
    ):
        return 0
    if (
        base == "query_reason_broad_turn_source_group"
        and query_reason == "birdwatching_city_schedule_bridge"
    ):
        return 0
    if _is_pottery_type_reason(query_reason) and base in {
        "query_reason",
        "query_reason_marker_coverage_source_group",
        "query_reason_source_group",
    }:
        return -4
    if (
        base == "query_reason_marker_coverage_source_group"
        and _is_pottery_type_inventory_item(item, query_reason=query_reason)
    ):
        return -4
    if (
        base
        in {
            "query_reason_inventory_slot",
            "query_reason_inventory_slot_source_group",
        }
        and _place_area_state_query_applies(query=query, query_reason=query_reason)
    ):
        return _place_area_state_answer_support_rank(
            item,
            query=query,
            query_reason=query_reason,
        )
    if base in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        if query_reason == TRAVEL_HOBBY_WRITING_REASON:
            return travel_hobby_writing_answer_rank(item.text) - (
                3 if _has_any_exact_turn_source_ref(item) else 0
            )
        return _inventory_answer_slot_priority_for_family(
            _inventory_answer_slot_from_family(family),
            family=family,
        )
    if base in {
        "query_reason_career_slot",
        "query_reason_career_slot_marker_source_group",
        "query_reason_career_slot_source_group",
    }:
        slot_priority = _career_answer_slot_priority(_career_answer_slot_from_family(family))
        if _precise_answer_content_rank(item, query_reason=query_reason) == 0:
            if _has_primary_exact_turn_source_ref(item) and len(item.source_refs) == 1:
                return slot_priority - 4
            if _has_any_exact_turn_source_ref(item):
                return slot_priority - 3
        return slot_priority
    if base == "query_reason_marker_coverage_source_group":
        if _is_family_activity_reason(query_reason):
            return 4
        if (
            query_reason == "decomposition_inventory_list"
            and _pottery_type_answer_content_rank(item.text) <= 3
        ):
            return 0
        answer_object_rank = _answer_object_rank(
            item,
            query_reason=query_reason,
        )
        if query_reason == "book_reading_list_bridge":
            if (
                _book_reading_answer_content_rank(item.text) <= 1
                and answer_object_rank <= 1
            ):
                return 2 + answer_object_rank
            return 6
        if answer_object_rank <= 1:
            return 1 + answer_object_rank
        source_group = _marker_coverage_family_source_group(family)
        if marker_source_group_counts.get(source_group, 0) > 1:
            return min(answer_object_rank + 1, 3)
        return min(answer_object_rank + 2, 5)
    return 2


def _is_exact_conversational_support_family(family: str, *, item: ContextItem) -> bool:
    return (
        _diversity_family_base(family) == "query_reason_exact_marker_source_group"
        and _is_conversational_support_turn(item)
    )


def _is_exact_named_game_inventory_answer_support_item(
    family: str,
    *,
    item: ContextItem,
) -> bool:
    query_reason = _answer_support_query_reason(item)
    if query_reason != "board_game_inventory_bridge":
        return False
    if _diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return False
    return (
        _inventory_answer_slot(item, query_reason=query_reason).startswith("game_named_")
        and _has_any_exact_turn_source_ref(item)
    )


def _is_exact_animal_evidence_answer_family(
    family: str,
    *,
    item: ContextItem,
) -> bool:
    return bool(_answer_support_animal_evidence_family_slot(family)) and (
        _has_any_exact_turn_source_ref(item)
    )


def _is_exact_temporal_query_object_family(
    family: str,
    *,
    item: ContextItem,
    query: str,
) -> bool:
    query_reason = _answer_support_query_reason(item)
    base = _diversity_family_base(family)
    if _is_degree_completion_temporal_answer_support_item(item, query=query):
        return True
    if (
        base
        in {
            "query_reason_source_group",
            "query_reason_activity_slot_source_group",
            "query_reason_inventory_slot_source_group",
        }
        and _answer_support_exact_query_object_hits(item, query=query) > 0
        and _has_any_exact_turn_source_ref(item)
    ):
        return True
    return (
        _TEMPORAL_ANSWER_SUPPORT_QUERY_RE.search(query) is not None
        and base in {
            "temporal_source_sibling_marker",
            "temporal_source_sibling_marker_source_group",
            "query_reason_source_group",
        }
        and _temporal_answer_support_query_object_hits(
            item,
            query=query,
            query_reason=query_reason,
        )
        > 0
        and _has_any_exact_turn_source_ref(item)
    )


def _is_degree_completion_temporal_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query:
        return False
    if _DEGREE_COMPLETION_TEMPORAL_QUERY_RE.search(query) is None:
        return False
    if _answer_support_query_reason(item) != "degree_policy_inference_bridge":
        return False
    if _degree_policy_answer_slot(item.text) != "degree_completion_context":
        return False
    return _has_any_exact_turn_source_ref(item)


def _is_exact_precise_content_answer_support_item(item: ContextItem) -> bool:
    if not _has_any_exact_turn_source_ref(item):
        return False
    query_reason = _answer_support_query_reason(item)
    if query_reason not in _EXACT_PRECISE_CONTENT_TURN_REASONS:
        return False
    return _precise_answer_content_rank(item, query_reason=query_reason) == 0


def _is_exact_named_preference_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query or not _has_any_exact_turn_source_ref(item):
        return False
    query_reason = _answer_support_query_reason(item)
    if query_reason.replace("_", "-") not in {
        "decomposition-inference-support",
        "original-query",
    }:
        return False
    if (
        _numeric_signal(_diagnostic_score_signals(item).get("source_sibling_answer_evidence"))
        <= 0
    ):
        return False
    return is_named_preference_source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason=query_reason,
        text=item.text,
    )


def _is_exact_place_inference_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query or not _has_any_exact_turn_source_ref(item):
        return False
    query_reason = _answer_support_query_reason(item)
    return is_place_inference_source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason=query_reason,
        text=item.text,
    )


def _is_exact_themed_location_inference_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query or not _has_any_exact_turn_source_ref(item):
        return False
    query_reason = _answer_support_query_reason(item)
    return is_themed_location_source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason=query_reason,
        text=item.text,
    )


def _is_exact_query_destination_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query or not _has_any_exact_turn_source_ref(item):
        return False
    query_reason = _answer_support_query_reason(item).replace("_", "-")
    if query_reason not in {
        "decomposition-inference-support",
        "original-query",
        "place-area-inventory-bridge",
        "themed-location-destination-anchor-bridge",
        "themed-location-destination-bridge",
        "travel-country-inventory-bridge",
        "trip-destination-bridge",
    }:
        return False
    if not query_destination_places(query):
        return False
    return is_query_destination_source_sibling_anchor(
        expansion_query=query,
        expansion_reason=query_reason,
        text=item.text,
    )


def _is_exact_country_destination_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query or not _has_any_exact_turn_source_ref(item):
        return False
    return is_country_destination_source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason=_answer_support_query_reason(item),
        text=item.text,
    )


def _country_destination_answer_support_rank(
    item: ContextItem,
    *,
    query: str,
) -> int:
    if not query:
        return 5
    return country_destination_answer_support_rank(
        expansion_query=query,
        text=item.text,
        has_exact_turn=_has_any_exact_turn_source_ref(item),
    )


def _is_exact_business_direct_answer_support_item(item: ContextItem) -> bool:
    return (
        _answer_support_query_reason(item)
        in {"business_commonality_bridge", "business_start_reason_bridge"}
        and _has_any_exact_turn_source_ref(item)
        and _business_commonality_answer_content_rank(item.text) == 0
    )


def _is_exact_screenplay_rejection_answer_support_item(item: ContextItem) -> bool:
    return (
        _answer_support_query_reason(item) == "screenplay_count_bridge"
        and _has_any_exact_turn_source_ref(item)
        and _screenplay_rejection_answer_content_rank(item.text) == 0
    )


def _is_exact_common_interest_answer_support_item(item: ContextItem) -> bool:
    query_reason = _answer_support_query_reason(item)
    return (
        _is_common_interest_answer_reason(query_reason)
        and _has_primary_exact_turn_source_ref(item)
        and bool(_common_interest_answer_slot(item, query_reason=query_reason))
    )


def _is_exact_place_area_state_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    query_reason = _answer_support_query_reason(item)
    if _is_state_residence_geo_answer_support_item(item, query=query):
        return True
    return (
        _place_area_state_query_applies(query=query, query_reason=query_reason)
        and _has_any_exact_turn_source_ref(item)
        and _place_area_state_answer_support_rank(
            item,
            query=query,
            query_reason=query_reason,
        )
        == 0
    )


def _is_exact_inspiration_source_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    return (
        bool(query and _INSPIRATION_SOURCE_QUERY_RE.search(query))
        and _has_any_exact_turn_source_ref(item)
        and _inspiration_source_answer_content_rank(item.text) == 0
    )


def _marker_coverage_source_group_counts(candidates: dict[str, ContextItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for family in candidates:
        if _diversity_family_base(family) != "query_reason_marker_coverage_source_group":
            continue
        source_group = _marker_coverage_family_source_group(family)
        if source_group:
            counts[source_group] = counts.get(source_group, 0) + 1
    return counts


def _broad_turn_source_group_counts(candidates: dict[str, ContextItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for family in candidates:
        if _diversity_family_base(family) != "query_reason_broad_turn_source_group":
            continue
        source_group = _broad_turn_family_source_group(family)
        if source_group:
            counts[source_group] = counts.get(source_group, 0) + 1
    return counts


def _broad_turn_family_source_group(family: str) -> str:
    parts = family.split(":")
    if len(parts) >= 4:
        return parts[-1]
    return ""


def _pet_acquisition_named_object_source_groups(
    candidates: dict[str, ContextItem],
    *,
    query: str,
) -> frozenset[str]:
    object_terms = _pet_acquisition_named_object_terms(query)
    if not object_terms:
        return frozenset()
    source_groups: set[str] = set()
    for item in candidates.values():
        if _answer_support_query_reason(item) != "pet_acquisition_date_bridge":
            continue
        source_group = _answer_support_source_group(item)
        if not source_group:
            continue
        text = item.text.casefold()
        if any(re.search(rf"\b{re.escape(term)}\b", text) for term in object_terms):
            source_groups.add(source_group)
    return frozenset(source_groups)


def _pet_acquisition_named_object_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in _NAMED_ACQUISITION_OBJECT_QUERY_RE.finditer(query):
        term = match.group("object").strip().casefold()
        if term and term not in terms:
            terms.append(term)
    return tuple(terms)


def _marker_coverage_family_source_group(family: str) -> str:
    parts = family.split(":")
    if len(parts) >= 4:
        return parts[-1]
    return ""


def _answer_support_source_group_reason_key(family: str) -> str:
    parts = family.split(":")
    if len(parts) < 3 or parts[0] not in {
        "query_reason_activity_slot_source_group",
        "query_reason_broad_turn_source_group",
        "query_reason_career_slot_marker_source_group",
        "query_reason_career_slot_source_group",
        "query_reason_common_interest_slot_marker_source_group",
        "query_reason_common_interest_slot_source_group",
        "query_reason_count_coverage_source_group",
        "query_reason_exact_marker_source_group",
        "query_reason_inference_slot_source_group",
        "query_reason_inventory_slot_source_group",
        "query_reason_marker_coverage_source_group",
        "query_reason_source_group",
    }:
        return ""
    if (
        parts[0] == "query_reason_activity_slot_source_group"
        and len(parts) >= 4
        and (
            _is_family_activity_reason(parts[1])
        )
    ):
        return f"{parts[1]}:{parts[2]}"
    if parts[0] == "query_reason_inventory_slot_source_group" and len(parts) >= 4:
        return f"{parts[1]}:{parts[2]}"
    if (
        parts[0]
        in {
            "query_reason_common_interest_slot_source_group",
            "query_reason_common_interest_slot_marker_source_group",
        }
        and len(parts) >= 4
    ):
        return f"{parts[1]}:{parts[2]}"
    return parts[1]


def _answer_support_source_group_limit(
    reason: str,
    *,
    family: str,
    item: ContextItem,
) -> int:
    if _is_count_aggregation_reason(reason):
        return _MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS
    normalized_reason = reason.replace("_", "-")
    base_reason = normalized_reason.split(":", 1)[0]
    if base_reason in {
        "cause-event-inventory-bridge",
        "cause-education-infrastructure-inventory-bridge",
        "cause-veterans-inventory-bridge",
    }:
        return _MAX_ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON
    if base_reason == "decomposition-inventory-list":
        parts = normalized_reason.split(":")
        if len(parts) >= 2 and parts[1] in {
            "dessert",
            "dessert-cobbler",
            "dessert-pie",
            "dessert-sundae",
            "animal-shelter",
            "shelter",
            "shelter-activity",
            "shelter-anchor",
            "shelter-service-activity",
        }:
            return _MAX_ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON
    family_base = _diversity_family_base(family)
    aggregation_family_bases = {
        "query_reason_activity_slot_source_group",
        "query_reason_broad_turn_source_group",
        "query_reason_career_slot_marker_source_group",
        "query_reason_career_slot_source_group",
        "query_reason_common_interest_slot_marker_source_group",
        "query_reason_common_interest_slot_source_group",
        "query_reason_count_coverage_source_group",
        "query_reason_exact_marker_source_group",
        "query_reason_inference_slot_source_group",
        "query_reason_inventory_slot_source_group",
        "query_reason_marker_coverage_source_group",
    }
    if (
        (
            reason in _ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS
            or normalized_reason in _ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS
        )
        and (
            family_base in aggregation_family_bases
            or (item.source_refs and family_base == "query_reason_source_group")
        )
    ):
        return _MAX_ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON
    if (
        reason.startswith("decomposition-")
        and reason.endswith("-event")
        and reason not in {"decomposition-event-context", "decomposition-event-sequence"}
    ):
        return _MAX_ANSWER_SUPPORT_EVENT_SLOT_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON
    return _MAX_ANSWER_SUPPORT_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON


def _is_count_aggregation_reason(reason: str) -> bool:
    normalized_reason = reason.replace("-", "_")
    return reason in _COUNT_AGGREGATION_COVERAGE_REASONS or (
        normalized_reason in _COUNT_AGGREGATION_COVERAGE_REASONS
    )


def _answer_support_diversity_family(item: ContextItem) -> str:
    query_reason = _answer_support_query_reason(item)
    if _is_temporal_answer_support_item(item, query_reason=query_reason):
        source_group = _answer_support_source_group(item)
        marker = _primary_exact_turn_marker(item) or _first_dialogue_marker(item.text)
        if source_group:
            return _compound_diversity_family(
                "temporal_source_sibling_marker_source_group",
                marker or "temporal",
                source_group,
            )
        return _compound_diversity_family(
            "temporal_source_sibling_marker",
            marker or item.item_id,
        )

    if query_reason and query_reason != "original_query":
        if query_reason in _ANSWER_SUPPORT_EXCLUDED_QUERY_REASONS:
            return ""
        source_group = _answer_support_source_group(item)
        career_slot = _career_answer_slot(item, query_reason=query_reason)
        activity_slot = _activity_answer_slot(item, query_reason=query_reason)
        inference_slot = _inference_answer_slot(item, query_reason=query_reason)
        inventory_slot = _inventory_answer_slot(item, query_reason=query_reason)
        animal_evidence_slot = _animal_evidence_answer_slot(
            item,
            query_reason=query_reason,
        )
        common_interest_slot = _common_interest_answer_slot(
            item,
            query_reason=query_reason,
        )
        exact_support_marker = _exact_answer_support_marker_slot(
            item,
            query_reason=query_reason,
        )
        if source_group:
            if exact_support_marker and _exact_marker_should_precede_inventory(
                item,
                marker=exact_support_marker,
            ):
                return _compound_diversity_family(
                    "query_reason_exact_marker_source_group",
                    query_reason,
                    exact_support_marker,
                    source_group,
                )
            if broad_turn_slot := _broad_evidence_turn_slot(item, query_reason=query_reason):
                return _compound_diversity_family(
                    "query_reason_broad_turn_source_group",
                    query_reason,
                    broad_turn_slot,
                    source_group,
                )
            if _is_count_aggregation_coverage_item(item, query_reason=query_reason):
                return _compound_diversity_family(
                    "query_reason_count_coverage_source_group",
                    query_reason,
                    source_group,
                )
            if common_interest_slot and not (
                query_reason == "hobby_interest_bridge" and animal_evidence_slot
            ):
                marker = _primary_exact_turn_marker(item)
                if marker:
                    return _compound_diversity_family(
                        "query_reason_common_interest_slot_marker_source_group",
                        query_reason,
                        common_interest_slot,
                        marker,
                        source_group,
                    )
                return _compound_diversity_family(
                    "query_reason_common_interest_slot_source_group",
                    query_reason,
                    common_interest_slot,
                    source_group,
                )
            if animal_evidence_slot:
                return _compound_diversity_family(
                    "query_reason_animal_evidence_slot_source_group",
                    query_reason,
                    animal_evidence_slot,
                    source_group,
                )
            if inventory_slot and _inventory_slot_precedes_marker_coverage(
                inventory_slot,
            ):
                return _compound_diversity_family(
                    "query_reason_inventory_slot_source_group",
                    query_reason,
                    inventory_slot,
                    source_group,
                )
            if marker_slot := _aggregation_marker_coverage_slot(
                item,
                query_reason=query_reason,
            ):
                return _compound_diversity_family(
                    "query_reason_marker_coverage_source_group",
                    query_reason,
                    marker_slot,
                    source_group,
                )
            if inventory_slot:
                return _compound_diversity_family(
                    "query_reason_inventory_slot_source_group",
                    query_reason,
                    inventory_slot,
                    source_group,
                )
            if exact_support_marker:
                return _compound_diversity_family(
                    "query_reason_exact_marker_source_group",
                    query_reason,
                    exact_support_marker,
                    source_group,
                )
            if activity_slot:
                return _compound_diversity_family(
                    "query_reason_activity_slot_source_group",
                    query_reason,
                    activity_slot,
                    source_group,
                )
            if career_slot:
                marker = _primary_exact_turn_marker(item)
                if marker and not _is_business_commonality_reason(query_reason):
                    return _compound_diversity_family(
                        "query_reason_career_slot_marker_source_group",
                        query_reason,
                        career_slot,
                        marker,
                        source_group,
                    )
                return _compound_diversity_family(
                    "query_reason_career_slot_source_group",
                    query_reason,
                    career_slot,
                    source_group,
                )
            if inference_slot:
                return _compound_diversity_family(
                    "query_reason_inference_slot_source_group",
                    query_reason,
                    inference_slot,
                    source_group,
                )
            if _diagnostic_signal_truthy(item, "source_sibling_dialogue_visual_reference"):
                return _compound_diversity_family(
                    "query_reason_source_group_visual_reference",
                    query_reason,
                    source_group,
                )
            return _compound_diversity_family(
                "query_reason_source_group",
                query_reason,
                source_group,
            )
        if activity_slot:
            return _compound_diversity_family(
                "query_reason_activity_slot",
                query_reason,
                activity_slot,
            )
        if common_interest_slot and not (
            query_reason == "hobby_interest_bridge" and animal_evidence_slot
        ):
            return _compound_diversity_family(
                "query_reason_common_interest_slot",
                query_reason,
                common_interest_slot,
            )
        if animal_evidence_slot:
            return _compound_diversity_family(
                "query_reason_animal_evidence_slot",
                query_reason,
                animal_evidence_slot,
            )
        if inventory_slot:
            return _compound_diversity_family(
                "query_reason_inventory_slot",
                query_reason,
                inventory_slot,
            )
        if career_slot:
            return _compound_diversity_family(
                "query_reason_career_slot",
                query_reason,
                career_slot,
            )
        if inference_slot:
            return _compound_diversity_family(
                "query_reason_inference_slot",
                query_reason,
                inference_slot,
            )
        return _typed_diversity_family("query_reason", query_reason)
    if (
        _has_any_exact_turn_source_ref(item)
        and _numeric_signal(
            _diagnostic_score_signals(item).get("source_sibling_answer_evidence")
        )
        > 0
    ):
        source_group = _answer_support_source_group(item)
        if source_group:
            return _compound_diversity_family(
                "query_reason_source_group",
                "source_sibling_answer_evidence",
                source_group,
            )
    matched_anchor_kinds = _diagnostic_list(item, "context_requirement_matched_anchor_kinds")
    if matched_anchor_kinds:
        return _typed_diversity_family("requirement_anchor", matched_anchor_kinds[0])

    matched_modalities = _diagnostic_list(item, "context_requirement_matched_modalities")
    if matched_modalities:
        return _typed_diversity_family("requirement_modality", matched_modalities[0])

    if _is_weak_vector_requirement_candidate(item):
        return ""

    matched_features = _diagnostic_list(item, "context_requirement_matched_evidence_features")
    if matched_features:
        return _typed_diversity_family("requirement_feature", matched_features[0])

    return ""


def _inventory_slot_precedes_marker_coverage(slot: str) -> bool:
    return slot in {
        "game_win_result",
        "gratitude_note_writer",
        "shelter_food_dropoff",
        "skill_game_coaching",
        "skill_recipe_teaching",
    }


def _is_weak_vector_requirement_candidate(item: ContextItem) -> bool:
    retrieval_sources = set(diagnostic_retrieval_sources(item.diagnostics))
    if retrieval_sources != {"vector_chunks"}:
        return False
    signals = _diagnostic_score_signals(item)
    return (
        _numeric_signal(signals.get("unique_term_hits")) <= 0
        and _numeric_signal(signals.get("distinctive_term_hits")) <= 0
        and _numeric_signal(signals.get("phrase_bigram_hits")) <= 0
    )


def _first_dialogue_marker(text: str) -> str:
    match = _DIALOGUE_MARKER_RE.search(text)
    return match.group(0) if match is not None else ""
def _primary_exact_turn_marker(item: ContextItem) -> str:
    source_id = _primary_exact_turn_source_id(item)
    match = _DIALOGUE_MARKER_RE.search(source_id)
    return match.group(0) if match is not None else ""
def _exact_marker_should_precede_inventory(item: ContextItem, *, marker: str) -> bool:
    if len(item.source_refs) != 1:
        return False
    first_marker = _first_dialogue_marker(item.text)
    return bool(first_marker and marker and first_marker != marker)


def _answer_support_query_reason(item: ContextItem) -> str:
    query_reason = _diagnostic_signal_text(item, "query_expansion_reason")
    deterministic_reason = _diagnostic_signal_text(item, "deterministic_rerank_query_reason")
    if (
        deterministic_reason
        and deterministic_reason != "original_query"
        and query_reason
        in {
            "decomposition_evidence_reason",
            "decomposition_inference_support",
        }
    ):
        return deterministic_reason
    return (
        query_reason
        or _diagnostic_signal_text(item, "bm25_lexical_query_reason")
        or deterministic_reason
    )


def _answer_support_source_group(item: ContextItem) -> str:
    aggregation_source_group = _diagnostic_text(item, "keyword_aggregation_source_group")
    if aggregation_source_group:
        return aggregation_source_group
    if set(diagnostic_retrieval_sources(item.diagnostics)).intersection(
        {
            "keyword_aggregation_chunks",
            "keyword_source_sibling_chunks",
        }
    ):
        return _source_group_key(item)
    if _has_derived_source_group_ref(item):
        return _source_group_key(item)
    return ""


def _exact_answer_support_marker_slot(item: ContextItem, *, query_reason: str) -> str:
    if not _is_pottery_type_reason(query_reason):
        return ""
    if (
        _numeric_signal(_diagnostic_score_signals(item).get("source_sibling_answer_evidence")) <= 0
        and "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics)
    ):
        return ""
    marker = _primary_exact_turn_marker(item)
    if not marker:
        return ""
    if re.search(rf"\b{re.escape(marker)}\b", item.text) is None:
        return ""
    return marker

def _has_derived_source_group_ref(item: ContextItem) -> bool:
    if not item.source_refs:
        return False
    source_group_key = _source_group_key(item)
    return source_group_key != _source_key(item)


def _is_exact_cause_inventory_answer_support_item(item: ContextItem) -> bool:
    if not _has_any_exact_turn_source_ref(item):
        return False
    return _is_cause_inventory_answer_support_item(item)


def _is_single_exact_cause_inventory_answer_support_item(item: ContextItem) -> bool:
    return (
        len(item.source_refs) == 1
        and _has_primary_exact_turn_source_ref(item)
        and _is_cause_inventory_answer_support_item(item)
    )


def _is_cause_inventory_answer_support_item(item: ContextItem) -> bool:
    query_reason = _answer_support_query_reason(item)
    if query_reason not in {
        "cause_event_inventory_bridge",
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
    }:
        return False
    return bool(_inventory_answer_slot(item, query_reason=query_reason))


def _answer_support_family_item_key(item: ContextItem) -> tuple[float | int | str, ...]:
    return _answer_support_family_item_key_for_query(item, query="")


def _answer_support_family_item_key_for_query(
    item: ContextItem,
    *,
    query: str,
) -> tuple[float | int | str, ...]:
    signals = _diagnostic_score_signals(item)
    query_reason = _answer_support_query_reason(item)
    if _is_count_aggregation_coverage_item(item, query_reason=query_reason):
        signal_rank = (
            -_numeric_signal(signals.get("item_purchase_object_evidence")),
            -_numeric_signal(signals.get("symbol_importance_visual_evidence")),
            -_numeric_signal(signals.get("friend_place_shelter_anchor_evidence")),
            -_numeric_signal(signals.get("cause_awareness_answer_evidence")),
            -_numeric_signal(signals.get("choice_reason_answer_evidence")),
            -_numeric_signal(signals.get("future_plan_timing_answer_evidence")),
            -_numeric_signal(signals.get("birdwatching_city_schedule_answer_evidence")),
            -_numeric_signal(signals.get("source_sibling_answer_evidence")),
            -_numeric_signal(signals.get("distinctive_term_hits")),
            -_numeric_signal(signals.get("phrase_bigram_hits")),
        )
    else:
        signal_rank = (
            -_numeric_signal(signals.get("item_purchase_object_evidence")),
            -_numeric_signal(signals.get("symbol_importance_visual_evidence")),
            -_numeric_signal(signals.get("friend_place_shelter_anchor_evidence")),
            -_numeric_signal(signals.get("cause_awareness_answer_evidence")),
            -_numeric_signal(signals.get("choice_reason_answer_evidence")),
            -_numeric_signal(signals.get("future_plan_timing_answer_evidence")),
            -_numeric_signal(signals.get("birdwatching_city_schedule_answer_evidence")),
            -_numeric_signal(signals.get("source_sibling_answer_evidence")),
            -_numeric_signal(signals.get("phrase_bigram_hits")),
            -_numeric_signal(signals.get("distinctive_term_hits")),
        )
    exact_alignment_slot = _inventory_answer_slot(item, query_reason=query_reason)
    exact_alignment_slot_detector = _inventory_answer_slot_for_text
    if not exact_alignment_slot:
        exact_alignment_slot = _animal_evidence_answer_slot(
            item,
            query_reason=query_reason,
        )

        def exact_alignment_slot_detector(text: str) -> str:
            return _animal_evidence_slot_for_text(
                text,
                query_reason=query_reason,
            )

    return (
        _degree_completion_temporal_answer_support_rank(item, query=query),
        _common_interest_animal_answer_shape_rank(
            item,
            query=query,
            query_reason=query_reason,
        ),
        _common_interest_direct_evidence_rank(
            item,
            query_reason=query_reason,
        ),
        _common_interest_movie_seen_query_rank(
            item,
            query=query,
            query_reason=query_reason,
        ),
        _common_interest_first_mention_rank(
            item,
            query=query,
            query_reason=query_reason,
        ),
        _shared_volunteering_first_mention_rank(
            item,
            query=query,
            query_reason=query_reason,
        ),
        _recognition_award_visual_answer_rank(
            item,
            query=query,
            query_reason=query_reason,
        ),
        _activity_competition_visual_answer_rank(
            item,
            query=query,
            query_reason=query_reason,
        ),
        recommendation_list_answer_support_rank(
            text=item.text,
            query_reason=query_reason,
        ),
        recommendation_role_alignment_rank(
            text=item.text,
            query=query,
            query_reason=query_reason,
        ),
        _relationship_status_answer_support_rank(
            item,
            query=query,
            query_reason=query_reason,
        ),
        food_inventory_answer_support_rank(
            text=item.text,
            query=query,
            query_reason=query_reason,
            has_exact_turn=_has_any_exact_turn_source_ref(item),
        ),
        food_inventory_role_alignment_rank(
            text=item.text,
            query=query,
            query_reason=query_reason,
        ),
        _career_exact_turn_answer_support_rank(item, query_reason=query_reason),
        -_answer_support_exact_query_object_hits(item, query=query),
        _answer_support_exact_turn_alignment_rank(
            text=item.text,
            source_ids=tuple(str(ref.source_id) for ref in item.source_refs),
            inventory_slot=exact_alignment_slot,
            slot_detector=exact_alignment_slot_detector,
            query_reason=query_reason,
        ),
        _place_area_state_answer_support_rank(
            item,
            query=query,
            query_reason=query_reason,
        ),
        _country_destination_answer_support_rank(item, query=query),
        _state_residence_answer_support_rank(
            item,
            query=query,
            query_reason=query_reason,
        ),
        _business_dialogue_marker_answer_support_rank(item, query_reason=query_reason),
        _common_interest_answer_support_rank(item, query_reason=query_reason),
        _precise_turn_answer_support_rank(item, query_reason=query_reason),
        _pet_acquisition_date_anchor_answer_support_rank(
            item,
            query_reason=query_reason,
        ),
        _precise_answer_content_rank(item, query_reason=query_reason),
        _answer_object_rank(item, query_reason=query_reason),
        _marker_coverage_answer_support_rank(item, query_reason=query_reason),
        _birdwatching_city_schedule_exact_turn_rank(item, query_reason=query_reason),
        -_temporal_answer_support_query_object_hits(
            item,
            query=query,
            query_reason=query_reason,
        ),
        _temporal_answer_support_source_span_rank(item, query_reason=query_reason),
        _inventory_first_mention_rank(
            source_id=_primary_exact_turn_source_id(item),
            query=query,
            enabled=(
                _is_community_participation_reason(query_reason)
                or _is_business_commonality_reason(query_reason)
                or (
                    query_reason.replace("_", "-") == "destress-activity-bridge"
                    and _precise_answer_content_rank(item, query_reason=query_reason) == 0
                )
            ),
        ),
        -len(item.source_refs),
        *signal_rank,
        -len(diagnostic_retrieval_sources(item.diagnostics)),
        context_rank_key(item),
    )


def _common_interest_first_mention_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> tuple[int, int]:
    return _inventory_first_mention_rank(
        source_id=_primary_exact_turn_source_id(item),
        query=query,
        enabled=(
            _is_common_interest_answer_reason(query_reason)
            and _is_exact_common_interest_answer_support_item(item)
        ),
    )


def _shared_volunteering_first_mention_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> tuple[int, int]:
    if (
        query_reason.replace("_", "-") not in _SHARED_VOLUNTEERING_QUERY_REASONS
        or _EN_SHARED_VOLUNTEERING_QUERY_RE.search(query) is None
    ):
        return _NEUTRAL_FIRST_MENTION_RANK
    slot = _inventory_answer_slot(item, query_reason=query_reason).replace("-", "_")
    if slot not in _SHARED_VOLUNTEERING_FIRST_MENTION_SLOTS:
        return _NEUTRAL_FIRST_MENTION_RANK
    return _inventory_first_mention_rank(
        source_id=_primary_exact_turn_source_id(item),
        query=query,
        enabled=True,
    )


def _career_exact_turn_answer_support_rank(
    item: ContextItem,
    *,
    query_reason: str,
) -> int:
    if not _career_answer_slot(item, query_reason=query_reason):
        return 0
    if _has_primary_exact_turn_source_ref(item) and len(item.source_refs) == 1:
        return 0
    if _has_any_exact_turn_source_ref(item):
        return 1
    return 2


def _recognition_award_visual_answer_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if query_reason != "recognition_award_bridge":
        return 1
    if _RECOGNITION_CERTIFICATE_QUERY_RE.search(query) is None:
        return 1
    if not _has_any_exact_turn_source_ref(item):
        return 1
    return 0 if _RECOGNITION_CERTIFICATE_VISUAL_ANSWER_RE.search(item.text) else 1


def _common_interest_movie_seen_query_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if not (
        _is_common_interest_answer_reason(query_reason)
        and _COMMON_INTEREST_MOVIE_SEEN_QUERY_RE.search(query) is not None
    ):
        return 0
    text = item.text
    if _COMMON_INTEREST_MOVIE_SEEN_SLOT_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_MOVIE_QUESTION_ONLY_RE.search(text) is not None:
        return 4
    if _COMMON_INTEREST_MOVIE_SLOT_RE.search(text) is not None:
        return 2
    return 5


_COMMON_INTEREST_ANIMAL_ANSWER_QUERY_RE = re.compile(
    r"\b(?:what|which)\s+animals?\b|"
    r"\banimals?\b(?=.{0,140}\b(?:both|same|shared|share|like|likes|"
    r"love|loves|enjoy|enjoys|prefer|prefers)\b)|"
    r"\b(?:both|same|shared|share|like|likes|love|loves|enjoy|enjoys|"
    r"prefer|prefers)\b(?=.{0,140}\banimals?\b)",
    re.IGNORECASE | re.DOTALL,
)
_COMMON_INTEREST_EXPLICIT_ANIMAL_CHOICE_RE = re.compile(
    r"\b(?:drawn\s+to|chose|choose|chooses|like|likes|love|loves|"
    r"enjoy|enjoys|prefer|prefers)\s+(?:the\s+|these\s+|those\s+|my\s+|"
    r"their\s+|a\s+|an\s+)?(?:turtles?|pets?|animals?|reptiles?)\b|"
    r"\b(?:turtles?|pets?|animals?|reptiles?)\b"
    r"(?=.{0,180}\b(?:drawn|unique|slow\s+pace|low[-\s]?maintenance|"
    r"calming|calm|love|loves|like|likes|enjoy|enjoys|prefer|prefers)\b)",
    re.IGNORECASE | re.DOTALL,
)
_COMMON_INTEREST_ANIMAL_FALSE_FRIEND_RE = re.compile(
    r"\banimals?\s+like\b|"
    r"\bother\s+animals?\b(?=.{0,120}\b(?:consider|allerg(?:y|ic)|"
    r"pictures?|pics?)\b)|"
    r"\b(?:send|sending)\s+(?:you\s+)?(?:pictures?|pics?)\b",
    re.IGNORECASE | re.DOTALL,
)


def _common_interest_animal_answer_shape_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if not (
        _is_common_interest_answer_reason(query_reason)
        and query
        and _COMMON_INTEREST_ANIMAL_ANSWER_QUERY_RE.search(query) is not None
    ):
        return 0
    text = item.text
    if _COMMON_INTEREST_ANIMAL_FALSE_FRIEND_RE.search(text) is not None:
        return 4
    if _COMMON_INTEREST_EXPLICIT_ANIMAL_CHOICE_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_INSPIRATIONAL_AFFINITY_SLOT_RE.search(text) is not None:
        return 1
    if _COMMON_INTEREST_ANIMAL_AFFINITY_SLOT_RE.search(text) is not None:
        return 2
    return 5


_ACTIVITY_COMPETITION_VISUAL_QUERY_RE = re.compile(
    r"\b(?:dancers?|photo|picture|image|dance\s+festival|festival|"
    r"attitude|participat(?:e|ing)|part\s+of)\b",
    re.IGNORECASE,
)
_ACTIVITY_COMPETITION_ATTITUDE_QUERY_RE = re.compile(
    r"\b(?:attitude|participat(?:e|ing)|part\s+of)\b",
    re.IGNORECASE,
)
_ACTIVITY_COMPETITION_DANCER_REPLY_RE = re.compile(
    r"\b(?:dancers?|they(?:'re| are)|ones?)\b"
    r"(?=.{0,220}\b(?:perform(?:ing|ance)?|grace|graceful|"
    r"skill|practic(?:e|ed|ing)|impress)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_COMPETITION_ATTITUDE_REPLY_RE = re.compile(
    r"\b(?:glad\s+to\s+be\s+part\s+of\s+it|part\s+of\s+it|"
    r"awesome|excited)\b",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_COMPETITION_VISUAL_ANSWER_RE = re.compile(
    r"\b(?:dancers?|dance|festival|perform(?:ing|ance)?|stage)\b"
    r"(?=.{0,260}\b(?:photo|picture|image\s+caption|visual\s+query|"
    r"grace|graceful|skill|practic(?:e|ed|ing)|impress|part\s+of\s+it|"
    r"glad|awesome|excited|memories|grand\s+opening)\b)",
    re.IGNORECASE | re.DOTALL,
)


def _activity_competition_visual_answer_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if query_reason != "activity_competition_evidence_bridge":
        return 0
    if not query or _ACTIVITY_COMPETITION_VISUAL_QUERY_RE.search(query) is None:
        return 0
    if _ACTIVITY_COMPETITION_ATTITUDE_QUERY_RE.search(query) is not None:
        if _ACTIVITY_COMPETITION_ATTITUDE_REPLY_RE.search(item.text) is not None:
            return 0
        if _ACTIVITY_COMPETITION_VISUAL_ANSWER_RE.search(item.text) is not None:
            return 2
        if _general_activity_answer_slot_for_text(item.text.casefold()):
            return 3
        return 5
    if _ACTIVITY_COMPETITION_DANCER_REPLY_RE.search(item.text) is not None:
        return 0
    if _ACTIVITY_COMPETITION_VISUAL_ANSWER_RE.search(item.text) is not None:
        return 1
    if _ACTIVITY_COMPETITION_ATTITUDE_REPLY_RE.search(item.text) is not None:
        return 2
    if _general_activity_answer_slot_for_text(item.text.casefold()):
        return 3
    return 5


def _common_interest_direct_evidence_rank(
    item: ContextItem,
    *,
    query_reason: str,
) -> int:
    if not (
        _is_common_interest_answer_reason(query_reason)
        and _is_exact_common_interest_answer_support_item(item)
    ):
        return 0
    text = item.text
    if _COMMON_INTEREST_MOVIE_SEEN_SLOT_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_MOVIE_SLOT_RE.search(text) is not None:
        if _COMMON_INTEREST_MOVIE_QUESTION_ONLY_RE.search(text) is not None:
            return 2
        return 0
    if _COMMON_INTEREST_PERSONAL_HOBBY_SLOT_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_ANIMAL_AFFINITY_SLOT_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_INSPIRATIONAL_AFFINITY_SLOT_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_SHARED_DESSERT_BRIDGE_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_SELF_DESSERT_EVIDENCE_RE.search(text) is not None:
        return 0
    if _COMMON_INTEREST_PERSONAL_DESSERT_PREFERENCE_RE.search(text) is not None:
        return 2
    return 1


def _degree_completion_temporal_answer_support_rank(
    item: ContextItem,
    *,
    query: str,
) -> int:
    return 0 if _is_degree_completion_temporal_answer_support_item(item, query=query) else 1


def _common_interest_answer_support_rank(item: ContextItem, *, query_reason: str) -> int:
    if not _is_common_interest_answer_reason(query_reason):
        return 0
    slot = _common_interest_answer_slot(item, query_reason=query_reason)
    if not slot:
        return 5
    slot_priority = _common_interest_answer_slot_priority(slot)
    if _has_any_exact_turn_source_ref(item):
        return slot_priority
    return min(slot_priority + 1, 4)


def _place_area_state_answer_support_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if not _place_area_state_query_applies(query=query, query_reason=query_reason):
        return 0
    slot = _inventory_answer_slot(item, query_reason=query_reason)
    if not (
        slot.startswith("state_")
        or slot in {"country", "travel_place", "travel_place_realized"}
    ):
        return 3
    has_direct_location = (
        _PLACE_AREA_DIRECT_LOCATION_RE.search(item.text) is not None
        or _PLACE_AREA_LANDMARK_LOCATION_RE.search(item.text) is not None
    )
    has_state_visit = _PLACE_AREA_STATE_VISIT_RE.search(item.text) is not None
    if (
        _has_any_exact_turn_source_ref(item)
        and (slot.endswith("_realized") or has_state_visit)
        and _PLACE_AREA_STATE_FUTURE_RE.search(item.text) is None
        and not (
            _place_area_state_query_wants_concrete_state(query)
            and slot in {"state_east_coast", "state_pacific_northwest"}
        )
    ):
        return 0
    if (
        _has_any_exact_turn_source_ref(item)
        and has_direct_location
        and _PLACE_AREA_STATE_FUTURE_RE.search(item.text) is None
    ):
        return 1
    if (
        _place_area_state_query_wants_concrete_state(query)
        and slot
        in {"state_east_coast", "state_pacific_northwest", "travel_place"}
    ):
        return 2
    if _has_any_exact_turn_source_ref(item):
        return 1
    return 2


def _place_area_state_query_applies(*, query: str, query_reason: str) -> bool:
    if not query or _PLACE_AREA_STATE_QUERY_RE.search(query) is None:
        return False
    return query_reason.replace("_", "-") in {
        "decomposition-inventory-list",
        "place-area-inventory-bridge",
        "trip-destination-bridge",
    }


def _place_area_state_query_wants_concrete_state(query: str) -> bool:
    return re.search(r"\bstates?\b", query, re.IGNORECASE) is not None


_STATE_RESIDENCE_ANSWER_EVIDENCE_REASONS = frozenset(
    {
        "inference_state_residence_city_state_evidence",
        "inference_state_residence_named_state_evidence",
        "inference_state_residence_geo_evidence",
    }
)
_STATE_RESIDENCE_MAP_TRAIL_RE = re.compile(
    r"\bmap\b(?=.{0,160}\btrails?\b)|\btrails?\b(?=.{0,160}\bmap\b)",
    re.IGNORECASE | re.DOTALL,
)


def _state_residence_answer_support_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if query_reason != "state_residence_inference_bridge" or not query:
        return 0
    signal = state_residence_inference_signal(query=query, text=item.text)
    if signal.reason == "inference_state_residence_geo_evidence":
        has_map_trail = _STATE_RESIDENCE_MAP_TRAIL_RE.search(item.text) is not None
        if has_map_trail and _has_any_exact_turn_source_ref(item):
            return 0
        if has_map_trail:
            return 1
        if _has_any_exact_turn_source_ref(item):
            return 2
        return 3
    if signal.reason in _STATE_RESIDENCE_ANSWER_EVIDENCE_REASONS:
        if _has_any_exact_turn_source_ref(item):
            return 1
        return 2
    if signal.penalty > 0:
        return 5
    if _has_any_exact_turn_source_ref(item):
        return 4
    return 5


def _is_state_residence_geo_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    query_reason = _answer_support_query_reason(item)
    if query_reason != "state_residence_inference_bridge" or not query:
        return False
    return (
        _state_residence_answer_support_rank(
            item,
            query=query,
            query_reason=query_reason,
        )
        == 0
    )


def _is_direct_place_area_state_answer_support_item(
    item: ContextItem,
    *,
    query: str,
    family: str,
) -> bool:
    query_reason = _answer_support_query_reason(item)
    if not _place_area_state_query_applies(query=query, query_reason=query_reason):
        return False
    if _diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return False
    return (
        _place_area_state_answer_support_rank(
            item,
            query=query,
            query_reason=query_reason,
        )
        == 0
    )


def _is_direct_outdoor_activity_answer_support_item(
    item: ContextItem,
    *,
    query: str,
    family: str,
) -> bool:
    if not query or not re.search(
        r"\b(?:outdoor|outdoors|hiking|hike|mountaineering|picnic|"
        r"waterfall|colleagues?|workmates?|friends?)\b",
        query,
        re.IGNORECASE,
    ):
        return False
    if _answer_support_query_reason(item) != "outdoor_activity_inventory_bridge":
        return False
    if _diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return False
    slot = _inventory_answer_slot(item, query_reason="outdoor_activity_inventory_bridge")
    return slot in {
        "outdoor_visual_group",
        "outdoor_mountaineering",
        "outdoor_hiking",
        "outdoor_picnic",
        "outdoor_waterfall",
    }


def _birdwatching_city_schedule_exact_turn_rank(item: ContextItem, *, query_reason: str) -> int:
    if query_reason != "birdwatching_city_schedule_bridge":
        return 0
    if _has_any_exact_turn_source_ref(item) and len(item.source_refs) == 1:
        return 0
    return 1


def _pet_acquisition_date_anchor_answer_support_rank(
    item: ContextItem,
    *,
    query_reason: str,
) -> int:
    return 0 if _is_pet_acquisition_date_anchor_answer_support_item(item) else 1


def _is_pet_acquisition_date_anchor_answer_support_item(item: ContextItem) -> bool:
    query_reason = _answer_support_query_reason(item)
    text = item.text
    signals = _diagnostic_score_signals(item)
    signal_reason = str(signals.get("query_expansion_reason") or "").strip()
    if (
        query_reason == "pet_acquisition_date_bridge"
        and _numeric_signal(signals.get("exact_source_repair_date_anchor")) > 0
        and _is_temporal_answer_support_item(item, query_reason=query_reason)
    ):
        return True
    if (
        query_reason == "pet_acquisition_date_bridge"
        and _is_temporal_answer_support_item(item, query_reason=query_reason)
        and _PET_ACQUISITION_DATE_ANCHOR_SUPPORT_RE.search(text) is not None
    ):
        return True
    return (
        query_reason in {"pet_acquisition_date_bridge", "decomposition_temporal_answer"}
        and (
            signal_reason == "pet_acquisition_date_bridge"
            or _PET_ACQUISITION_OBJECT_ANCHOR_RE.search(text) is not None
        )
        and _is_temporal_answer_support_item(item, query_reason=query_reason)
        and _PET_ACQUISITION_DATE_ANCHOR_SUPPORT_RE.search(text) is not None
    )


def _temporal_answer_support_source_span_rank(item: ContextItem, *, query_reason: str) -> int:
    if not _is_temporal_answer_support_item(item, query_reason=query_reason):
        return 0
    if _has_primary_exact_turn_source_ref(item) and len(item.source_refs) == 1:
        return 0
    if _has_primary_exact_turn_source_ref(item):
        return 1
    if _has_any_exact_turn_source_ref(item) and len(item.source_refs) == 1:
        return 2
    if _has_any_exact_turn_source_ref(item):
        return 3
    return 4


def _temporal_answer_support_query_object_hits(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if not query or not _is_temporal_answer_support_item(item, query_reason=query_reason):
        return 0
    query_tokens = tuple(
        dict.fromkeys(
            token.casefold()
            for token in _QUERY_OBJECT_TOKEN_RE.findall(query)
            if len(token) >= 3
            and token.casefold() not in _TEMPORAL_QUERY_OBJECT_STOPWORDS
            and not token[:1].isupper()
        )
    )
    if not query_tokens:
        return 0
    text = item.text.casefold()
    return sum(1 for token in query_tokens if re.search(rf"\b{re.escape(token)}\b", text))


def _answer_object_rank(item: ContextItem, *, query_reason: str) -> int:
    if _is_support_network_reason(query_reason):
        return _support_network_answer_object_rank(item.text)
    if _is_pottery_type_reason(query_reason):
        return _pottery_type_answer_object_rank(item.text)
    if _is_pottery_type_inventory_item(item, query_reason=query_reason):
        return _pottery_type_answer_object_rank(item.text)
    if _is_family_activity_reason(query_reason):
        return _family_activity_answer_object_rank(item.text)
    if query_reason == "cause_event_inventory_bridge":
        return _cause_event_answer_content_rank(item.text)
    if query_reason == "childhood_possession_inventory_bridge":
        return _childhood_possession_answer_content_rank(item.text)
    if _is_inventory_list_reason(query_reason):
        return _inventory_list_answer_object_rank(item.text)
    return 2

def _marker_coverage_answer_support_rank(item: ContextItem, *, query_reason: str) -> int:
    if not _aggregation_marker_coverage_slot(item, query_reason=query_reason):
        return 0
    markers = tuple(
        dict.fromkeys(match.group(0) for match in _DIALOGUE_MARKER_RE.finditer(item.text))
    )
    return -len(markers)


def _is_temporal_answer_support_item(item: ContextItem, *, query_reason: str) -> bool:
    if _numeric_signal(_diagnostic_score_signals(item).get("source_sibling_answer_evidence")) <= 0:
        return False
    if not _has_any_exact_turn_source_ref(item):
        return False
    if (
        query_reason in {"business_commonality_bridge", "business_start_reason_bridge"}
        and _business_commonality_answer_slot(item.text)
    ):
        return False
    signals = _diagnostic_score_signals(item)
    if _numeric_signal(signals.get("exact_source_repair_date_anchor")) > 0:
        return True
    normalized_reason = query_reason.replace("_", "-")
    if normalized_reason in _TEMPORAL_ANSWER_SUPPORT_REASONS:
        return True
    if query_reason == "outdoor_activity_inventory_bridge" or (
        _is_community_participation_reason(query_reason)
        and _inventory_answer_slot(item, query_reason=query_reason)
    ):
        return False
    if normalized_reason in {"place-area-inventory-bridge", "trip-destination-bridge"} and (
        _inventory_answer_slot(item, query_reason=query_reason)
    ):
        return False
    return _TEMPORAL_DIRECT_ANSWER_RE.search(item.text) is not None

def _precise_turn_answer_support_rank(item: ContextItem, *, query_reason: str) -> int:
    if _is_temporal_answer_support_item(item, query_reason=query_reason):
        return 0
    if _is_count_aggregation_coverage_item(item, query_reason=query_reason):
        return 0
    if (
        _is_family_activity_reason(query_reason)
        and _answer_object_rank(item, query_reason=query_reason) == 0
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        _is_activity_participation_answer_reason(query_reason)
        and _activity_answer_content_rank(item.text) == 0
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason == "birdwatching_city_schedule_bridge"
        and _numeric_signal(
            _diagnostic_score_signals(item).get("birdwatching_city_schedule_answer_evidence")
        )
        >= 2
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason == "birdwatching_city_schedule_bridge"
        and _birdwatching_city_schedule_answer_content_rank(item.text) <= 1
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason in {"book_reading_list_bridge", "creative_writing_career_bridge"}
        and _book_reading_answer_content_rank(item.text) <= 1
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason == "decomposition_inventory_list"
        and _book_reading_answer_content_rank(item.text) <= 1
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason == "music_artist_answer_bridge"
        and _music_artist_answer_content_rank(item.text) <= 1
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        _is_inventory_list_reason(query_reason)
        and _answer_object_rank(item, query_reason=query_reason) <= 1
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        _is_common_interest_answer_reason(query_reason)
        and _common_interest_answer_slot(item, query_reason=query_reason)
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if query_reason in _BROAD_EVIDENCE_ANSWER_SUPPORT_REASONS:
        return 2
    if (
        query_reason in _COUNT_AGGREGATION_COVERAGE_REASONS
        and _has_primary_exact_turn_source_ref(item)
    ):
        return 1
    if _is_activity_participation_answer_reason(query_reason):
        return 2
    if query_reason not in _PRECISE_TURN_ANSWER_SUPPORT_REASONS:
        return 2
    return 0 if _has_primary_exact_turn_source_ref(item) else 1

def _precise_answer_content_rank(item: ContextItem, *, query_reason: str) -> int:
    if _is_support_network_reason(query_reason):
        return _support_network_answer_object_rank(item.text)
    if query_reason in {"career_intent_bridge", "career_path_bridge"}:
        text = item.text.casefold()
        if "working with trans people" in text or (
            "mental health" in text and ("support" in text or "help" in text)
        ):
            return 0
        if "counsel" in text or "mental health" in text:
            return 1
        return 3
    if query_reason == "creative_writing_career_bridge":
        return _book_reading_answer_content_rank(item.text)
    if query_reason == "birdwatching_city_schedule_bridge":
        return _birdwatching_city_schedule_answer_content_rank(item.text)
    if query_reason == "book_reading_list_bridge":
        return _book_reading_answer_content_rank(item.text)
    if query_reason == "book_suggestion_bridge":
        return min(
            _book_suggestion_answer_content_rank(item.text),
            recommendation_list_answer_support_rank(
                text=item.text,
                query_reason=query_reason,
            ),
        )
    if is_recommendation_list_reason(query_reason):
        recommendation_rank = recommendation_list_answer_support_rank(
            text=item.text,
            query_reason=query_reason,
        )
        if recommendation_rank <= 2:
            return recommendation_rank
    if query_reason == "music_artist_answer_bridge":
        return _music_artist_answer_content_rank(item.text)
    if query_reason == "classical_music_preference_bridge":
        return _classical_music_preference_answer_content_rank(item.text)
    if query_reason == "sentimental_reminder_bridge":
        return _sentimental_reminder_answer_content_rank(item.text)
    if query_reason == "decomposition_collectible_object":
        return _collectible_object_answer_content_rank(item.text)
    if query_reason == "outdoor_nature_memory_bridge":
        return _outdoor_nature_memory_answer_content_rank(item.text)
    if query_reason == "children_preference_bridge":
        return _children_preference_answer_content_rank(item.text)
    if query_reason == "inspiration_source_bridge":
        return _inspiration_source_answer_content_rank(item.text)
    if query_reason == "public_office_service_bridge":
        return _public_office_service_answer_content_rank(item.text)
    if query_reason == "recognition_award_bridge":
        return _recognition_award_answer_content_rank(item.text)
    if query_reason == "relocation_willingness_inference_bridge":
        return _relocation_willingness_answer_content_rank(item.text)
    if query_reason == "volunteer_career_inference_bridge":
        return _volunteer_career_answer_content_rank(item)
    if _is_activity_participation_answer_reason(query_reason):
        return _activity_answer_content_rank(item.text)
    if (
        query_reason == "decomposition_inventory_list"
        and _book_reading_answer_content_rank(item.text) <= 1
    ):
        return _book_reading_answer_content_rank(item.text)
    if _is_pottery_type_reason(query_reason):
        return _pottery_type_answer_content_rank(item.text)
    if query_reason in {"running_reason_bridge", "running_reason_question_bridge"}:
        text = item.text.casefold()
        if "what got you into running" in text or "for walking or running" in text:
            return 0
        if "running" in text and any(
            marker in text
            for marker in (
                "destress",
                "de-stress",
                "clear my mind",
                "headspace",
            )
        ):
            return 0
        if "running" in text:
            return 2
        return 3
    if query_reason == "shoe_usage_bridge":
        text = item.text.casefold()
        if "walking or running" in text or "for walking" in text:
            return 0
        if any(marker in text for marker in ("new shoes", "sneakers", "running shoe")):
            return 1
        return 3
    if query_reason == "painting_inventory_bridge":
        return _painting_inventory_answer_content_rank(item.text)
    if query_reason == "degree_policy_inference_bridge":
        return _degree_policy_answer_content_rank(item.text)
    if query_reason == "childhood_possession_inventory_bridge":
        return _childhood_possession_answer_content_rank(item.text)
    if query_reason == "cause_event_inventory_bridge":
        return _cause_event_answer_content_rank(item.text)
    if query_reason == "event_participation_help_bridge":
        if _inventory_answer_slot(item, query_reason=query_reason) in {
            "community_mentorship_program",
            "community_school_event",
        }:
            return 0
        return _inventory_list_answer_object_rank(item.text)
    if query_reason == "transgender_youth_center_event_bridge":
        return _transgender_youth_center_event_answer_content_rank(item)
    if query_reason in {"business_commonality_bridge", "business_start_reason_bridge"}:
        return _business_commonality_answer_content_rank(item.text)
    if query_reason == "creative_work_submission_bridge":
        return _creative_work_submission_answer_content_rank(item.text)
    if query_reason == "creative_writing_inventory_bridge":
        return _creative_writing_inventory_answer_content_rank(item.text)
    if query_reason == TRAVEL_HOBBY_WRITING_REASON:
        return travel_hobby_writing_answer_rank(item.text)
    if query_reason == "screenplay_count_bridge":
        return _screenplay_rejection_answer_content_rank(item.text)
    if query_reason == "charity_brand_sponsorship_bridge":
        return _charity_brand_sponsorship_answer_content_rank(item.text)
    if query_reason == "exercise_activity_inventory_bridge":
        return _exercise_activity_answer_content_rank(item.text)
    if query_reason == "friend_place_shelter_inventory_bridge":
        return _friend_place_shelter_answer_content_rank(item.text)
    if query_reason == "animal_care_instruction_bridge":
        return _animal_care_instruction_content_rank(item.text)
    if query_reason in {
        "support_career_motivation_bridge",
        "support_origin_bridge",
    }:
        return _support_career_motivation_content_rank(item.text)
    if query_reason != "meteor_shower_feeling_bridge":
        return 0
    text = item.text.casefold()
    if "awe" in text or "tiny" in text:
        return 0
    if "felt" in text or "feel" in text or "universe" in text:
        return 1
    return 2

def _support_career_motivation_content_rank(text: str) -> int:
    if _SUPPORT_CAREER_MOTIVATION_DIRECT_RE.search(text) is not None:
        return 0
    if _SUPPORT_CAREER_MOTIVATION_CONTEXT_RE.search(text) is not None:
        return 1
    return 3

def _classical_music_preference_answer_content_rank(text: str) -> int:
    if _CLASSICAL_MUSIC_PREFERENCE_DIRECT_RE.search(text) is not None:
        return 0
    if re.search(r"\b(?:classical|bach|mozart|vivaldi|orchestra|symphony)\b", text, re.IGNORECASE):
        return 1
    if re.search(r"\b(?:music|song|tunes?|composer|concert)\b", text, re.IGNORECASE):
        return 2
    return 4


def _sentimental_reminder_answer_content_rank(text: str) -> int:
    if _SENTIMENTAL_REMINDER_DIRECT_RE.search(text) is not None:
        return 0
    if _SENTIMENTAL_REMINDER_CONTEXT_RE.search(text) is not None:
        return 1
    return 4


def _collectible_object_answer_content_rank(text: str) -> int:
    if _COLLECTIBLE_OBJECT_DIRECT_RE.search(text) is not None:
        return 0
    if _COLLECTIBLE_OBJECT_CONTEXT_RE.search(text) is not None:
        return 1
    return 4


def _outdoor_nature_memory_answer_content_rank(text: str) -> int:
    if _OUTDOOR_NATURE_MEMORY_DIRECT_RE.search(text) is not None:
        return 0
    if _OUTDOOR_NATURE_MEMORY_CONTEXT_RE.search(text) is not None:
        return 1
    return 4


def _children_preference_answer_content_rank(text: str) -> int:
    if _CHILDREN_PREFERENCE_DIRECT_RE.search(text) is not None:
        return 0
    if _CHILDREN_PREFERENCE_CONTEXT_RE.search(text) is not None:
        return 1
    return 4


def _childhood_possession_answer_content_rank(text: str) -> int:
    has_direct_context = _CHILDHOOD_POSSESSION_DIRECT_RE.search(text) is not None
    has_object = _CHILDHOOD_POSSESSION_OBJECT_RE.search(text) is not None
    if has_direct_context and has_object:
        return 0
    if has_direct_context:
        return 1
    if has_object and re.search(r"\b(?:childhood|kid|child|younger)\b", text, re.IGNORECASE):
        return 2
    return 5


def _public_office_service_answer_content_rank(text: str) -> int:
    if _PUBLIC_OFFICE_SERVICE_DIRECT_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if "office" in lowered or "politic" in lowered or "campaign" in lowered:
        return 1
    return 4


def _recognition_award_answer_content_rank(text: str) -> int:
    if _RECOGNITION_CERTIFICATE_VISUAL_ANSWER_RE.search(text) is not None:
        return 0
    if re.search(
        r"\b(?:recognition|awards?|medals?|certificates?|honou?rs?|"
        r"troph(?:y|ies)|prizes?)\b"
        r"(?=.{0,200}\b(?:receive|received|got|given|gave|earned|won)\b)|"
        r"\b(?:receive|received|got|given|gave|earned|won)\b"
        r"(?=.{0,160}\b(?:recognition|awards?|medals?|certificates?|"
        r"honou?rs?|troph(?:y|ies)|prizes?)\b)",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        return 1
    if re.search(
        r"\b(?:certificate|certificates|diploma|diplomas|degree|"
        r"graduat(?:e|ed|ion))\b",
        text,
        re.IGNORECASE,
    ):
        return 2
    return 4


def _inspiration_source_answer_content_rank(text: str) -> int:
    if _INSPIRATION_SOURCE_DIRECT_RE.search(text) is not None:
        return 0
    if _INSPIRATION_SOURCE_CONTEXT_RE.search(text) is not None:
        return 2
    return 4


def _relocation_willingness_answer_content_rank(text: str) -> int:
    if (
        _PUBLIC_OFFICE_SERVICE_DIRECT_RE.search(text) is not None
        or _MILITARY_SERVICE_GOAL_DIRECT_RE.search(text) is not None
    ):
        return 0
    lowered = text.casefold()
    if any(marker in lowered for marker in ("military", "country", "office", "politic")):
        return 1
    return 4


def _volunteer_career_answer_content_rank(item: ContextItem) -> int:
    slot = _career_answer_slot(
        item,
        query_reason="volunteer_career_inference_bridge",
    )
    if slot in {
        "shelter_operations",
        "counseling_talks",
        "volunteer_origin",
        "start_motivation",
    }:
        return 0
    if slot == "resident_support":
        return 1
    if slot == "homeless_shelter":
        return 2
    return 4


def _degree_policy_answer_content_rank(text: str) -> int:
    slot = _degree_policy_answer_slot(text)
    if slot == "degree_field_inference":
        return 0
    if slot == "policy_career_plan":
        return 1
    if slot == "degree_completion_context":
        return 2
    return 3


def _birdwatching_city_schedule_answer_content_rank(text: str) -> int:
    if _BIRDWATCHING_CITY_SCHEDULE_CONTENT_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if "nature" in lowered and ("city" in lowered or "outdoors" in lowered):
        return 1
    return 3


def _book_suggestion_answer_content_rank(text: str) -> int:
    if _BOOK_SUGGESTION_DIRECT_RE.search(text) is not None:
        return 0
    return _book_reading_answer_content_rank(text)


def _music_artist_answer_content_rank(text: str) -> int:
    if _MUSIC_ARTIST_DIRECT_ANSWER_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if "artist" in lowered or "band" in lowered or "singer" in lowered:
        return 1
    if "music" in lowered or "song" in lowered or "concert" in lowered:
        return 3
    return 5


def _business_commonality_answer_content_rank(text: str) -> int:
    slot = _business_commonality_answer_slot(text)
    if slot in {"jon_job_loss", "gina_job_loss"}:
        if _BUSINESS_DIRECT_JOB_LOSS_RE.search(text) is not None:
            return 0
        return 1
    if slot in {"jon_business_type", "gina_store_start"}:
        if _BUSINESS_DIRECT_START_REASON_RE.search(text) is not None:
            return 0
        return 1
    if slot == "business_start_generic":
        return 2
    return 3


def _cause_event_answer_content_rank(text: str) -> int:
    if _cause_event_answer_slot(text):
        return 0
    lowered = text.casefold()
    if "cause" in lowered and any(
        marker in lowered for marker in ("event", "fund", "awareness", "charity")
    ):
        return 1
    if any(marker in lowered for marker in ("food drive", "toy drive", "veteran")):
        return 2
    return 5


_TRANSGENDER_YOUTH_CENTER_EVENT_DIRECT_RE = re.compile(
    r"\b(?:youth\s+center|talent\s+show|band|stage|microphone|"
    r"colorful\s+lights|visual\s+query)\b",
    re.IGNORECASE,
)


def _transgender_youth_center_event_answer_content_rank(item: ContextItem) -> int:
    if _diagnostic_signal_truthy(item, "source_sibling_dialogue_visual_reference"):
        return 0
    return 0 if _TRANSGENDER_YOUTH_CENTER_EVENT_DIRECT_RE.search(item.text) else 5


def _screenplay_rejection_answer_content_rank(text: str) -> int:
    if _SCREENPLAY_REJECTION_DIRECT_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if "rejection" in lowered or "rejected" in lowered:
        return 1
    if "script" in lowered or "screenplay" in lowered:
        return 2
    return 4


def _creative_work_submission_answer_content_rank(text: str) -> int:
    if _CREATIVE_WORK_SUBMISSION_DIRECT_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if "submit" in lowered or "submission" in lowered:
        return 1
    if "screenplay" in lowered or "script" in lowered or "project" in lowered:
        return 2
    return 4


def _creative_writing_inventory_answer_content_rank(text: str) -> int:
    if _CREATIVE_WRITING_INVENTORY_DIRECT_RE.search(text) is not None:
        return 0
    lowered = text.casefold()
    if any(
        marker in lowered
        for marker in ("screenplay", "script", "book", "journal", "blog post")
    ):
        return 1
    if "writing" in lowered or "wrote" in lowered:
        return 2
    return 4


def _business_dialogue_marker_answer_support_rank(
    item: ContextItem,
    *,
    query_reason: str,
) -> int:
    if not _is_business_commonality_reason(query_reason):
        return 0
    if _business_commonality_answer_content_rank(item.text) > 1:
        return 1
    return 0 if _DIALOGUE_MARKER_RE.search(item.text) is not None else 1


def _is_business_commonality_reason(query_reason: str) -> bool:
    return query_reason in {"business_commonality_bridge", "business_start_reason_bridge"}


_CHARITY_BRAND_CONCRETE_DEAL_RE = re.compile(
    r"\b(?:signed(?:\s+up)?|secure(?:d|s)?|landed)\b"
    r"(?=.{0,180}\b(?:brand|brands?|company|companies|organization|"
    r"organisations?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?|deal|deals?|"
    r"gear|shoe|shoes|apparel|equipment)\b)|"
    r"\bin\s+talks?\s+with\b"
    r"(?=.{0,180}\b(?:sponsor(?:ship|s)?|endorse(?:ment|d|s)?|"
    r"partner(?:ship|ed|s)?|deal|deals?)\b)|"
    r"\b(?:deal|deals?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?|"
    r"partner(?:ship|s)?)\b"
    r"(?=.{0,140}\b(?:signed(?:\s+up)?|secure(?:d|s)?|landed|"
    r"in\s+talks?\s+with|stoked|working\s+with)\b)",
    re.IGNORECASE | re.DOTALL,
)


def _charity_brand_sponsorship_answer_content_rank(text: str) -> int:
    slot = _charity_brand_sponsorship_answer_slot(text)
    if slot == "brand_sponsorship_deal":
        return 0 if _CHARITY_BRAND_CONCRETE_DEAL_RE.search(text) else 1
    if slot == "partner_affinity_fit":
        return 0
    if slot in {"charity_org_fit", "charity_intent"}:
        return 1
    if slot == "sports_brand_generic":
        return 2
    return 3


def _activity_answer_content_rank(text: str) -> int:
    if _ACTIVITY_DIRECT_PARTICIPATION_RE.search(text) is not None:
        return 0
    if _general_activity_answer_slot_for_text(text.casefold()):
        return 1
    if _ACTIVITY_CONTEXT_RE.search(text) is not None:
        return 2
    return 4


def _friend_place_shelter_answer_content_rank(text: str) -> int:
    if _INVENTORY_FRIEND_PLACE_DIRECT_RE.search(text):
        return 0
    if _INVENTORY_FRIEND_PLACE_SHELTER_ACTIVITY_REPEAT_RE.search(text):
        return 2
    if _INVENTORY_FRIEND_PLACE_SHELTER_ANCHOR_RE.search(text):
        return 0
    if _INVENTORY_SHELTER_SLOT_RE.search(text):
        return 1
    return 3


def _animal_care_instruction_content_rank(text: str) -> int:
    if _ANIMAL_CARE_DIRECT_INSTRUCTION_RE.search(text):
        return 0
    if _ANIMAL_CARE_GENERIC_HABITAT_RE.search(text):
        return 3
    if re.search(r"\b(?:care|clean|feed|light|habitat|routine)\b", text, re.IGNORECASE):
        return 1
    return 2


def _pottery_type_answer_content_rank(text: str) -> int:
    if _POTTERY_TYPE_DIRECT_MADE_OBJECT_RE.search(text):
        return 0
    if _POTTERY_TYPE_FRIENDSHIP_COMPANION_RE.search(text):
        return 1
    if _POTTERY_TYPE_PROJECT_COMPANION_RE.search(text):
        return 2
    if _POTTERY_TYPE_GENERIC_ANSWER_OBJECT_RE.search(text):
        return 3
    return 4
