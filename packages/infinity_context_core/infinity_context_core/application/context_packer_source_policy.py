"""Source cap and diversity policy for context packing."""

from __future__ import annotations

import infinity_context_core.application.context_packer_diagnostics as _diagnostics
import infinity_context_core.application.context_packer_rendering as _rendering
from infinity_context_core.application.dto import ContextItem

MAX_ITEMS_PER_SOURCE = 4
MAX_ART_STYLE_ITEMS_PER_SOURCE_GROUP = 4
SOURCE_CAPPED_ITEM_TYPES = frozenset({"chunk", "extraction_artifact"})


def source_cap_applies(item: ContextItem) -> bool:
    return item.item_type in SOURCE_CAPPED_ITEM_TYPES


def source_group_cap(item: ContextItem) -> int | None:
    if not source_cap_applies(item):
        return None
    if _diagnostics.diagnostic_text(item, "query_expansion_reason") == "art_style_bridge":
        return MAX_ART_STYLE_ITEMS_PER_SOURCE_GROUP
    return None


def source_diversity_key(item: ContextItem) -> str:
    item_source_key = _rendering.source_key(item)
    if not source_cap_applies(item):
        return item_source_key
    item_source_group_key = _rendering.source_group_key(item)
    if item_source_group_key != item_source_key:
        return item_source_group_key
    return item_source_key


def chunk_source_counts(items: tuple[ContextItem, ...] | list[ContextItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if item.item_type != "chunk":
            continue
        item_source_key = _rendering.source_key(item)
        counts[item_source_key] = counts.get(item_source_key, 0) + 1
    return counts


def source_capped_source_counts(
    items: tuple[ContextItem, ...] | list[ContextItem],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if not source_cap_applies(item):
            continue
        item_source_key = _rendering.source_key(item)
        counts[item_source_key] = counts.get(item_source_key, 0) + 1
    return counts


def source_diversified_order(items: list[ContextItem]) -> tuple[ContextItem, ...]:
    source_positions: dict[str, int] = {}
    indexed: list[tuple[int, int, ContextItem]] = []
    for index, item in enumerate(items):
        if item.item_type != "chunk":
            indexed.append((0, index, item))
            continue
        source_position_key = source_diversity_key(item)
        source_position = source_positions.get(source_position_key, 0)
        source_positions[source_position_key] = source_position + 1
        indexed.append((source_position, index, item))
    return tuple(item for _, _, item in sorted(indexed, key=lambda value: (value[0], value[1])))


def source_diversity_reordered_chunk_count(
    original_items: list[ContextItem],
    ordered_items: tuple[ContextItem, ...],
) -> int:
    original_chunk_positions = {
        selection_key(item): index
        for index, item in enumerate(original_items)
        if item.item_type == "chunk"
    }
    return sum(
        1
        for index, item in enumerate(ordered_items)
        if item.item_type == "chunk" and original_chunk_positions.get(selection_key(item)) != index
    )


def selection_key(item: ContextItem) -> tuple[str, str]:
    return (item.item_type, item.item_id)
