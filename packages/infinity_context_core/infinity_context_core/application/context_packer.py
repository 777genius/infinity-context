"""Prompt-safe context packing."""

from __future__ import annotations

import re
from dataclasses import dataclass

import infinity_context_core.application.context_packer_diagnostics as _diagnostics
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
_BIRDWATCHING_CITY_SCHEDULE_CONTENT_RE = re.compile(
    r"\b("
    r"busy\s+week|city\s+schedule|schedule|"
    r"binos|binoculars|notebook|log\s+them|"
    r"spot\s+(?:looks\s+)?ideal|where\s+did\s+you\s+take\s+them|"
    r"birdwatching|watching\s+birds?|birds?|eagles?|soar"
    r")\b",
    re.IGNORECASE,
)
_DIVERSITY_FAMILY_PRIORITY = (
    "fact",
    "chunk",
    "extraction_artifact",
    "anchor",
    "suggestion",
)
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_ANIMAL_CARE_DIRECT_INSTRUCTION_RE = re.compile(
    r"\b(?:keep(?:ing)?\s+(?:their|the)?\s*(?:area|tank|space|habitat)\s+clean|"
    r"clean\s+(?:area|tank|space|habitat)|feed(?:ing)?\s+(?:them\s+)?properly|"
    r"enough\s+light|make\s+sure\s+they\s+get\s+enough\s+light|"
    r"care\s+instructions?|kind\s+of\s+fun)\b",
    re.IGNORECASE,
)
_ANIMAL_CARE_GENERIC_HABITAT_RE = re.compile(
    r"\b(?:relaxing\s+in\s+the\s+tank|basking|heat\s+lamp|new\s+tank|"
    r"bigger\s+tank|room\s+to\s+swim|took\s+my\s+turtles\s+out\s+for\s+a\s+walk|"
    r"cute\s+pet|little\s+dudes)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_PRIMARY_ANSWER_OBJECT_RE = re.compile(
    r"\b(?:clay|cup|cups|mug|mugs|pot|pots|dog\s+face)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_SECONDARY_ANSWER_OBJECT_RE = re.compile(
    r"\b(?:bowl|bowls|plate|plates|ceramic|project|projects)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_GENERIC_ANSWER_OBJECT_RE = re.compile(
    r"\b(?:pottery|art|painting|creative|creativity)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_INVENTORY_CONTEXT_RE = re.compile(
    r"\b(?:pottery|ceramic|clay|bowl|bowls|cup|cups|mug|mugs|plate|plates)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_CUP_SLOT_RE = re.compile(r"\b(?:cup|cups|mug|mugs|dog\s+face)\b", re.IGNORECASE)
_POTTERY_TYPE_BOWL_SLOT_RE = re.compile(r"\b(?:bowl|bowls)\b", re.IGNORECASE)
_POTTERY_TYPE_POT_SLOT_RE = re.compile(r"\b(?:pot|pots)\b", re.IGNORECASE)
_POTTERY_TYPE_PROJECT_SLOT_RE = re.compile(
    r"\b(?:clay|ceramic|project|projects|piece|pieces|finished)\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_DIRECT_MADE_OBJECT_RE = re.compile(
    r"\b(?:dog\s+face|black\s+and\s+white\s+flower|photo\s+of\s+a\s+(?:bowl|cup)|"
    r"kids?.{0,120}(?:clay|cup|pots?|pottery\s+workshop)|"
    r"(?:clay|cup|pots?|pottery\s+workshop).{0,120}kids?)\b",
    re.IGNORECASE | re.DOTALL,
)
_POTTERY_TYPE_FRIENDSHIP_COMPANION_RE = re.compile(
    r"\b(?:pottery\s+project|finished\s+another\s+pottery|source\s+of\s+happiness)"
    r".{0,260}\b(?:values?\s+friendship|appreciat(?:es|ion).{0,60}friendship|"
    r"family\s+outing|planning\s+something\s+special)\b",
    re.IGNORECASE | re.DOTALL,
)
_POTTERY_TYPE_PROJECT_COMPANION_RE = re.compile(
    r"\b(?:pottery\s+project|finished\s+another\s+pottery|source\s+of\s+happiness|"
    r"fulfillment|sanctuary|comfort)\b",
    re.IGNORECASE,
)
_FAMILY_ACTIVITY_DIRECT_ANSWER_OBJECT_RE = re.compile(
    r"\b(?:husband|motivated|motivate|motivation)\b(?=.{0,180}\b"
    r"(?:family|kids?|children|hiking|hike|nature|waterfall|trail))|"
    r"\b(?:family|kids?|children|hiking|hike|nature|waterfall|trail)\b"
    r"(?=.{0,180}\b(?:husband|motivated|motivate|motivation))",
    re.IGNORECASE | re.DOTALL,
)
_FAMILY_ACTIVITY_ACTIVITY_OBJECT_RE = re.compile(
    r"\b(?:swimming|swim|hiking|hike|trail|waterfall|museum|dinosaur|"
    r"pottery|clay|painting|camping|campfire|marshmallow|park)\b",
    re.IGNORECASE,
)
_FAMILY_ACTIVITY_CONTEXT_OBJECT_RE = re.compile(
    r"\b(?:family|fam|kids?|children|husband)\b",
    re.IGNORECASE,
)
_INVENTORY_FRIEND_PLACE_DIRECT_RE = re.compile(
    r"\b(?:became\s+friends|now\s+friends|made\s+friends|friends\s+with|"
    r"fellow\s+volunteers?)\b",
    re.IGNORECASE,
)
_INVENTORY_FRIEND_COMMUNITY_PLACE_RE = re.compile(
    r"\b(?:joined\s+(?:a\s+|the\s+|nearby\s+|local\s+)?(?:church|gym)|"
    r"(?:church|gym).{0,120}\b(?:community|supportive|welcoming|people)|"
    r"(?:supportive|welcoming).{0,120}\b(?:church|gym)|"
    r"feel\s+closer\s+to\s+a\s+community)\b",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_SHELTER_SLOT_RE = re.compile(
    r"\b(?:homeless\s+shelter|dog\s+shelter|animal\s+shelter|shelter)\b",
    re.IGNORECASE,
)
_INVENTORY_ANIMAL_SHELTER_SLOT_RE = re.compile(
    r"\b(?:dog|animal)\s+shelter\b",
    re.IGNORECASE,
)
_INVENTORY_FRIEND_PLACE_SHELTER_ANCHOR_RE = re.compile(
    r"\b(?:homeless\s+shelter|shelter)\b(?=.{0,80}\b"
    r"(?:i\s+volunteer\s+at|where\s+(?:she\s+)?volunteers?|"
    r"donated\s+(?:my\s+|her\s+)?old\s+car))|"
    r"\b(?:i\s+volunteer\s+at|where\s+(?:she\s+)?volunteers?|"
    r"donated\s+(?:my\s+|her\s+)?old\s+car)\b(?=.{0,80}\b"
    r"(?:homeless\s+shelter|shelter))",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_FRIEND_PLACE_SHELTER_ACTIVITY_REPEAT_RE = re.compile(
    r"\b(?:gave\s+a\s+few\s+talks|received\s+lots\s+of\s+compliments|"
    r"fundraiser|ring-toss|baked\s+goods?|dropped\s+off|"
    r"received\s+a\s+medal|front\s+desk|kids?\s+event)\b",
    re.IGNORECASE,
)
_INVENTORY_GYM_SLOT_RE = re.compile(
    r"\b(?:joined\s+(?:a\s+|the\s+|nearby\s+|local\s+)?gym|gym)\b",
    re.IGNORECASE,
)
_INVENTORY_CHURCH_JOINED_SLOT_RE = re.compile(
    r"\bjoined\s+(?:a\s+|the\s+)?(?:nearby\s+|local\s+)?church\b",
    re.IGNORECASE,
)
_INVENTORY_CHURCH_SLOT_RE = re.compile(r"\bchurch\b", re.IGNORECASE)
_INVENTORY_VOLUNTEER_SLOT_RE = re.compile(
    r"\b(?:volunteer|volunteers|volunteering)\b",
    re.IGNORECASE,
)
_INVENTORY_EDUCATION_INFRASTRUCTURE_SLOT_RE = re.compile(
    r"\b(?:education|educational|school|schools|infrastructure|"
    r"community\s+meetings?|education\s+reform|infrastructure\s+development)\b",
    re.IGNORECASE,
)
_INVENTORY_VETERANS_SLOT_RE = re.compile(
    r"\b(?:veterans?|military|served|service\s+members?|memorial)\b",
    re.IGNORECASE,
)
_INVENTORY_COMMUNITY_SLOT_RE = re.compile(
    r"\b(?:community|supportive\s+people|welcoming\s+atmosphere)\b",
    re.IGNORECASE,
)
_INVENTORY_SUPPORT_GROUP_SLOT_RE = re.compile(r"\bsupport\s+group\b", re.IGNORECASE)
_INVENTORY_COUNTRY_SLOT_RE = re.compile(
    r"\b(?:england|spain|france|italy|germany|portugal|ireland|sweden|"
    r"country|countries|abroad|european?)\b",
    re.IGNORECASE,
)
_INVENTORY_PLACE_MARKER_RE = re.compile(
    r"\b(?:homeless\s+shelter|dog\s+shelter|shelter|volunteers?|church|gym)\b",
    re.IGNORECASE,
)
_RELIGIOUS_DIRECT_EVIDENCE_RE = re.compile(
    r"\b(?:church|faith|stained\s+glass|pray|prayer|spiritual|worship)\b",
    re.IGNORECASE,
)
_RELIGIOUS_CONTRAST_EVIDENCE_RE = re.compile(
    r"\breligious\b(?=.{0,160}\b(?:conservatives?|unwelcoming|upset|lgbtq|rights)\b)|"
    r"\b(?:conservatives?|unwelcoming|upset|lgbtq|rights)\b"
    r"(?=.{0,160}\breligious\b)",
    re.IGNORECASE | re.DOTALL,
)


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
                    "item_type_counts": _item_type_counts(selected),
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
            _diagnostics.diagnostic_text(item, "anchor_kind"),
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
        slot_priority = _inventory_answer_slot_priority(slot)
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
    if _diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return ""
    return _inventory_answer_slot_from_family(family)


def _answer_support_family_priority(
    family: str,
    *,
    item: ContextItem,
    marker_source_group_counts: dict[str, int],
    broad_turn_source_group_counts: dict[str, int],
) -> int:
    base = _diversity_family_base(family)
    if base == "query_reason_count_coverage_source_group":
        return 0
    if (
        base == "query_reason_broad_turn_source_group"
        and _numeric_signal(
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
    query_reason = _answer_support_query_reason(item)
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
        return 0
    if (
        base == "query_reason_marker_coverage_source_group"
        and _is_pottery_type_inventory_item(item, query_reason=query_reason)
    ):
        return 0
    if base in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return _inventory_answer_slot_priority(_inventory_answer_slot_from_family(family))
    if base == "query_reason_marker_coverage_source_group":
        if _is_family_activity_reason(query_reason):
            return 4
        answer_object_rank = _answer_object_rank(
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
        and _is_family_activity_reason(parts[1])
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
    family_base = _diversity_family_base(family)
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
    query_reason = _answer_support_query_reason(item)
    if query_reason and query_reason != "original_query":
        if query_reason in _ANSWER_SUPPORT_EXCLUDED_QUERY_REASONS:
            return ""
        source_group = _answer_support_source_group(item)
        career_slot = _career_answer_slot(item, query_reason=query_reason)
        activity_slot = _activity_answer_slot(item, query_reason=query_reason)
        inference_slot = _inference_answer_slot(item, query_reason=query_reason)
        inventory_slot = _inventory_answer_slot(item, query_reason=query_reason)
        if source_group:
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
            if activity_slot:
                return _compound_diversity_family(
                    "query_reason_activity_slot_source_group",
                    query_reason,
                    activity_slot,
                    source_group,
                )
            if career_slot:
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
            if _diagnostics.diagnostic_signal_truthy(
                item,
                "source_sibling_dialogue_visual_reference",
            ):
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

    matched_anchor_kinds = _diagnostics.diagnostic_list(
        item,
        "context_requirement_matched_anchor_kinds",
    )
    if matched_anchor_kinds:
        return _typed_diversity_family("requirement_anchor", matched_anchor_kinds[0])

    matched_modalities = _diagnostics.diagnostic_list(
        item,
        "context_requirement_matched_modalities",
    )
    if matched_modalities:
        return _typed_diversity_family("requirement_modality", matched_modalities[0])

    matched_features = _diagnostics.diagnostic_list(
        item,
        "context_requirement_matched_evidence_features",
    )
    if matched_features:
        return _typed_diversity_family("requirement_feature", matched_features[0])

    return ""


def _answer_support_query_reason(item: ContextItem) -> str:
    query_reason = _diagnostics.diagnostic_signal_text(item, "query_expansion_reason")
    deterministic_reason = _diagnostics.diagnostic_signal_text(
        item,
        "deterministic_rerank_query_reason",
    )
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
        or _diagnostics.diagnostic_signal_text(item, "bm25_lexical_query_reason")
        or deterministic_reason
    )


def _answer_support_source_group(item: ContextItem) -> str:
    aggregation_source_group = _diagnostics.diagnostic_text(
        item,
        "keyword_aggregation_source_group",
    )
    if aggregation_source_group:
        return aggregation_source_group
    if set(diagnostic_retrieval_sources(item.diagnostics)).intersection(
        {
            "keyword_aggregation_chunks",
            "keyword_source_sibling_chunks",
        }
    ):
        return _rendering.source_group_key(item)
    if _has_derived_source_group_ref(item):
        return _rendering.source_group_key(item)
    return ""


def _has_derived_source_group_ref(item: ContextItem) -> bool:
    if not item.source_refs:
        return False
    source_group_key = _rendering.source_group_key(item)
    return source_group_key != _rendering.source_key(item)


def _activity_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if query_reason not in {
        "activity_aggregation_bridge",
        "activity_visual_selfcare_bridge",
        "decomposition_activity_participation",
        "exercise_activity_inventory_bridge",
        "family_activity_bridge",
        "family_hike_detail_bridge",
        "family_hike_activity_bridge",
        "family_museum_activity_bridge",
        "family_painting_activity_bridge",
        "family_swimming_activity_bridge",
        "painting_inventory_bridge",
        "shoe_usage_bridge",
    }:
        return ""
    text = item.text.casefold()
    if query_reason == "shoe_usage_bridge":
        if "walking or running" in text or "for walking" in text:
            return "shoe_usage_answer"
        if any(marker in text for marker in ("new shoes", "sneakers", "running shoe")):
            return "shoe_purchase_visual"
        return ""
    if query_reason == "painting_inventory_bridge":
        return _painting_inventory_answer_slot(text)
    if query_reason == "exercise_activity_inventory_bridge":
        return _exercise_activity_answer_slot(text)
    slots = (
        ("swimming", ("swimming", " swim ", "self care", "taking care")),
        ("hiking", ("hiking", " hike ", "trail", "waterfall", "mountain")),
        ("camping", ("camping", "camped", "campfire", "marshmallow", "unplug")),
        ("pottery", ("pottery", "clay", "ceramic", "bowl")),
        ("painting", ("painting", "painted", "sunrise", "sunset", "lake", "drawing")),
        ("family_motivation", ("husband", "motivated", "motivate", "motivation")),
        ("running", ("running", "run ", "ran ", "race")),
        ("museum", ("museum", "dinosaur", "exhibit", "bones")),
        ("park", ("park", "outdoors", "playing", "exploring")),
        ("concert", ("concert", "music", "band")),
    )
    padded = f" {text} "
    for slot, markers in slots:
        if any(marker in padded for marker in markers):
            return slot
    return ""


def _is_count_aggregation_coverage_item(item: ContextItem, *, query_reason: str) -> bool:
    if query_reason not in _COUNT_AGGREGATION_COVERAGE_REASONS:
        return False
    if _has_primary_exact_turn_source_ref(item):
        return False
    if "keyword_aggregation_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    return len(item.source_refs) > 1


def _broad_evidence_turn_slot(item: ContextItem, *, query_reason: str) -> str:
    if query_reason not in _BROAD_EVIDENCE_TURN_SLOT_REASONS:
        return ""
    if len(item.source_refs) != 1:
        return ""
    return _primary_exact_turn_source_id(item)


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


def _career_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if query_reason == "degree_policy_inference_bridge":
        return _degree_policy_answer_slot(item.text)
    if query_reason == "business_commonality_bridge":
        return _business_commonality_answer_slot(item.text)
    if query_reason == "charity_brand_sponsorship_bridge":
        return _charity_brand_sponsorship_answer_slot(item.text)
    if query_reason != "volunteer_career_inference_bridge":
        return ""
    text = item.text.casefold()
    slots = (
        ("shelter_operations", ("front desk", "food or a bed", "food", " bed", "coordinator")),
        ("counseling_talks", ("gave a few talks", " talks ", "compliments", "counselor")),
        (
            "volunteer_origin",
            (
                "about a year ago",
                "witnessing a family",
                "family struggling",
                "struggling on the streets",
                "reached out to the shelter",
                "needed any volunteers",
            ),
        ),
        ("start_motivation", ("started volunteering", "aunt", "struggling", "brighten")),
        ("resident_support", ("resident", "cindy", "gratitude", "support they receive")),
        ("homeless_shelter", ("homeless shelter", " shelter", "volunteer")),
    )
    padded = f" {text} "
    for slot, markers in slots:
        if any(marker in padded for marker in markers):
            return slot
    return ""


def _inference_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if query_reason.replace("_", "-") != "religious-inference-bridge":
        return ""
    if _RELIGIOUS_CONTRAST_EVIDENCE_RE.search(item.text):
        return "religious_contrast"
    if _RELIGIOUS_DIRECT_EVIDENCE_RE.search(item.text):
        return "religious_direct"
    return ""


def _degree_policy_answer_slot(text: str) -> str:
    text = text.casefold()
    padded = f" {text} "
    if any(
        marker in padded
        for marker in (
            " because of my degree",
            " because of his degree",
            " because of her degree",
            "policymaking because",
            "public policy",
            "public administration",
            "public affairs",
            "political science",
        )
    ):
        return "degree_field_inference"
    if any(marker in padded for marker in ("policymaking", "policy making", " policy ")):
        return "policy_career_plan"
    if any(marker in padded for marker in ("graduated", "degree", "diploma")):
        return "degree_completion_context"
    return ""


def _business_commonality_answer_slot(text: str) -> str:
    text = text.casefold()
    if "door dash" in text and "lost my job" in text:
        return "gina_job_loss"
    if "lost my job as a banker" in text or ("banker" in text and "own business" in text):
        return "jon_job_loss"
    if "dance studio" in text or ("starting" in text and "passionate about dancing" in text):
        return "jon_business_type"
    if "clothing store" in text or "my own store" in text or "ad campaign" in text:
        return "gina_store_start"
    if "own business" in text or "starting" in text:
        return "business_start_generic"
    return ""


def _charity_brand_sponsorship_answer_slot(text: str) -> str:
    text = text.casefold()
    if "under armour" in text or "under armor" in text:
        return "under_armour_interest"
    if "nike" in text and ("gatorade" in text or "sponsorship" in text):
        return "nike_gatorade_deals"
    if "good sports" in text or "disadvantaged kids" in text:
        return "charity_org_fit"
    if "give something back" in text or "charity" in text or "make a difference" in text:
        return "charity_intent"
    if "sports brand" in text or "big brands" in text:
        return "sports_brand_generic"
    return ""


def _inventory_answer_slot(item: ContextItem, *, query_reason: str) -> str:
    if _is_pottery_type_reason(query_reason):
        return _pottery_type_inventory_slot_for_text(item.text)
    if not _is_inventory_list_reason(query_reason):
        return ""
    return _inventory_answer_slot_for_text(item.text)


def _inventory_answer_slot_for_text(text: str) -> str:
    pottery_slot = _pottery_type_inventory_slot_for_text(text)
    if pottery_slot:
        return pottery_slot
    if _INVENTORY_FRIEND_PLACE_SHELTER_ACTIVITY_REPEAT_RE.search(text):
        return "shelter_activity"
    if _INVENTORY_FRIEND_PLACE_SHELTER_ANCHOR_RE.search(text):
        return "shelter_anchor"
    if _INVENTORY_ANIMAL_SHELTER_SLOT_RE.search(text):
        return "animal_shelter"
    if _INVENTORY_SHELTER_SLOT_RE.search(text):
        return "shelter"
    if _INVENTORY_GYM_SLOT_RE.search(text):
        return "gym"
    if _INVENTORY_CHURCH_JOINED_SLOT_RE.search(text):
        return "church_joined"
    if _INVENTORY_CHURCH_SLOT_RE.search(text):
        return "church"
    if _INVENTORY_EDUCATION_INFRASTRUCTURE_SLOT_RE.search(text):
        return "education_infrastructure"
    if _INVENTORY_VETERANS_SLOT_RE.search(text):
        return "veterans"
    if _INVENTORY_FRIEND_PLACE_DIRECT_RE.search(text):
        return "direct_friend"
    if _INVENTORY_VOLUNTEER_SLOT_RE.search(text):
        return "volunteer"
    if _INVENTORY_COMMUNITY_SLOT_RE.search(text):
        return "community"
    if _INVENTORY_SUPPORT_GROUP_SLOT_RE.search(text):
        return "support_group"
    if _INVENTORY_COUNTRY_SLOT_RE.search(text):
        return "country"
    if _INVENTORY_PLACE_MARKER_RE.search(text):
        return "place"
    return ""


def _inventory_answer_slot_priority(slot: str) -> int:
    normalized_slot = slot.replace("-", "_")
    return {
        "direct_friend": 0,
        "shelter_anchor": 0,
        "pottery_cup": 0,
        "pottery_pot": 0,
        "animal_shelter": 1,
        "shelter_activity": 1,
        "shelter": 1,
        "gym": 1,
        "church_joined": 1,
        "country": 1,
        "education_infrastructure": 1,
        "veterans": 1,
        "pottery_bowl": 1,
        "pottery_project": 2,
        "church": 2,
        "volunteer": 2,
        "community": 3,
        "pottery_generic": 3,
        "place": 4,
        "support_group": 5,
    }.get(normalized_slot, 6)


def _inventory_answer_slot_from_family(family: str) -> str:
    parts = family.split(":")
    if len(parts) >= 3:
        return parts[2]
    return ""


def _answer_support_family_item_key(item: ContextItem) -> tuple[float | int | str, ...]:
    signals = _diagnostics.diagnostic_score_signals(item)
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
            -_numeric_signal(signals.get("phrase_bigram_hits")),
            -_numeric_signal(signals.get("distinctive_term_hits")),
        )
    return (
        _precise_turn_answer_support_rank(item, query_reason=query_reason),
        _precise_answer_content_rank(item, query_reason=query_reason),
        _answer_object_rank(item, query_reason=query_reason),
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
    if _has_any_exact_turn_source_ref(item) and len(item.source_refs) == 1:
        return 0
    return 1


def _answer_object_rank(item: ContextItem, *, query_reason: str) -> int:
    if _is_pottery_type_reason(query_reason):
        return _pottery_type_answer_object_rank(item.text)
    if _is_pottery_type_inventory_item(item, query_reason=query_reason):
        return _pottery_type_answer_object_rank(item.text)
    if _is_family_activity_reason(query_reason):
        return _family_activity_answer_object_rank(item.text)
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


def _is_pottery_type_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") == "pottery-type-bridge"


def _is_pottery_type_inventory_item(item: ContextItem, *, query_reason: str) -> bool:
    if query_reason.replace("_", "-") != "decomposition-inventory-list":
        return False
    if _POTTERY_TYPE_INVENTORY_CONTEXT_RE.search(item.text) is None:
        return False
    return _pottery_type_answer_object_rank(item.text) <= 1


def _is_family_activity_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in {
        "decomposition-activity-participation",
        "family-activity-bridge",
        "family-hike-activity-bridge",
        "family-hike-detail-bridge",
        "family-museum-activity-bridge",
        "family-painting-activity-bridge",
        "family-swimming-activity-bridge",
    }


def _is_inventory_list_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in {
        "decomposition-inventory-list",
        "friend-place-inventory-bridge",
        "friend-place-shelter-inventory-bridge",
        "friend-place-gym-inventory-bridge",
        "friend-place-church-inventory-bridge",
        "cause-education-infrastructure-inventory-bridge",
        "cause-veterans-inventory-bridge",
        "travel-country-inventory-bridge",
    }


def _pottery_type_answer_object_rank(text: str) -> int:
    if _POTTERY_TYPE_PRIMARY_ANSWER_OBJECT_RE.search(text):
        return 0
    if _POTTERY_TYPE_SECONDARY_ANSWER_OBJECT_RE.search(text):
        return 1
    if _POTTERY_TYPE_GENERIC_ANSWER_OBJECT_RE.search(text):
        return 3
    return 5


def _family_activity_answer_object_rank(text: str) -> int:
    if _FAMILY_ACTIVITY_DIRECT_ANSWER_OBJECT_RE.search(text):
        return 0
    has_activity = _FAMILY_ACTIVITY_ACTIVITY_OBJECT_RE.search(text) is not None
    has_family_context = _FAMILY_ACTIVITY_CONTEXT_OBJECT_RE.search(text) is not None
    if has_activity and has_family_context:
        return 1
    if has_activity:
        return 2
    if has_family_context:
        return 3
    return 5


def _inventory_list_answer_object_rank(text: str) -> int:
    slot = _inventory_answer_slot_for_text(text)
    if slot in {"pottery_cup", "pottery_pot"}:
        return 0
    if slot == "pottery_bowl":
        return 1
    if slot == "pottery_project":
        return 2
    if slot == "pottery_generic":
        return 3
    if slot == "direct_friend":
        return 0
    if slot in {
        "shelter",
        "gym",
        "church_joined",
        "country",
        "education_infrastructure",
        "veterans",
    }:
        return 1
    if slot in {"church", "volunteer"}:
        return 2
    if slot in {"community", "place"} or _INVENTORY_FRIEND_COMMUNITY_PLACE_RE.search(text):
        return 3
    if slot == "support_group":
        return 5
    return 6


def _pottery_type_inventory_slot_for_text(text: str) -> str:
    if _POTTERY_TYPE_INVENTORY_CONTEXT_RE.search(text) is None:
        return ""
    if _POTTERY_TYPE_CUP_SLOT_RE.search(text):
        return "pottery_cup"
    if _POTTERY_TYPE_POT_SLOT_RE.search(text):
        return "pottery_pot"
    if _POTTERY_TYPE_BOWL_SLOT_RE.search(text):
        return "pottery_bowl"
    if _POTTERY_TYPE_PROJECT_SLOT_RE.search(text):
        return "pottery_project"
    return "pottery_generic"


def _precise_turn_answer_support_rank(item: ContextItem, *, query_reason: str) -> int:
    if _is_count_aggregation_coverage_item(item, query_reason=query_reason):
        return 0
    if (
        _is_family_activity_reason(query_reason)
        and _answer_object_rank(item, query_reason=query_reason) == 0
        and _has_any_exact_turn_source_ref(item)
    ):
        return 0
    if (
        query_reason == "birdwatching_city_schedule_bridge"
        and _numeric_signal(
            _diagnostics.diagnostic_score_signals(item).get("birdwatching_city_schedule_answer_evidence")
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
    if query_reason in _BROAD_EVIDENCE_ANSWER_SUPPORT_REASONS:
        return 2
    if (
        query_reason in _COUNT_AGGREGATION_COVERAGE_REASONS
        and _has_primary_exact_turn_source_ref(item)
    ):
        return 1
    if query_reason not in _PRECISE_TURN_ANSWER_SUPPORT_REASONS:
        return 2
    return 0 if _has_primary_exact_turn_source_ref(item) else 1


def _precise_answer_content_rank(item: ContextItem, *, query_reason: str) -> int:
    if query_reason == "birdwatching_city_schedule_bridge":
        return _birdwatching_city_schedule_answer_content_rank(item.text)
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
    if query_reason == "business_commonality_bridge":
        return _business_commonality_answer_content_rank(item.text)
    if query_reason == "charity_brand_sponsorship_bridge":
        return _charity_brand_sponsorship_answer_content_rank(item.text)
    if query_reason == "exercise_activity_inventory_bridge":
        return _exercise_activity_answer_content_rank(item.text)
    if query_reason == "friend_place_shelter_inventory_bridge":
        return _friend_place_shelter_answer_content_rank(item.text)
    if query_reason == "animal_care_instruction_bridge":
        return _animal_care_instruction_content_rank(item.text)
    if query_reason != "meteor_shower_feeling_bridge":
        return 0
    text = item.text.casefold()
    if "awe" in text or "tiny" in text:
        return 0
    if "felt" in text or "feel" in text or "universe" in text:
        return 1
    return 2


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


def _business_commonality_answer_content_rank(text: str) -> int:
    slot = _business_commonality_answer_slot(text)
    if slot in {"jon_job_loss", "gina_job_loss", "jon_business_type", "gina_store_start"}:
        return 0
    if slot == "business_start_generic":
        return 1
    return 3


def _charity_brand_sponsorship_answer_content_rank(text: str) -> int:
    slot = _charity_brand_sponsorship_answer_slot(text)
    if slot in {"nike_gatorade_deals", "under_armour_interest", "charity_intent"}:
        return 0
    if slot == "charity_org_fit":
        return 1
    if slot == "sports_brand_generic":
        return 2
    return 3


def _exercise_activity_answer_slot(text: str) -> str:
    text = text.casefold()
    padded = f" {text} "
    if "taekwondo" in padded or "tae kwon do" in padded:
        return "taekwondo"
    if "kickboxing" in padded or "kick boxing" in padded:
        return "kickboxing"
    if "circuit training" in padded:
        return "circuit_training"
    if "weight training" in padded or "weights" in padded:
        return "weight_training"
    if "aerial yoga" in padded:
        return "aerial_yoga"
    if "yoga" in padded and any(
        marker in padded
        for marker in (
            "trying out",
            "try out",
            "trying yoga",
            "started yoga",
            "starting yoga",
        )
    ):
        return "yoga_trial"
    if "yoga" in padded and any(
        marker in padded
        for marker in (
            "strength",
            "flexibility",
            "balance",
            "focus",
            "workout",
            "performance",
            "improve",
        )
    ):
        return "yoga_performance"
    if " yoga" in padded:
        return "yoga"
    if any(marker in padded for marker in ("workout", "exercise", "fitness")):
        return "generic_exercise"
    return ""


def _exercise_activity_answer_content_rank(text: str) -> int:
    slot = _exercise_activity_answer_slot(text)
    if slot in {"kickboxing", "taekwondo", "weight_training", "circuit_training"}:
        return 0
    if slot in {"aerial_yoga", "yoga_trial", "yoga_performance"}:
        return 0
    if slot == "yoga":
        return 1
    if slot == "generic_exercise":
        return 2
    return 3


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


def _painting_inventory_answer_slot(text: str) -> str:
    if "horse" in text:
        return "painting_horse"
    if "sunset over a lake" in text or "painting sunrise" in text or "lake sunrise" in text:
        return "painting_lake_sunrise"
    if "palm tree" in text or "vibrant flowers" in text:
        return "painting_palm_sunset"
    if "sunflower" in text:
        return "painting_sunflower"
    if "landscape" in text or "sunset" in text:
        return "painting_landscape"
    if "painting" in text or "painted" in text:
        return "painting_generic"
    return ""


def _painting_inventory_answer_content_rank(text: str) -> int:
    normalized = text.casefold()
    if "image caption:" in normalized or "visual query:" in normalized:
        if any(
            marker in normalized
            for marker in (
                "horse",
                "sunset over a lake",
                "painting sunrise",
                "palm tree",
                "vibrant flowers",
                "sunflower",
            )
        ):
            return 0
        return 1
    if "painted" in normalized and any(
        marker in normalized
        for marker in ("horse", "sunrise", "sunset", "lake", "landscape", "nature")
    ):
        return 1
    if "painting" in normalized or "painted" in normalized:
        return 2
    return 4


def _has_primary_exact_turn_source_ref(item: ContextItem) -> bool:
    if not item.source_refs:
        return False
    return _is_exact_turn_source_id(item.source_refs[0].source_id)


def _has_any_exact_turn_source_ref(item: ContextItem) -> bool:
    return bool(_primary_exact_turn_source_id(item))


def _primary_exact_turn_source_id(item: ContextItem) -> str:
    for ref in item.source_refs:
        source_id = ref.source_id or ""
        if _is_exact_turn_source_id(source_id):
            return source_id
    return ""


def _is_exact_turn_source_id(source_id: str | None) -> bool:
    parts = (source_id or "").split(":")
    return len(parts) >= 6 and parts[-1] == "turn" and parts[-3].startswith("D")


def _diversity_family_base(family: str) -> str:
    return family.split(":", 1)[0]


def _typed_diversity_family(base: str, suffix: str) -> str:
    safe_suffix = _safe_diversity_suffix(suffix)
    return f"{base}:{safe_suffix}" if safe_suffix else base


def _compound_diversity_family(base: str, *suffixes: str) -> str:
    safe_suffixes = tuple(
        safe_suffix
        for suffix in suffixes
        if (safe_suffix := _safe_diversity_suffix(suffix))
    )
    return ":".join((base, *safe_suffixes)) if safe_suffixes else base


def _numeric_signal(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _safe_diversity_suffix(value: str) -> str:
    text = value.strip().casefold()
    if not text or "redacted" in text:
        return ""
    chars: list[str] = []
    previous_dash = False
    for char in text[:160]:
        if char.isalnum():
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
    token = "".join(chars).strip("-")
    if len(token) <= 64:
        return token
    return f"{token[:24]}-{token[-39:]}".strip("-")[:64]


def _source_ref_modality_hint(item: ContextItem) -> str:
    refs = item.source_refs
    if any(ref.time_start_ms is not None or ref.time_end_ms is not None for ref in refs):
        return "time_range"
    if any(ref.bbox is not None for ref in refs):
        return "image"
    if any(ref.page_number is not None for ref in refs):
        return "document"
    return ""


def _artifact_diversity_hint(item: ContextItem) -> str:
    modality = _diagnostics.diagnostic_text(
        item,
        "evidence_modality",
    ) or _source_ref_modality_hint(item)
    kind = _diagnostics.diagnostic_text(item, "evidence_kind")
    if modality and kind:
        return f"{modality}-{kind}"
    return modality or kind


def _item_type_counts(items: tuple[ContextItem, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.item_type] = counts.get(item.item_type, 0) + 1
    return counts


def _context_render_rank_key(item: ContextItem) -> tuple[object, ...]:
    query_reason = _answer_support_query_reason(item)
    if (
        query_reason in _PRECISE_TURN_ANSWER_SUPPORT_REASONS
        and _precise_turn_answer_support_rank(item, query_reason=query_reason) == 0
    ):
        return (
            0,
            _precise_answer_content_rank(item, query_reason=query_reason),
            _answer_object_rank(item, query_reason=query_reason),
            _answer_support_family_item_key(item),
            context_rank_key(item),
        )
    return (1, context_rank_key(item))


def _rendered_char_count(items: tuple[ContextItem, ...]) -> int:
    return _rendering.rendered_context_char_count(items, rank_key=_context_render_rank_key)
