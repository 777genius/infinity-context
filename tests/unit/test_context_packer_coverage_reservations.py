from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_coverage_reservation_survives_rank_pressure() -> None:
    target = _item(
        "target",
        score=0.70,
        source_id="source-target",
        reason="path-a",
        hits=9,
        ratio=0.82,
        text="Synthetic owner selected the amber release path after review.",
    )
    decoys = tuple(
        _item(
            f"decoy-{index}",
            score=0.99 - index * 0.01,
            source_id=f"source-{index}",
            reason="path-a",
            hits=2,
            ratio=0.18,
            text=f"General planning note {index} with no decision evidence.",
        )
        for index in range(5)
    )

    result = ContextPacker().pack(
        bundle_id="ctx-coverage",
        items=(*decoys, target),
        token_budget=64,
    )

    assert "target" in _selected_ids(result)
    assert result.bundle.diagnostics["coverage_reservations_selected"] == 1
    assert result.bundle.diagnostics["coverage_selected_obligation_ids"] == ("o-000",)


def test_reservation_obeys_source_cap_and_total_reservation_bound() -> None:
    items = tuple(
        _item(
            f"candidate-{index}",
            score=0.90 - index * 0.01,
            source_id="shared-source",
            reason=f"path-{index}",
            hits=8,
            ratio=0.75,
            text=f"Independent synthetic evidence statement {index}.",
        )
        for index in range(6)
    )

    result = ContextPacker().pack(
        bundle_id="ctx-caps",
        items=items,
        token_budget=2000,
    )

    assert result.bundle.diagnostics["coverage_reservations_selected"] == 4
    assert len(result.bundle.items) == 4
    assert result.bundle.diagnostics["max_source_capped_items_used_per_source"] == 4


def test_provider_diagnostics_do_not_change_canonical_selection() -> None:
    def run(channel: str):
        items = tuple(
            _item(
                item_id,
                score=score,
                source_id=source_id,
                reason=reason,
                hits=hits,
                ratio=ratio,
                text=text,
                channel=channel,
            )
            for item_id, score, source_id, reason, hits, ratio, text in (
                ("strong", 0.8, "source-a", "path-a", 8, 0.8, "Amber path evidence."),
                ("ranked", 0.9, "source-b", "path-a", 2, 0.2, "General note."),
                ("other", 0.7, "source-c", "path-b", 6, 0.6, "Blue path evidence."),
            )
        )
        return ContextPacker().pack(
            bundle_id="ctx-provider-neutral",
            items=items,
            token_budget=64,
        )

    first = run("channel-one")
    second = run("channel-two")

    assert _selected_ids(first) == _selected_ids(second)
    assert first.bundle.diagnostics["coverage_selected_obligation_ids"] == (
        "o-000",
        "o-001",
    )


def test_reserved_diversity_representative_preserves_diversity_diagnostic() -> None:
    fact = _item(
        "stable-fact",
        item_type="fact",
        score=0.9,
        source_id="source-fact",
        reason="",
        hits=0,
        ratio=0.0,
        text="A stable synthetic statement.",
    )
    reserved_chunk = _item(
        "reserved-chunk",
        score=0.8,
        source_id="source-chunk",
        reason="path-a",
        hits=8,
        ratio=0.8,
        text="A bounded synthetic path statement.",
    )

    result = ContextPacker().pack(
        bundle_id="ctx-reserved-diversity",
        items=(fact, reserved_chunk),
        token_budget=2000,
    )

    assert _selected_ids(result) == ("stable-fact", "reserved-chunk")
    assert result.bundle.diagnostics["coverage_reservations_selected"] == 1
    assert result.bundle.diagnostics["diversity_families_used"] == 2
    assert result.bundle.diagnostics["diversity_items_used"] == 2


