"""Answer-support family identity, source grouping and diversity limits."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import diagnostic_retrieval_sources
from infinity_context_core.application.context_packer_answer_support_patterns import (
    _ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS,
    _ANSWER_SUPPORT_EXCLUDED_QUERY_REASONS,
    _COUNT_AGGREGATION_COVERAGE_REASONS,
    _MAX_ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON,
    _MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS,
    _MAX_ANSWER_SUPPORT_EVENT_SLOT_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON,
    _MAX_ANSWER_SUPPORT_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON,
    _NAMED_ACQUISITION_OBJECT_QUERY_RE,
)
from infinity_context_core.application.context_packer_answer_support_slots import (
    _activity_answer_slot,
    _aggregation_marker_coverage_slot,
    _animal_evidence_answer_slot,
    _broad_evidence_turn_slot,
    _career_answer_slot,
    _common_interest_answer_slot,
    _inference_answer_slot,
    _inventory_answer_slot,
    _is_count_aggregation_coverage_item,
    _is_family_activity_reason,
    _is_pottery_type_reason,
)
from infinity_context_core.application.context_packer_answer_support_temporal import (
    _is_temporal_answer_support_item,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _answer_support_query_reason,
    _answer_support_source_group,
    _compound_diversity_family,
    _diagnostic_list,
    _diagnostic_score_signals,
    _diagnostic_signal_truthy,
    _diversity_family_base,
    _exact_marker_should_precede_inventory,
    _first_dialogue_marker,
    _has_any_exact_turn_source_ref,
    _is_business_commonality_reason,
    _numeric_signal,
    _primary_exact_turn_marker,
    _typed_diversity_family,
)
from infinity_context_core.application.dto import ContextItem


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
