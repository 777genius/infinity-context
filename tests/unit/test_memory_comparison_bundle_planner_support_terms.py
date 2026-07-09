from __future__ import annotations

from infinity_context_server.memory_comparison_bundle_planner import (
    EvidenceBundleCandidate,
    EvidenceBundlePlanner,
)


def test_evidence_bundle_planner_keeps_same_source_answer_support_terms() -> None:
    primary = _candidate(
        item_id="primary",
        covered_expected_terms=("planning group",),
        primary_signal=True,
        source_type="raw_turn",
        retrieval_sources=("raw_turns",),
    )
    list_items = tuple(
        _candidate(
            item_id=f"list-item-{index}",
            dedupe_key=f"refs:D1:{index}",
            source_type="chunk",
            retrieval_sources=("semantic_chunks",),
            query_support_terms=(support_term,),
        )
        for index, support_term in enumerate(
            ("alice", "ben", "carla", "dinesh"),
            start=1,
        )
    )

    plan = EvidenceBundlePlanner(
        max_items=5,
        max_items_per_source_type=2,
        max_items_per_retrieval_source=2,
    ).plan((primary, *list_items), case_group="single")

    diagnostics = plan.to_diagnostics()

    assert [item.candidate.item_id for item in plan.items] == [
        "primary",
        "list-item-1",
        "list-item-2",
        "list-item-3",
        "list-item-4",
    ]
    assert plan.dropped_diversity_count == 0
    assert diagnostics["source_type_counts"]["chunk"] == 4
    assert diagnostics["retrieval_source_counts"]["semantic_chunks"] == 4
    assert diagnostics["covered_query_support_term_count"] == 4


def _candidate(
    *,
    item_id: str,
    covered_expected_terms: tuple[str, ...] = (),
    query_support_terms: tuple[str, ...] = (),
    primary_signal: bool = False,
    dedupe_key: str | None = None,
    source_type: str = "unknown",
    retrieval_sources: tuple[str, ...] = (),
) -> EvidenceBundleCandidate:
    return EvidenceBundleCandidate(
        rank=1,
        retrieval_order=1,
        item_id=item_id,
        covered_expected_terms=covered_expected_terms,
        covered_evidence_terms=(),
        query_support_terms=query_support_terms,
        query_support_score=0.0,
        bundle_strength_score=1.0,
        focused_evidence_score=0.0,
        primary_signal=primary_signal,
        dedupe_key=dedupe_key or item_id,
        source_type=source_type,
        retrieval_sources=retrieval_sources,
    )
