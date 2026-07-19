"""Source cap and deterministic diversity policy for context packing."""

from __future__ import annotations

from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_query_reason,
    _diagnostic_score_signals,
    _has_any_exact_turn_source_ref,
    _precise_turn_answer_support_rank,
)
from infinity_context_core.application.context_packer_answer_support_patterns import (
    _PRECISE_TURN_ANSWER_SUPPORT_REASONS,
    _SUPPORT_NETWORK_DIRECT_ANSWER_RE,
)
from infinity_context_core.application.context_packer_diagnostics import diagnostic_text
from infinity_context_core.application.context_packer_rendering import (
    source_group_key,
    source_key,
)
from infinity_context_core.application.dto import ContextItem

MAX_ITEMS_PER_SOURCE = 4
MAX_ART_STYLE_ITEMS_PER_SOURCE_GROUP = 4
SOURCE_CAPPED_ITEM_TYPES = frozenset({"chunk", "extraction_artifact"})


def source_cap_applies(item: ContextItem) -> bool:
    return item.item_type in SOURCE_CAPPED_ITEM_TYPES


def source_group_cap(item: ContextItem) -> int | None:
    if not source_cap_applies(item):
        return None
    if diagnostic_text(item, "query_expansion_reason") == "art_style_bridge":
        return MAX_ART_STYLE_ITEMS_PER_SOURCE_GROUP
    return None


def source_diversity_key(item: ContextItem) -> str:
    item_source_key = source_key(item)
    if not source_cap_applies(item):
        return item_source_key
    item_source_group_key = source_group_key(item)
    if item_source_group_key != item_source_key:
        return item_source_group_key
    return item_source_key


def chunk_source_counts(items: tuple[ContextItem, ...] | list[ContextItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if item.item_type != "chunk":
            continue
        item_source_key = source_key(item)
        counts[item_source_key] = counts.get(item_source_key, 0) + 1
    return counts


def source_capped_source_counts(
    items: tuple[ContextItem, ...] | list[ContextItem],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if not source_cap_applies(item):
            continue
        item_source_key = source_key(item)
        counts[item_source_key] = counts.get(item_source_key, 0) + 1
    return counts


def source_diversified_order(items: list[ContextItem]) -> tuple[ContextItem, ...]:
    source_positions: dict[str, int] = {}
    indexed: list[tuple[int, int, int, ContextItem]] = []
    for index, item in enumerate(items):
        if item.item_type != "chunk":
            indexed.append((0, 0, index, item))
            continue
        item_source_key = source_diversity_key(item)
        source_position = source_positions.get(item_source_key, 0)
        source_positions[item_source_key] = source_position + 1
        indexed.append((source_diversity_priority(item), source_position, index, item))
    return tuple(item for _, _, _, item in sorted(indexed, key=lambda value: value[:3]))


def source_diversity_priority(item: ContextItem) -> int:
    query_reason = _answer_support_query_reason(item)
    if _SUPPORT_NETWORK_DIRECT_ANSWER_RE.search(item.text) and _has_any_exact_turn_source_ref(item):
        return 0
    if (
        query_reason in _PRECISE_TURN_ANSWER_SUPPORT_REASONS
        and _precise_turn_answer_support_rank(item, query_reason=query_reason) == 0
    ):
        return 0
    if item.item_type == "chunk" and direct_lexical_query_hits(item) >= 2:
        return 0
    return 1


def direct_lexical_query_hits(item: ContextItem) -> int:
    value = _diagnostic_score_signals(item).get("unique_term_hits")
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return 0


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
