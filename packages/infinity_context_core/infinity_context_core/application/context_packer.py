"""Prompt-safe context packing."""

from __future__ import annotations

import re
from dataclasses import dataclass

import infinity_context_core.application.context_packer_answer_slots as _answer_slots
import infinity_context_core.application.context_packer_diagnostics as _diagnostics
import infinity_context_core.application.context_packer_identity_policy as _identity
import infinity_context_core.application.context_packer_rendering as _rendering
import infinity_context_core.application.context_packer_source_policy as _source_policy
from infinity_context_core.application.context_diagnostics import (
    context_rank_key,
    diagnostic_retrieval_sources,
    normalize_context_item_diagnostics,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    PRECISE_TURN_SOURCE_SIBLING_REASONS,
)
from infinity_context_core.application.dto import ContextBundle, ContextItem
from infinity_context_core.application.normalize import estimate_tokens

_DEFAULT_MAX_RENDERED_CHARS = 18000
_MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS = 8
_MAX_ANSWER_SUPPORT_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON = 1
_MAX_ANSWER_SUPPORT_EVENT_SLOT_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON = 2
_MAX_ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_DIVERSITY_ITEMS_PER_REASON = 6
_ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS = frozenset(
    {
        "adoption-current-goal-bridge",
        "adoption-current-milestone-bridge",
        "activity-aggregation-bridge",
        "activity-visual-selfcare-bridge",
        "birdwatching-city-schedule-bridge",
        "book-reading-list-bridge",
        "book-suggestion-bridge",
        "business-commonality-bridge",
        "charity-brand-sponsorship-bridge",
        "children-count-event-bridge",
        "children-count-sibling-bridge",
        "cause-education-infrastructure-inventory-bridge",
        "cause-veterans-inventory-bridge",
        "decomposition-activity-duration",
        "decomposition-activity-participation",
        "decomposition-attribute-aggregation",
        "decomposition-frequency-recurrence",
        "decomposition-inventory-list",
        "decomposition-quantity-count",
        "degree-policy-inference-bridge",
        "event-participation-bridge",
        "exercise-activity-inventory-bridge",
        "family-activity-bridge",
        "family-hike-detail-bridge",
        "family-hike-activity-bridge",
        "family-museum-activity-bridge",
        "friend-place-inventory-bridge",
        "friend-place-shelter-inventory-bridge",
        "friend-place-gym-inventory-bridge",
        "friend-place-church-inventory-bridge",
        "family-painting-activity-bridge",
        "family-swimming-activity-bridge",
        "hike-count-activity-bridge",
        "item-purchase-bridge",
        "music-artist-band-bridge",
        "national-park-inference-bridge",
        "painting-inventory-bridge",
        "pottery-type-bridge",
        "recommendation-source-bridge",
        "religious-inference-bridge",
        "running-reason-bridge",
        "running-reason-question-bridge",
        "symbol-importance-bridge",
        "transgender-youth-center-event-bridge",
        "travel-country-inventory-bridge",
        "volunteer-career-inference-bridge",
    }
)
_COUNT_AGGREGATION_COVERAGE_REASONS = frozenset(
    {
        "beach_count_activity_bridge",
        "hike_count_activity_bridge",
        "hiking_trail_count_bridge",
    }
)
_ANSWER_SUPPORT_EXCLUDED_QUERY_REASONS = frozenset({"art_style_bridge"})
_BROAD_EVIDENCE_ANSWER_SUPPORT_REASONS = frozenset(
    {
        "activity_visual_selfcare_bridge",
        "birdwatching_city_schedule_bridge",
        "book_suggestion_bridge",
    }
)
_BROAD_EVIDENCE_TURN_SLOT_REASONS = frozenset(
    {
        "birdwatching_city_schedule_bridge",
        "book_suggestion_bridge",
    }
)
_PRECISE_TURN_ANSWER_SUPPORT_REASONS = PRECISE_TURN_SOURCE_SIBLING_REASONS | frozenset(
    {
        "food_recipe_recommendation_bridge",
        "personality_authenticity_bridge",
        "personality_drive_bridge",
        "personality_thoughtfulness_bridge",
        "personality_trait_bridge",
        "wellness_activity_effect_bridge",
    }
)
_DIVERSITY_PRECISE_TURN_REASONS = frozenset(
    {
        "birdwatching_city_schedule_bridge",
        "food_recipe_recommendation_bridge",
        "wellness_activity_effect_bridge",
    }
)
_DIVERSITY_FAMILY_PRIORITY = (
    "fact",
    "chunk",
    "extraction_artifact",
    "anchor",
    "suggestion",
)
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")

