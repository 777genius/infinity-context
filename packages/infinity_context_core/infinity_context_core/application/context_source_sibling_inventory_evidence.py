"""Inventory answer evidence helpers for source-sibling retrieval."""

from __future__ import annotations

from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slots,
)

_SOURCE_SIBLING_INVENTORY_SLOTS_BY_REASON = {
    "game_win_count_bridge": frozenset({"game_win_result"}),
    "skill_teaching_inventory_bridge": frozenset(
        {"skill_game_coaching", "skill_recipe_teaching"}
    ),
    "volunteering_inventory_bridge": frozenset({"shelter_food_dropoff"}),
    "volunteering_people_inventory_bridge": frozenset({"gratitude_note_writer"}),
}


def source_sibling_inventory_answer_slot_count(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> int:
    expected_slots = _SOURCE_SIBLING_INVENTORY_SLOTS_BY_REASON.get(expansion_reason)
    if not expected_slots:
        return 0
    return len(aggregation_answer_slots(query=expansion_query, text=text) & expected_slots)
