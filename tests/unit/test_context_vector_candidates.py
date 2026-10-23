"""A reserve can repair visibility holes, but cannot widen healthy evidence."""

from __future__ import annotations

import random

from infinity_context_core.application.context_collectors import _fused_ranked_keys
from infinity_context_core.application.context_vector_candidates import (
    select_visible_vector_candidates,
    vector_candidate_window,
)

from tests.unit.test_context_candidate_fusion_equivalence import _chunk


def test_healthy_candidates_equal_previous_fusion_across_query_counts_and_caps():
    randomizer = random.Random(9137)
    for query_count in (1, 2, 4, 8):
        for query_limit in (1, 4, 15, 30, 120, 200):
            pool_limit = min(240, query_limit * 4)
            rankings = {
                f"{i}:original_query" if i == 0 else f"{i}:test": tuple(
                    f"chunk_{key}" for key in randomizer.sample(range(500), query_limit * 2)
                )
                for i in range(query_count)
            }
            previous = _fused_ranked_keys(
                {key: ranking[:query_limit] for key, ranking in rankings.items()},
                limit=pool_limit,
            )
            primary, hydration = vector_candidate_window(
                rankings, query_limit=query_limit, pool_limit=pool_limit
            )
            assert primary == previous
            assert set(primary) <= set(hydration)
            assert len(hydration) <= 240
            assert len(set(hydration)) == len(hydration)
            # Canonical storage order is not an authority for retrieval ordering.
            chunks = tuple(_chunk(key) for key in reversed(hydration))
            selected = select_visible_vector_candidates(
                primary_ids=primary, candidate_ids=hydration, chunks=chunks
            )
            assert tuple(str(chunk.id) for chunk in selected) == previous


def test_reserve_only_fills_filtered_primary_slots():
    primary, hydration = vector_candidate_window(
        {"0:original_query": ("missing", "retained", "reserve_a", "reserve_b")},
        query_limit=2,
        pool_limit=8,
    )
    visible = tuple(_chunk(key) for key in ("reserve_b", "retained", "reserve_a"))
    selected = select_visible_vector_candidates(
        primary_ids=primary, candidate_ids=hydration, chunks=visible
    )
    assert tuple(str(chunk.id) for chunk in selected) == ("retained", "reserve_a")
    assert (
        select_visible_vector_candidates(primary_ids=primary, candidate_ids=hydration, chunks=())
        == ()
    )


def test_empty_candidate_window_does_not_invent_evidence():
    assert vector_candidate_window({}, query_limit=2, pool_limit=8) == ((), ())