@dataclass(frozen=True)
class PackResult:
    bundle: ContextBundle
    dropped_count: int

@dataclass
class _SelectionState:
    selected: list[ContextItem]
    selected_keys: set[tuple[str, str]]
    selected_answer_support_families: set[str]
    selected_chunks_by_source: dict[str, int]
    selected_source_capped_items_by_source: dict[str, int]
    selected_art_style_items_by_source_group: dict[str, int]
    used_tokens: int = 0

class ContextPacker:
    """Renders memory as evidence, never as instructions."""

    def pack(
        self,
        *,
        bundle_id: str,
        items: tuple[ContextItem, ...],
        token_budget: int,
        max_rendered_chars: int = _DEFAULT_MAX_RENDERED_CHARS,
    ) -> PackResult:
        budget = max(64, token_budget)
        char_budget = max(
            len("\n".join(_rendering.CONTEXT_PACKER_HEADER_LINES)),
            max_rendered_chars,
        )
        normalized_items = tuple(normalize_context_item_diagnostics(item) for item in items)
        ordered_items = sorted(normalized_items, key=context_rank_key)
        selectable_items: list[ContextItem] = []
        dropped_by_instruction_flag = 0
        dropped_by_source_cap = 0
        dropped_by_source_group_cap = 0
        dropped_by_budget = 0
        dropped_by_char_cap = 0
        redacted_item_keys: set[tuple[str, str]] = set()
        for item in ordered_items:
            if item.is_instruction:
                dropped_by_instruction_flag += 1
                continue
            item, item_text_redacted = _rendering.redact_context_item_text(item)
            if item_text_redacted:
                redacted_item_keys.add(_selection_key(item))
            selectable_items.append(item)

        state = _SelectionState(
            selected=[],
            selected_keys=set(),
            selected_answer_support_families=set(),
            selected_chunks_by_source={},
            selected_source_capped_items_by_source={},
            selected_art_style_items_by_source_group={},
        )
        diversity_items_used = 0
        diversity_families = _diversity_candidates(selectable_items)
        for family in _ordered_diversity_families(diversity_families):
            item = diversity_families[family]
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
                mark_answer_support_family=False,
            ):
                diversity_items_used += 1

        answer_support_items_used = 0
        answer_support_source_group_items_by_reason: dict[str, int] = {}
        answer_support_families = _answer_support_diversity_candidates(selectable_items)
        for family in _ordered_answer_support_families(answer_support_families):
            if answer_support_items_used >= _MAX_ANSWER_SUPPORT_DIVERSITY_ITEMS:
                break
            item = answer_support_families[family]
            source_group_reason = _answer_support_source_group_reason_key(family)
            if (
                source_group_reason
                and answer_support_source_group_items_by_reason.get(source_group_reason, 0)
                >= _answer_support_source_group_limit(
                    source_group_reason,
                    family=family,
                    item=item,
                )
            ):
                continue
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
            ):
                answer_support_items_used += 1
                if source_group_reason:
                    answer_support_source_group_items_by_reason[source_group_reason] = (
                        answer_support_source_group_items_by_reason.get(source_group_reason, 0) + 1
                    )

        selection_items = _source_policy.source_diversified_order(selectable_items)
        source_diversity_chunks_reordered = _source_policy.source_diversity_reordered_chunk_count(
            selectable_items,
            selection_items,
        )
        dropped_by_answer_support_family_duplicate = 0
        for item in selection_items:
            key = _selection_key(item)
            if key in state.selected_keys:
                continue
            answer_support_family = _answer_support_diversity_family(item)
            if (
                answer_support_family
                and answer_support_family in state.selected_answer_support_families
            ):
                dropped_by_answer_support_family_duplicate += 1
                continue
            if _source_policy.source_cap_applies(item):
                source_key = _rendering.source_key(item)
                source_count = state.selected_source_capped_items_by_source.get(source_key, 0)
                if source_count >= _source_policy.MAX_ITEMS_PER_SOURCE:
                    dropped_by_source_cap += 1
                    continue
                source_group_cap = _source_policy.source_group_cap(item)
                if source_group_cap is not None:
                    source_group_key = _rendering.source_group_key(item)
                    source_group_count = state.selected_art_style_items_by_source_group.get(
                        source_group_key,
                        0,
                    )
                    if source_group_count >= source_group_cap:
                        dropped_by_source_group_cap += 1
                        continue
            item_tokens = estimate_tokens(item.text) + 16
            if state.used_tokens + item_tokens > budget:
                dropped_by_budget += 1
                continue
            if _rendered_char_count((*state.selected, item)) > char_budget:
                dropped_by_char_cap += 1
                continue
            _select_item(state, item=item, item_tokens=item_tokens)

        selected = tuple(sorted(state.selected, key=_context_render_rank_key))
        lines = _rendering.render_context_lines(selected)
        dropped_count = len(normalized_items) - len(selected)
        rendered_text = "\n".join(lines).strip()
        selected_keys = {_selection_key(item) for item in selected}
        return PackResult(
            bundle=ContextBundle(
                bundle_id=bundle_id,
                rendered_text=rendered_text,
                items=selected,
                token_estimate=state.used_tokens,
                diagnostics={
                    "items_considered": len(items),
                    "items_used": len(selected),
                    "diversity_families_considered": len(diversity_families),
                    "diversity_families_used": len({_diversity_family(item) for item in selected}),
                    "diversity_items_used": diversity_items_used,
                    "answer_support_families_considered": len(answer_support_families),
                    "answer_support_families_used": len(
                        {
                            family
                            for item in selected
                            if (family := _answer_support_diversity_family(item))
                        }
                    ),
                    "answer_support_items_used": answer_support_items_used,
                    "item_type_counts": _identity.item_type_counts(selected),
                    "chunk_sources_considered": len(
                        _source_policy.chunk_source_counts(selectable_items)
                    ),
                    "chunk_sources_used": len(_source_policy.chunk_source_counts(selected)),
                    "max_chunks_used_per_source": max(
                        _source_policy.chunk_source_counts(selected).values(),
                        default=0,
                    ),
                    "source_capped_sources_considered": len(
                        _source_policy.source_capped_source_counts(selectable_items)
                    ),
                    "source_capped_sources_used": len(
                        _source_policy.source_capped_source_counts(selected)
                    ),
                    "max_source_capped_items_used_per_source": max(
                        _source_policy.source_capped_source_counts(selected).values(),
                        default=0,
                    ),
                    "source_diversity_chunks_reordered": source_diversity_chunks_reordered,
                    "dropped_by_instruction_flag": dropped_by_instruction_flag,
                    "dropped_by_budget": dropped_by_budget,
                    "dropped_by_source_cap": dropped_by_source_cap,
                    "dropped_by_source_group_cap": dropped_by_source_group_cap,
                    "dropped_by_char_cap": dropped_by_char_cap,
                    "dropped_by_answer_support_family_duplicate": (
                        dropped_by_answer_support_family_duplicate
                    ),
                    "citations_rendered": sum(
                        len(_rendering.citation_labels(item)) for item in selected
                    ),
                    "citation_quote_previews_rendered": sum(
                        _rendering.citation_quote_preview_count(item) for item in selected
                    ),
                    "sensitive_citation_quote_previews_skipped": (
                        sum(
                            _rendering.sensitive_citation_quote_skip_count(item)
                            for item in selected
                        )
                    ),
                    "sensitive_source_identity_parts_redacted": (
                        sum(
                            _rendering.sensitive_source_identity_part_count(item)
                            for item in selected
                        )
                    ),
                    "unsafe_source_identity_parts_sanitized": (
                        sum(_rendering.unsafe_source_identity_part_count(item) for item in selected)
                    ),
                    "sensitive_item_text_redacted": len(selected_keys & redacted_item_keys),
                    "rendered_chars": len(rendered_text),
                    "max_rendered_chars": char_budget,
                },
            ),
            dropped_count=dropped_count,
        )

