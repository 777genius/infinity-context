"""Inventory and grouped-evidence packing prepasses."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import context_rank_key
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
)
from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_family_item_key_for_query,
    _answer_support_query_reason,
    _answer_support_source_group_reason_key,
    _has_any_exact_turn_source_ref,
    _is_community_participation_reason,
    _is_exact_cause_inventory_answer_support_item,
    _is_pet_acquisition_date_anchor_answer_support_item,
    _primary_exact_turn_source_id,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _diagnostic_text,
)
from infinity_context_core.application.context_packer_exact_turn_utils import (
    _exact_cause_inventory_directness_rank,
    _exact_cause_inventory_slot,
    _primary_exact_turn_marker,
)
from infinity_context_core.application.context_packer_inventory_slots import (
    _answer_support_exact_turn_alignment_rank,
    _community_participation_inventory_slot_for_text,
    _exercise_activity_answer_directness_rank,
    _game_inventory_answer_directness_rank,
    _game_inventory_slot_for_text,
)
from infinity_context_core.application.context_packer_marker_coverage import (
    _gift_joy_source_group_rank,
    _is_gift_joy_source_group_answer_item,
)
from infinity_context_core.application.context_packer_selection import (
    _SelectionState,
    _try_select_item,
)
from infinity_context_core.application.dto import ContextItem

_MAX_EXACT_CAUSE_INVENTORY_TURN_ITEMS = 6
_MAX_EXACT_GAME_INVENTORY_TURN_ITEMS = 8
_MAX_EXACT_PET_ACQUISITION_TURN_ITEMS = 4
_MAX_GIFT_JOY_SOURCE_GROUP_ITEMS = 4
_GAME_INVENTORY_QUERY_RE = re.compile(
    r"\b(?:board\s+games?|tabletop\s+games?|video\s+games?|videogames?)\b",
    re.IGNORECASE,
)
_GIFT_JOY_QUERY_RE = re.compile(
    r"\b(?:gave|give|gift(?:ed)?|present(?:ed)?|got)\b"
    r"(?=.{0,180}\b(?:joy|happy|happiness|cheer|comfort|cherish|"
    r"focus(?:ed)?|remind(?:s|ed)?|good\s+vibes?)\b)|"
    r"\b(?:joy|happy|happiness|cheer|comfort|cherish|focus(?:ed)?|"
    r"remind(?:s|ed)?|good\s+vibes?)\b"
    r"(?=.{0,180}\b(?:gave|give|gift(?:ed)?|present(?:ed)?|got)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_INVENTORY_ANSWER_REASONS = frozenset(
    {
        "children_name_inventory_bridge",
        "childhood_possession_inventory_bridge",
        "board_game_inventory_bridge",
        "exercise_activity_inventory_bridge",
        "family_hardship_support_bridge",
        "fundraiser_event_inventory_bridge",
        "item_purchase_bridge",
        "repeated_test_attempt_bridge",
        "veterans_event_inventory_bridge",
    }
)


def _select_exact_cause_inventory_turn_items(
    state: _SelectionState,
    *,
    answer_support_families: dict[str, ContextItem],
    query: str,
    budget: int,
    char_budget: int,
    source_group_items_by_reason: dict[str, int],
) -> int:
    ranked: list[tuple[tuple[object, ...], str, ContextItem]] = []
    for family, item in answer_support_families.items():
        if not _is_exact_cause_inventory_answer_support_item(item):
            continue
        if (
            len(item.source_refs) != 1
            and _diagnostic_text(item, "source_type") == "locomo_observation"
        ):
            continue
        primary_source_id = _primary_exact_turn_source_id(item)
        if not primary_source_id:
            continue
        direct_rank = _exact_cause_inventory_directness_rank(item)
        if direct_rank > 1:
            continue
        ranked.append(
            (
                (
                    direct_rank,
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                    family,
                ),
                family,
                item,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    selected_slots: dict[str, int] = {}
    for _, family, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_CAUSE_INVENTORY_TURN_ITEMS:
            break
        slot = _exact_cause_inventory_slot(item)
        if not slot:
            continue
        slot_limit = (
            3
            if slot
            in {
                "cause_shelter_toy_drive",
                "education_infrastructure",
            }
            else 1
        )
        if selected_slots.get(slot, 0) >= slot_limit:
            continue
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
            selected_slots[slot] = selected_slots.get(slot, 0) + 1
            source_group_reason = _answer_support_source_group_reason_key(family)
            if source_group_reason:
                source_group_items_by_reason[source_group_reason] = (
                    source_group_items_by_reason.get(source_group_reason, 0) + 1
                )
    return selected


def _select_exact_game_inventory_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    if _GAME_INVENTORY_QUERY_RE.search(query) is None:
        return 0
    ranked: list[tuple[tuple[object, ...], ContextItem, str]] = []
    for item in items:
        if not _has_any_exact_turn_source_ref(item):
            continue
        if len(item.source_refs) != 1:
            continue
        if _answer_support_query_reason(item) != "board_game_inventory_bridge":
            continue
        if _game_inventory_answer_directness_rank(item.text) != 0:
            continue
        inventory_slot = _game_inventory_slot_for_text(item.text)
        if not inventory_slot:
            continue
        alignment_rank = _answer_support_exact_turn_alignment_rank(
            text=item.text,
            source_ids=tuple(str(ref.source_id) for ref in item.source_refs),
            inventory_slot=inventory_slot,
            slot_detector=_game_inventory_slot_for_text,
            query_reason=_answer_support_query_reason(item),
        )
        if alignment_rank > 0:
            continue
        ranked.append(
            (
                (
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                item,
                inventory_slot,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    selected_slots: set[str] = set()
    for _, item, inventory_slot in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_GAME_INVENTORY_TURN_ITEMS:
            break
        if inventory_slot in selected_slots:
            continue
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
            selected_slots.add(inventory_slot)
    return selected


def _select_exact_pet_acquisition_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        if not _is_pet_acquisition_date_anchor_answer_support_item(item):
            continue
        ranked.append(
            (
                (
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                item,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_PET_ACQUISITION_TURN_ITEMS:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
    return selected


def _select_gift_joy_source_group_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    if _GIFT_JOY_QUERY_RE.search(query) is None:
        return 0
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        if not _is_gift_joy_source_group_answer_item(item):
            continue
        ranked.append(
            (
                (
                    _gift_joy_source_group_rank(item),
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                item,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_GIFT_JOY_SOURCE_GROUP_ITEMS:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
    return selected


def _is_exact_inventory_answer_family(item: ContextItem) -> bool:
    query_reason = _answer_support_query_reason(item)
    if not _has_any_exact_turn_source_ref(item):
        return False
    if _is_exact_cause_inventory_answer_support_item(item):
        return len(item.source_refs) == 1 and bool(_primary_exact_turn_source_id(item))
    if _is_community_participation_reason(query_reason):
        return _community_participation_inventory_slot_for_text(item.text) in {
            "community_activist_group",
            "community_art_show",
            "community_mentorship_program",
            "community_pride_event",
        }
    if query_reason not in _EXACT_INVENTORY_ANSWER_REASONS:
        return False
    text = f" {item.text.casefold()} "
    if query_reason == "children_name_inventory_bridge":
        return any(marker in text for marker in (" son ", " daughter ", " child ", " kid "))
    if query_reason == "childhood_possession_inventory_bridge":
        return any(marker in text for marker in ("childhood", "as a kid", "when younger")) and any(
            marker in text for marker in (" had ", " owned ", "used to have", "reminds")
        )
    if query_reason == "family_hardship_support_bridge":
        return any(marker in text for marker in ("money problem", "financial", "hardship")) and any(
            marker in text for marker in ("younger", "outside help", "struggling")
        )
    if query_reason == "item_purchase_bridge":
        return has_item_purchase_object_evidence(item.text)
    if query_reason == "board_game_inventory_bridge":
        return _game_inventory_answer_directness_rank(item.text) == 0
    if query_reason == "exercise_activity_inventory_bridge":
        return _exercise_activity_answer_directness_rank(item.text) == 0
    if query_reason == "veterans_event_inventory_bridge":
        return "veteran" in text and any(
            marker in text for marker in ("hospital", "petition", "march", "charity run", "5k")
        )
    if query_reason in {
        "decomposition_inventory_list",
        "fundraiser_event_inventory_bridge",
    }:
        return "fundraiser" in text and any(
            marker in text for marker in ("tournament", "cook-off", "planning")
        )
    return " test" in text and any(
        marker in text for marker in ("retook", "retake", "failed", "again", "results")
    )
