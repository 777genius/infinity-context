"""Query-focused family ordering and stable item tie-break policies."""

from __future__ import annotations

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
    _answer_object_rank,
    _pottery_type_answer_content_rank,
    _precise_answer_content_rank,
    _precise_turn_answer_support_rank,
)
from infinity_context_core.application.context_packer_answer_support_evidence import (
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
    _is_exact_business_direct_answer_support_item,
    _is_exact_common_interest_answer_support_item,
    _is_exact_named_game_inventory_answer_support_item,
    _is_exact_named_preference_answer_support_item,
    _is_exact_precise_content_answer_support_item,
    _is_exact_screenplay_rejection_answer_support_item,
    _is_exact_themed_location_inference_answer_support_item,
    _is_single_exact_cause_inventory_answer_support_item,
    _marker_coverage_answer_support_rank,
    _recognition_award_visual_answer_rank,
    _relationship_status_answer_support_rank,
    _shared_volunteering_first_mention_rank,
)
from infinity_context_core.application.context_packer_answer_support_families import (
    _broad_turn_family_source_group,
    _broad_turn_source_group_counts,
    _marker_coverage_family_source_group,
    _marker_coverage_source_group_counts,
    _pet_acquisition_named_object_source_groups,
)
from infinity_context_core.application.context_packer_answer_support_locations import (
    _country_destination_answer_support_rank,
    _is_direct_place_area_state_answer_support_item,
    _is_exact_country_destination_answer_support_item,
    _is_exact_place_inference_answer_support_item,
    _is_exact_query_destination_answer_support_item,
    _is_state_residence_geo_answer_support_item,
    _place_area_state_answer_support_rank,
    _place_area_state_query_applies,
    _state_residence_answer_support_rank,
)
from infinity_context_core.application.context_packer_answer_support_patterns import (
    _DIRECT_EVIDENCE_QUERY_FOCUS_REASONS,
    _MUSIC_EVENT_ATTENDANCE_QUERY_RE,
    _PLACE_AREA_STATE_QUERY_RE,
)
from infinity_context_core.application.context_packer_answer_support_slots import (
    _animal_evidence_answer_slot,
    _animal_evidence_answer_slot_from_family,
    _animal_evidence_answer_slot_priority_for_family,
    _animal_evidence_slot_for_text,
    _book_reading_answer_content_rank,
    _career_answer_slot_from_family,
    _career_answer_slot_priority,
    _common_interest_answer_slot_from_family,
    _common_interest_answer_slot_priority,
    _inventory_answer_slot,
    _inventory_answer_slot_for_text,
    _inventory_answer_slot_from_family,
    _is_community_participation_reason,
    _is_conversational_support_turn,
    _is_count_aggregation_coverage_item,
    _is_family_activity_reason,
    _is_pottery_type_inventory_item,
    _is_pottery_type_reason,
    _is_support_network_reason,
    _support_network_answer_object_rank,
    _travel_country_inventory_slot_for_text,
)
from infinity_context_core.application.context_packer_answer_support_temporal import (
    _degree_completion_temporal_answer_support_rank,
    _is_degree_completion_temporal_answer_support_item,
    _is_pet_acquisition_date_anchor_answer_support_item,
    _pet_acquisition_date_anchor_answer_support_rank,
    _temporal_answer_support_query_object_hits,
    _temporal_answer_support_source_span_rank,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _answer_support_activity_family_slot,
    _answer_support_exact_query_object_hits,
    _answer_support_query_reason,
    _answer_support_source_group,
    _diagnostic_score_signals,
    _diversity_family_base,
    _has_any_exact_turn_source_ref,
    _has_primary_exact_turn_source_ref,
    _inventory_first_mention_rank,
    _is_business_commonality_reason,
    _numeric_signal,
    _primary_exact_turn_source_id,
)
from infinity_context_core.application.context_packer_inventory_slots import (
    _answer_support_exact_turn_alignment_rank,
    _inventory_answer_slot_priority_for_family,
)
from infinity_context_core.application.context_recommendation_answer_support import (
    recommendation_family_priority,
    recommendation_list_answer_support_rank,
    recommendation_query_focus_applies,
    recommendation_role_alignment_rank,
)
from infinity_context_core.application.context_travel_hobby_writing_evidence import (
    TRAVEL_HOBBY_WRITING_REASON,
    travel_hobby_writing_answer_rank,
)
from infinity_context_core.application.dto import ContextItem


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