def _try_select_item(
    state: _SelectionState,
    *,
    item: ContextItem,
    budget: int,
    char_budget: int,
    mark_answer_support_family: bool = True,
) -> bool:
    if _selection_key(item) in state.selected_keys:
        return False
    answer_support_family = _answer_support_diversity_family(item)
    if answer_support_family and answer_support_family in state.selected_answer_support_families:
        return False
    if _source_policy.source_cap_applies(item):
        source_key = _rendering.source_key(item)
        if state.selected_source_capped_items_by_source.get(source_key, 0) >= (
            _source_policy.MAX_ITEMS_PER_SOURCE
        ):
            return False
        source_group_cap = _source_policy.source_group_cap(item)
        if source_group_cap is not None:
            source_group_key = _rendering.source_group_key(item)
            if (
                state.selected_art_style_items_by_source_group.get(source_group_key, 0)
                >= source_group_cap
            ):
                return False
    item_tokens = estimate_tokens(item.text) + 16
    if state.used_tokens + item_tokens > budget:
        return False
    if _rendered_char_count((*state.selected, item)) > char_budget:
        return False
    _select_item(
        state,
        item=item,
        item_tokens=item_tokens,
        mark_answer_support_family=mark_answer_support_family,
    )
    return True

def _select_item(
    state: _SelectionState,
    *,
    item: ContextItem,
    item_tokens: int,
    mark_answer_support_family: bool = True,
) -> None:
    state.selected.append(item)
    state.selected_keys.add(_selection_key(item))
    answer_support_family = _answer_support_diversity_family(item)
    if mark_answer_support_family and answer_support_family:
        state.selected_answer_support_families.add(answer_support_family)
    if item.item_type == "chunk":
        source_key = _rendering.source_key(item)
        state.selected_chunks_by_source[source_key] = (
            state.selected_chunks_by_source.get(source_key, 0) + 1
        )
    if _source_policy.source_cap_applies(item):
        source_key = _rendering.source_key(item)
        state.selected_source_capped_items_by_source[source_key] = (
            state.selected_source_capped_items_by_source.get(source_key, 0) + 1
        )
        if _source_policy.source_group_cap(item) is not None:
            source_group_key = _rendering.source_group_key(item)
            state.selected_art_style_items_by_source_group[source_group_key] = (
                state.selected_art_style_items_by_source_group.get(source_group_key, 0) + 1
            )
    state.used_tokens += item_tokens

