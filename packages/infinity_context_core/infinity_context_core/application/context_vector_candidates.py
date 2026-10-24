"""Bounded reserve evidence for canonical drops, not a wider healthy result set."""

from __future__ import annotations

from infinity_context_core.application.context_building_legacy_candidate_adapter import (
    _fused_ranked_keys,
)
from infinity_context_core.domain.entities import MemoryChunk


def vector_candidate_window(
    rankings: dict[str, tuple[str, ...]], *, query_limit: int, pool_limit: int
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Retain the old fused head and add a bounded reserve for canonical hydration."""
    primary = _fused_ranked_keys(
        {key: ranking[:query_limit] for key, ranking in rankings.items()}, limit=pool_limit
    )
    hydration_limit = min(240, pool_limit * 2)
    expanded = _fused_ranked_keys(rankings, limit=hydration_limit)
    return primary, tuple(dict.fromkeys((*primary, *expanded)))[:hydration_limit]


def select_visible_vector_candidates(
    *, primary_ids: tuple[str, ...], candidate_ids: tuple[str, ...], chunks: tuple[MemoryChunk, ...]
) -> tuple[MemoryChunk, ...]:
    """Fill only canonical vacancies; healthy retrieval keeps its exact old order."""
    by_id = {str(chunk.id): chunk for chunk in chunks}
    ordered = dict.fromkeys((*primary_ids, *candidate_ids))
    return tuple(by_id[key] for key in ordered if key in by_id)[: len(primary_ids)]
