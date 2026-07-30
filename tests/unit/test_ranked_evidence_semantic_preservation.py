from __future__ import annotations

from infinity_context_core.application.context_ranked_evidence_selection import (
    RankedEvidenceBudget,
    RankedEvidenceResult,
    select_ranked_evidence,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef
from infinity_context_server.ranked_evidence_semantic_metrics import (
    RankedEvidenceCutoffSnapshot,
    ranked_evidence_semantic_metrics,
)

_CUTOFFS = (10, 20, 50, 200)
_EXACT_SOURCE_ID = "corpus:exact-source"


def _wide_parent(turn_count: int = 205) -> ContextItem:
    markers = tuple(f"D1:{turn}" for turn in range(1, turn_count + 1))
    return ContextItem(
        item_id="rank-1-wide-parent",
        item_type="chunk",
        text="\n".join(
            f"{marker} Speaker: independently supported detail {turn}"
            for turn, marker in enumerate(markers, start=1)
        ),
        score=1.0,
        source_refs=tuple(
            SourceRef(source_type="episode", source_id=f"corpus:{marker}") for marker in markers
        ),
    )


def _exact_rank_two_item() -> ContextItem:
    return ContextItem(
        item_id="rank-2-exact-source",
        item_type="chunk",
        text="A concise independently supported detail.",
        score=0.99,
        source_refs=(SourceRef(source_type="episode", source_id=_EXACT_SOURCE_ID),),
    )


def _select(items: tuple[ContextItem, ...], cutoff: int) -> RankedEvidenceResult:
    return select_ranked_evidence(
        bundle_id=f"semantic-preservation-{cutoff}",
        items=items,
        query="summarize the supported evidence",
        budget=RankedEvidenceBudget(
            max_items=cutoff,
            max_tokens=100_000,
            max_chars=256_000,
        ),
    )


def _covered_exact_refs(result: RankedEvidenceResult) -> tuple[str, ...]:
    return tuple(
        ref.source_id
        for item in result.bundle.items
        for ref in item.source_refs
        if ref.source_id == _EXACT_SOURCE_ID
    )


def test_wide_rank_one_parent_preserves_sources_and_stable_prefixes() -> None:
    parent = _wide_parent()
    items = (parent, _exact_rank_two_item())
    results = tuple(_select(items, cutoff) for cutoff in _CUTOFFS)

    widest_ids = tuple(item.item_id for item in results[-1].bundle.items)
    assert [len(result.bundle.items) for result in results] == list(_CUTOFFS)
    assert all(
        tuple(item.item_id for item in result.bundle.items) == widest_ids[:cutoff]
        for cutoff, result in zip(_CUTOFFS, results, strict=True)
    )
    projected_items = tuple(
        item
        for result in results
        for item in result.bundle.items
        if item.item_id.startswith(parent.item_id)
    )
    assert all(
        item.text in parent.text
        and len(item.source_refs) == 1
        and item.text.startswith(item.source_refs[0].source_id.removeprefix("corpus:"))
        for item in projected_items
    )
    assert all(
        result.bundle.diagnostics["ranked_evidence_candidate_count"] == 2
        and result.bundle.diagnostics["ranked_evidence_selectable_candidate_count"] == 206
        and result.bundle.diagnostics["ranked_evidence_eligible_candidate_count"] == 206
        for result in results
    )


def test_parent_fair_ordering_preserves_exact_rank_two_source_at_all_cutoffs() -> None:
    items = (_wide_parent(), _exact_rank_two_item())
    results = tuple(_select(items, cutoff) for cutoff in _CUTOFFS)
    snapshots = tuple(
        RankedEvidenceCutoffSnapshot(
            cutoff=cutoff,
            item_ids=tuple(item.item_id for item in result.bundle.items),
            covered_refs=_covered_exact_refs(result),
            ranked_telemetry=result.bundle.diagnostics,
        )
        for cutoff, result in zip(_CUTOFFS, results, strict=True)
    )

    metrics = ranked_evidence_semantic_metrics(
        snapshots,
        expected_refs=(_EXACT_SOURCE_ID,),
        reference_cutoff=200,
    )

    assert metrics["matches"] is True
    assert metrics["checks"]["item_ids_stable_prefix"] is True
    assert metrics["retrieval_miss_refs"] == []
    assert [cutoff["recall"] for cutoff in metrics["cutoffs"]] == [1.0] * 4
    assert [cutoff["crowd_out_refs"] for cutoff in metrics["cutoffs"]] == [
        [],
        [],
        [],
        [],
    ]
    assert all(_covered_exact_refs(result) == (_EXACT_SOURCE_ID,) for result in results)
    assert all(
        tuple(item.item_id for item in result.bundle.items).index("rank-2-exact-source") == 1
        for result in results
    )