def _selection_key(item: ContextItem) -> tuple[str, str]:
    return (item.item_type, item.item_id)

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
                priority.get(_identity.diversity_family_base(family), len(priority)),
                context_rank_key(candidates[family]),
                family,
            ),
        )
    )

def _diversity_family(item: ContextItem) -> str:
    if item.item_type == "anchor":
        return _identity.typed_diversity_family(
            "anchor",
            _diagnostics.diagnostic_text(item, "anchor_kind"),
        )
    if item.item_type == "extraction_artifact":
        return _identity.typed_diversity_family(
            "extraction_artifact",
            _identity.artifact_diversity_hint(item),
        )
    if item.item_type in _DIVERSITY_FAMILY_PRIORITY:
        return item.item_type
    return item.item_type or "unknown"

def _diversity_candidate_item_key(item: ContextItem) -> tuple[object, ...]:
    query_reason = _identity.answer_support_query_reason(item)
    broad_window_rank = 1
    if (
        query_reason in _DIVERSITY_PRECISE_TURN_REASONS
        and _identity.has_primary_exact_turn_source_ref(item)
    ) or (
        query_reason in _BROAD_EVIDENCE_ANSWER_SUPPORT_REASONS
        and len(item.source_refs) > 1
    ):
        broad_window_rank = 0
    return (
        broad_window_rank,
        context_rank_key(item),
    )