def test_unclaimed_fixture_preserves_characterized_rank_order_and_rendering() -> None:
    items = (
        _item(
            "first",
            score=0.9,
            source_id="source-a",
            reason="",
            hits=0,
            ratio=0.0,
            text="First stable evidence.",
        ),
        _item(
            "second",
            score=0.8,
            source_id="source-b",
            reason="",
            hits=0,
            ratio=0.0,
            text="Second stable evidence.",
        ),
    )

    result = ContextPacker().pack(
        bundle_id="ctx-parity",
        items=items,
        token_budget=2000,
    )

    assert _selected_ids(result) == ("first", "second")
    assert result.bundle.diagnostics["coverage_reservations_selected"] == 0
    assert "chunk:first score=0.900" in result.bundle.rendered_text
    assert "source=synthetic:source-a" in result.bundle.rendered_text
    assert "chunk:second score=0.800" in result.bundle.rendered_text
    assert "source=synthetic:source-b" in result.bundle.rendered_text


def test_candidate_already_promoted_by_rerank_is_not_reserved() -> None:
    promoted = _item(
        "promoted",
        score=0.2,
        source_id="source-promoted",
        reason="path-a",
        hits=8,
        ratio=0.8,
        text="Already promoted evidence.",
        net_adjustment=0.01,
    )
    ranked = _item(
        "ranked",
        score=0.9,
        source_id="source-ranked",
        reason="",
        hits=0,
        ratio=0.0,
        text="Ordinary ranked evidence.",
    )

    result = ContextPacker().pack(
        bundle_id="ctx-promoted-parity",
        items=(promoted, ranked),
        token_budget=64,
    )

    assert result.bundle.diagnostics["coverage_reservations_selected"] == 0
    assert _selected_ids(result)[0] == "ranked"


def test_unresolved_rerank_conflict_is_not_eligible_for_coverage_reservation() -> None:
    conflicted = _item(
        "conflicted",
        score=0.99,
        source_id="source-conflicted",
        reason="path-a",
        hits=9,
        ratio=0.9,
        text="High lexical overlap with unresolved contradictory evidence.",
        rerank_reasons=("query_anchor_conflict",),
    )
    safe = _item(
        "safe",
        score=0.7,
        source_id="source-safe",
        reason="path-a",
        hits=8,
        ratio=0.8,
        text="Safe source-backed evidence for the amber release path.",
    )

    result = ContextPacker().pack(
        bundle_id="ctx-rerank-conflict",
        items=(conflicted, safe),
        token_budget=2000,
    )

    assert result.bundle.diagnostics["coverage_reservations_selected"] == 1
    assert result.bundle.diagnostics["coverage_selected_obligation_ids"] == ("o-000",)
    assert "safe" in _selected_ids(result)

    conflict_only = ContextPacker().pack(
        bundle_id="ctx-rerank-conflict-only",
        items=(conflicted,),
        token_budget=2000,
    )
    assert conflict_only.bundle.diagnostics["coverage_obligations_considered"] == 0
    assert conflict_only.bundle.diagnostics["coverage_reservations_selected"] == 0


def _item(
    item_id: str,
    *,
    item_type: str = "chunk",
    score: float,
    source_id: str,
    reason: str,
    hits: int,
    ratio: float,
    text: str,
    channel: str = "synthetic-channel",
    net_adjustment: float | None = None,
    rerank_reasons: tuple[str, ...] = (),
) -> ContextItem:
    score_signals: dict[str, object] = {
        "unique_term_hits": hits,
        "hit_ratio": ratio,
    }
    if reason:
        score_signals["query_expansion_reason"] = reason
    if net_adjustment is not None:
        score_signals["deterministic_rerank_net_adjustment"] = net_adjustment
    return ContextItem(
        item_id=item_id,
        item_type=item_type,
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="synthetic", source_id=source_id),),
        diagnostics={
            "memory_scope_id": "scope-synthetic",
            "retrieval_source": channel,
            "retrieval_sources": [channel],
            "score_signals": score_signals,
            **(
                {"provenance": {"deterministic_rerank_reasons": list(rerank_reasons)}}
                if rerank_reasons
                else {}
            ),
        },
    )


def _selected_ids(result) -> tuple[str, ...]:
    return tuple(item.item_id for item in result.bundle.items)