def _answer_support_diversity_candidates(items: list[ContextItem]) -> dict[str, ContextItem]:
    candidates: dict[str, ContextItem] = {}
    for item in items:
        family = _answer_support_diversity_family(item)
        if not family:
            continue
        existing = candidates.get(family)
        if existing is None or _answer_support_family_item_key(item) < (
            _answer_support_family_item_key(existing)
        ):
            candidates[family] = item
    return candidates

def _ordered_answer_support_families(candidates: dict[str, ContextItem]) -> tuple[str, ...]:
    marker_source_group_counts = _marker_coverage_source_group_counts(candidates)
    broad_turn_source_group_counts = _broad_turn_source_group_counts(candidates)
    ordered = tuple(
        sorted(
            candidates,
            key=lambda family: (
                _answer_support_family_priority(
                    family,
                    item=candidates[family],
                    marker_source_group_counts=marker_source_group_counts,
                    broad_turn_source_group_counts=broad_turn_source_group_counts,
                ),
                _answer_support_family_item_key(candidates[family]),
                family,
            ),
        )
    )
    return _round_robin_inventory_slot_families(ordered)

def _round_robin_inventory_slot_families(families: tuple[str, ...]) -> tuple[str, ...]:
    inventory_positions = tuple(
        index
        for index, family in enumerate(families)
        if _answer_support_inventory_family_slot(family)
    )
    if len(inventory_positions) < 3:
        return families
    slot_counts: dict[str, int] = {}
    ranked: list[tuple[int, int, int, str]] = []
    for index in inventory_positions:
        family = families[index]
        slot = _answer_support_inventory_family_slot(family)
        coverage_round = slot_counts.get(slot, 0)
        slot_counts[slot] = coverage_round + 1
        slot_priority = _answer_slots.inventory_answer_slot_priority(slot)
        if slot_priority >= 3:
            coverage_round += 2
        ranked.append((coverage_round, slot_priority, index, family))
    reranked_inventory = iter(family for _, _, _, family in sorted(ranked))
    inventory_position_set = set(inventory_positions)
    return tuple(
        next(reranked_inventory) if index in inventory_position_set else family
        for index, family in enumerate(families)
    )

def _answer_support_inventory_family_slot(family: str) -> str:
    if _identity.diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return ""
    return _answer_slots.inventory_answer_slot_from_family(family)

def _answer_support_family_priority(
    family: str,
    *,
    item: ContextItem,
    marker_source_group_counts: dict[str, int],
    broad_turn_source_group_counts: dict[str, int],
) -> int:
    base = _identity.diversity_family_base(family)
    if base == "query_reason_count_coverage_source_group":
        return 0
    if (
        base == "query_reason_broad_turn_source_group"
        and _identity.numeric_signal(
            _diagnostics.diagnostic_score_signals(item).get("book_author_preference_world_evidence")
        )
        >= 3
        and broad_turn_source_group_counts.get(_broad_turn_family_source_group(family), 0) > 1
    ):
        return 0
    if base in {
        "query_reason_activity_slot",
        "query_reason_activity_slot_source_group",
    }:
        return 0
    query_reason = _identity.answer_support_query_reason(item)
    if (
        base == "query_reason_broad_turn_source_group"
        and query_reason == "birdwatching_city_schedule_bridge"
    ):
        return 0
    if _answer_slots.is_pottery_type_reason(query_reason) and base in {
        "query_reason",
        "query_reason_marker_coverage_source_group",
        "query_reason_source_group",
    }:
        return 0
    if (
        base == "query_reason_marker_coverage_source_group"
        and _answer_slots.is_pottery_type_inventory_item(item, query_reason=query_reason)
    ):
        return 0
    if base in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return _answer_slots.inventory_answer_slot_priority(
            _answer_slots.inventory_answer_slot_from_family(family)
        )
    if base == "query_reason_marker_coverage_source_group":
        if _answer_slots.is_family_activity_reason(query_reason):
            return 4
        answer_object_rank = _answer_slots.answer_object_rank(
            item,
            query_reason=query_reason,
        )
        if answer_object_rank <= 1:
            return 1 + answer_object_rank
        source_group = _marker_coverage_family_source_group(family)
        if marker_source_group_counts.get(source_group, 0) > 1:
            return min(answer_object_rank + 1, 3)
        return min(answer_object_rank + 2, 5)
    return 2

def _marker_coverage_source_group_counts(candidates: dict[str, ContextItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for family in candidates:
        if _identity.diversity_family_base(family) != "query_reason_marker_coverage_source_group":
            continue
        source_group = _marker_coverage_family_source_group(family)
        if source_group:
            counts[source_group] = counts.get(source_group, 0) + 1
    return counts

def _broad_turn_source_group_counts(candidates: dict[str, ContextItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for family in candidates:
        if _identity.diversity_family_base(family) != "query_reason_broad_turn_source_group":
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
        "query_reason_career_slot_source_group",
        "query_reason_count_coverage_source_group",
        "query_reason_inference_slot_source_group",
        "query_reason_inventory_slot_source_group",
        "query_reason_marker_coverage_source_group",
        "query_reason_source_group",
    }:
        return ""
    if (
        parts[0] == "query_reason_activity_slot_source_group"
        and len(parts) >= 4
        and _answer_slots.is_family_activity_reason(parts[1])
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
    family_base = _identity.diversity_family_base(family)
    aggregation_family_bases = {
        "query_reason_activity_slot_source_group",
        "query_reason_broad_turn_source_group",
        "query_reason_career_slot_source_group",
        "query_reason_count_coverage_source_group",
        "query_reason_inference_slot_source_group",
        "query_reason_inventory_slot_source_group",
        "query_reason_marker_coverage_source_group",
    }
    if (
        reason in _ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS
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
    query_reason = _identity.answer_support_query_reason(item)
    if query_reason and query_reason != "original_query":
        if query_reason in _ANSWER_SUPPORT_EXCLUDED_QUERY_REASONS:
            return ""
        source_group = _identity.answer_support_source_group(item)
        career_slot = _answer_slots.career_answer_slot(item, query_reason=query_reason)
        activity_slot = _answer_slots.activity_answer_slot(item, query_reason=query_reason)
        inference_slot = _answer_slots.inference_answer_slot(item, query_reason=query_reason)
        inventory_slot = _answer_slots.inventory_answer_slot(item, query_reason=query_reason)
        if source_group:
            if broad_turn_slot := _broad_evidence_turn_slot(item, query_reason=query_reason):
                return _identity.compound_diversity_family(
                    "query_reason_broad_turn_source_group",
                    query_reason,
                    broad_turn_slot,
                    source_group,
                )
            if _is_count_aggregation_coverage_item(item, query_reason=query_reason):
                return _identity.compound_diversity_family(
                    "query_reason_count_coverage_source_group",
                    query_reason,
                    source_group,
                )
            if marker_slot := _aggregation_marker_coverage_slot(
                item,
                query_reason=query_reason,
            ):
                return _identity.compound_diversity_family(
                    "query_reason_marker_coverage_source_group",
                    query_reason,
                    marker_slot,
                    source_group,
                )
            if inventory_slot:
                return _identity.compound_diversity_family(
                    "query_reason_inventory_slot_source_group",
                    query_reason,
                    inventory_slot,
                    source_group,
                )
            if activity_slot:
                return _identity.compound_diversity_family(
                    "query_reason_activity_slot_source_group",
                    query_reason,
                    activity_slot,
                    source_group,
                )
            if career_slot:
                return _identity.compound_diversity_family(
                    "query_reason_career_slot_source_group",
                    query_reason,
                    career_slot,
                    source_group,
                )
            if inference_slot:
                return _identity.compound_diversity_family(
                    "query_reason_inference_slot_source_group",
                    query_reason,
                    inference_slot,
                    source_group,
                )
            if _diagnostics.diagnostic_signal_truthy(
                item,
                "source_sibling_dialogue_visual_reference",
            ):
                return _identity.compound_diversity_family(
                    "query_reason_source_group_visual_reference",
                    query_reason,
                    source_group,
                )
            return _identity.compound_diversity_family(
                "query_reason_source_group",
                query_reason,
                source_group,
            )
        if activity_slot:
            return _identity.compound_diversity_family(
                "query_reason_activity_slot",
                query_reason,
                activity_slot,
            )
        if inventory_slot:
            return _identity.compound_diversity_family(
                "query_reason_inventory_slot",
                query_reason,
                inventory_slot,
            )
        if career_slot:
            return _identity.compound_diversity_family(
                "query_reason_career_slot",
                query_reason,
                career_slot,
            )
        if inference_slot:
            return _identity.compound_diversity_family(
                "query_reason_inference_slot",
                query_reason,
                inference_slot,
            )
        return _identity.typed_diversity_family("query_reason", query_reason)

    matched_anchor_kinds = _diagnostics.diagnostic_list(
        item,
        "context_requirement_matched_anchor_kinds",
    )
    if matched_anchor_kinds:
        return _identity.typed_diversity_family("requirement_anchor", matched_anchor_kinds[0])

    matched_modalities = _diagnostics.diagnostic_list(
        item,
        "context_requirement_matched_modalities",
    )
    if matched_modalities:
        return _identity.typed_diversity_family("requirement_modality", matched_modalities[0])

    matched_features = _diagnostics.diagnostic_list(
        item,
        "context_requirement_matched_evidence_features",
    )
    if matched_features:
        return _identity.typed_diversity_family("requirement_feature", matched_features[0])

    return ""

def _is_count_aggregation_coverage_item(item: ContextItem, *, query_reason: str) -> bool:
    if query_reason not in _COUNT_AGGREGATION_COVERAGE_REASONS:
        return False
    if _identity.has_primary_exact_turn_source_ref(item):
        return False
    if "keyword_aggregation_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    return len(item.source_refs) > 1

def _broad_evidence_turn_slot(item: ContextItem, *, query_reason: str) -> str:
    if query_reason not in _BROAD_EVIDENCE_TURN_SLOT_REASONS:
        return ""
    if len(item.source_refs) != 1:
        return ""
    return _identity.primary_exact_turn_source_id(item)

def _aggregation_marker_coverage_slot(item: ContextItem, *, query_reason: str) -> str:
    normalized_reason = query_reason.replace("_", "-")
    if (
        query_reason not in _ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS
        and normalized_reason not in _ANSWER_SUPPORT_AGGREGATION_SOURCE_GROUP_REASONS
    ):
        return ""
    if not set(diagnostic_retrieval_sources(item.diagnostics)).intersection(
        {
            "keyword_aggregation_chunks",
            "keyword_chunks",
            "keyword_neighbor_chunks",
            "keyword_source_sibling_chunks",
        }
    ):
        return ""
    if _diagnostics.diagnostic_text(item, "source_type") != "locomo_observation":
        return ""
    if "related turns:" not in item.text.casefold():
        return ""
    markers = tuple(
        dict.fromkeys(match.group(0) for match in _DIALOGUE_MARKER_RE.finditer(item.text))
    )
    if len(markers) < 2:
        return ""
    return f"{markers[0]}-{markers[-1]}"

def _answer_support_family_item_key(item: ContextItem) -> tuple[float | int | str, ...]:
    signals = _diagnostics.diagnostic_score_signals(item)
    query_reason = _identity.answer_support_query_reason(item)
    if _is_count_aggregation_coverage_item(item, query_reason=query_reason):
        signal_rank = (
            -_identity.numeric_signal(signals.get("item_purchase_object_evidence")),
            -_identity.numeric_signal(signals.get("symbol_importance_visual_evidence")),
            -_identity.numeric_signal(signals.get("friend_place_shelter_anchor_evidence")),
            -_identity.numeric_signal(signals.get("cause_awareness_answer_evidence")),
            -_identity.numeric_signal(signals.get("choice_reason_answer_evidence")),
            -_identity.numeric_signal(signals.get("future_plan_timing_answer_evidence")),
            -_identity.numeric_signal(signals.get("birdwatching_city_schedule_answer_evidence")),
            -_identity.numeric_signal(signals.get("distinctive_term_hits")),
            -_identity.numeric_signal(signals.get("phrase_bigram_hits")),
        )
    else:
        signal_rank = (
            -_identity.numeric_signal(signals.get("item_purchase_object_evidence")),
            -_identity.numeric_signal(signals.get("symbol_importance_visual_evidence")),
            -_identity.numeric_signal(signals.get("friend_place_shelter_anchor_evidence")),
            -_identity.numeric_signal(signals.get("cause_awareness_answer_evidence")),
            -_identity.numeric_signal(signals.get("choice_reason_answer_evidence")),
            -_identity.numeric_signal(signals.get("future_plan_timing_answer_evidence")),
            -_identity.numeric_signal(signals.get("birdwatching_city_schedule_answer_evidence")),
            -_identity.numeric_signal(signals.get("phrase_bigram_hits")),
            -_identity.numeric_signal(signals.get("distinctive_term_hits")),
        )
    return (
        _precise_turn_answer_support_rank(item, query_reason=query_reason),
        _answer_slots.precise_answer_content_rank(item, query_reason=query_reason),
        _answer_slots.answer_object_rank(item, query_reason=query_reason),
        _marker_coverage_answer_support_rank(item, query_reason=query_reason),
        _birdwatching_city_schedule_exact_turn_rank(item, query_reason=query_reason),
        -len(item.source_refs),
        *signal_rank,
        -len(diagnostic_retrieval_sources(item.diagnostics)),
        context_rank_key(item),
    )

def _birdwatching_city_schedule_exact_turn_rank(item: ContextItem, *, query_reason: str) -> int:
    if query_reason != "birdwatching_city_schedule_bridge":
        return 0
    if _identity.has_any_exact_turn_source_ref(item) and len(item.source_refs) == 1:
        return 0
    return 1

def _marker_coverage_answer_support_rank(item: ContextItem, *, query_reason: str) -> int:
    if not _aggregation_marker_coverage_slot(item, query_reason=query_reason):
        return 0
    markers = tuple(
        dict.fromkeys(match.group(0) for match in _DIALOGUE_MARKER_RE.finditer(item.text))
    )
    return -len(markers)

def _precise_turn_answer_support_rank(item: ContextItem, *, query_reason: str) -> int:
    if _is_count_aggregation_coverage_item(item, query_reason=query_reason):
        return 0
    if (
        _answer_slots.is_family_activity_reason(query_reason)
        and _answer_slots.answer_object_rank(item, query_reason=query_reason) == 0
        and _identity.has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason == "birdwatching_city_schedule_bridge"
        and _identity.numeric_signal(
            _diagnostics.diagnostic_score_signals(item).get("birdwatching_city_schedule_answer_evidence")
        )
        >= 2
        and _identity.has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason == "birdwatching_city_schedule_bridge"
        and _answer_slots.birdwatching_city_schedule_answer_content_rank(item.text) <= 1
        and _identity.has_any_exact_turn_source_ref(item)
    ):
        return 0
    if query_reason in _BROAD_EVIDENCE_ANSWER_SUPPORT_REASONS:
        return 2
    if (
        query_reason in _COUNT_AGGREGATION_COVERAGE_REASONS
        and _identity.has_primary_exact_turn_source_ref(item)
    ):
        return 1
    if query_reason not in _PRECISE_TURN_ANSWER_SUPPORT_REASONS:
        return 2
    return 0 if _identity.has_primary_exact_turn_source_ref(item) else 1

def _context_render_rank_key(item: ContextItem) -> tuple[object, ...]:
    query_reason = _identity.answer_support_query_reason(item)
    if (
        query_reason in _PRECISE_TURN_ANSWER_SUPPORT_REASONS
        and _precise_turn_answer_support_rank(item, query_reason=query_reason) == 0
    ):
        return (
            0,
            _answer_slots.precise_answer_content_rank(item, query_reason=query_reason),
            _answer_slots.answer_object_rank(item, query_reason=query_reason),
            _answer_support_family_item_key(item),
            context_rank_key(item),
        )
    return (1, context_rank_key(item))

def _rendered_char_count(items: tuple[ContextItem, ...]) -> int:
    return _rendering.rendered_context_char_count(items, rank_key=_context_render_rank_key)
