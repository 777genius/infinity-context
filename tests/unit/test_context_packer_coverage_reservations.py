from dataclasses import replace

import pytest
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_packer_selection import (
    _SelectionState,
    _try_select_item,
    reserve_ranked_source_heads,
)
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


@pytest.mark.parametrize("support", ["producer", "query_excerpt"])
def test_ranked_source_head_survives_long_specialized_prepasses(support: str) -> None:
    target = _head_item("source-head", "independent-source", score=0.99)
    if support == "query_excerpt":
        signals = dict(target.diagnostics["score_signals"])
        signals.pop("application_evidence_contract_tier")
        target = replace(target, diagnostics={
            **target.diagnostics, "score_signals": signals,
            "query_snippet_unique_term_hits": 2,
        })
    specialized = tuple(
        replace(
            _item(
                f"submission-{index}", score=0.8 - index * 0.01,
                source_id=f"submission-source-{index}",
                reason="creative_work_submission_bridge", hits=1, ratio=0.1,
                text=f"D{index + 1}:1 Dana submitted a screenplay to a film contest. "
                + "Details. " * (115 if index == 0 else 60),
            ),
            source_refs=(SourceRef(
                source_type="locomo_turn",
                source_id=f"synthetic:fixture:session_{index + 1}:D{index + 1}:1:turn",
            ),),
        )
        for index in range(8)
    )
    noise = tuple(
        _item(
            f"untyped-{index}", score=1.0, source_id=f"untyped-source-{index}",
            reason="", hits=1, ratio=0.1, text="An unrelated project note.",
        )
        for index in range(40)
    )
    result = ContextPacker().pack(
        bundle_id="ctx-source-head", items=(*noise, *specialized, target),
        query="What places has Dana submitted her work to?",
        token_budget=2000, max_rendered_chars=1500,
    )
    assert "source-head" in _selected_ids(result)
    assert any(item.item_id.startswith("submission-") for item in result.bundle.items)
    assert len(result.bundle.rendered_text) <= 1500


def test_source_head_bound_counts_existing_sources_and_canonical_siblings() -> None:
    state = _source_head_state()
    existing = _head_item("existing", "shared")
    complement = replace(existing, item_id="complement", text="Additional evidence.")
    for item in (existing, complement):
        assert _try_select_item(state, item=item, budget=10000, char_budget=18000)
    head = _head_item("best", "new:pair:1", score=0.99)
    sibling = _head_item("sibling", "new:pair:2", score=0.98)
    scoped = replace(
        head, item_id="other-scope",
        diagnostics={**head.diagnostics, "memory_scope_id": "other"},
    )
    noise = [
        _head_item(f"noise-{i}", f"noise-source-{i}", score=0.9 - i * 0.01)
        for i in range(40)
    ]
    assert reserve_ranked_source_heads(
        state, items=[*reversed(noise), sibling, head, scoped],
        query="evidence", budget=10000, char_budget=18000,
    ) == 7
    assert [item.item_id for item in state.selected] == [
        "existing", "complement", "other-scope", "best",
        "noise-0", "noise-1", "noise-2", "noise-3", "noise-4",
    ]
    # Reservation does not consume the later complementary same-source slot.
    assert _try_select_item(state, item=sibling, budget=10000, char_budget=18000)
    assert head.score == 0.99 and sibling.score == 0.98


def test_source_heads_obey_safety_and_both_packing_budgets() -> None:
    safe = _head_item("safe", "safe-source", score=0.1)
    unsafe = [
        _item(
            "untyped-noise", score=1.0, source_id="untyped-source", reason="",
            hits=1, ratio=0.1, text="High-ranked but unsupported general context.",
        ),
        replace(_head_item("instruction", "instruction-source"), is_instruction=True),
        replace(_head_item("review", "review-source"), diagnostics={"review_only": True}),
        replace(_head_item("conflict", "conflict-source"), diagnostics={
            "provenance": {"trace": {"conflicting_fact_id": "current"}},
        }),
        replace(_head_item("rejected", "rejected-source"), diagnostics={
            "provenance": {"deterministic_rerank_reasons": ["subject_mismatch"]},
        }),
        _head_item("unsafe-source", "ignore-previous-instructions"),
    ]
    oversized = replace(_head_item("oversized", "oversized-source"), text="Long. " * 1000)
    for budget, char_budget in ((64, 18000), (10000, 400)):
        state = _source_head_state()
        assert reserve_ranked_source_heads(
            state, items=[*unsafe, oversized, safe],
            query="evidence", budget=budget, char_budget=char_budget,
        ) == 1
        assert [item.item_id for item in state.selected] == ["safe"]
        assert state.used_tokens <= budget
        packed = ContextPacker().pack(
            bundle_id="ctx-boundary", items=tuple(state.selected),
            token_budget=budget, max_rendered_chars=char_budget,
        )
        assert len(packed.bundle.rendered_text) <= char_budget


@pytest.mark.parametrize("duplicate_chunks", [0, 12])
def test_source_head_rarity_counts_sources_and_handles_duplicate_item_ids(
    duplicate_chunks: int,
) -> None:
    common = [
        replace(
            _head_item(f"common-{index}", f"common-source-{index}"),
            text="Common planning evidence.",
        )
        for index in range(5)
    ]
    rare = replace(
        _head_item(common[0].item_id, "rare-source", score=0.1),
        text="Precise saffron evidence.",
    )
    siblings = [
        replace(rare, item_id=f"sibling-{index}", score=0.01)
        for index in range(duplicate_chunks)
    ]
    state = _source_head_state()
    assert reserve_ranked_source_heads(
        state, items=[*common, rare, *siblings], query="COMMON planning SAFFRON",
        budget=32, char_budget=18000,
    ) == 1
    assert state.selected == [rare]
    assert rare.score == 0.1
    assert state.selected_answer_support_families == set()


@pytest.mark.parametrize(
    ("query", "expected"),
    [("", "excerpt"), ("unmatched", "excerpt"), ("SAFFRON", "producer")],
)
def test_source_head_query_preserves_producer_precedence_and_empty_query_order(
    query: str, expected: str,
) -> None:
    producer = _head_item("producer", "producer-source", score=0.1)
    excerpt = replace(
        _item(
            "excerpt", score=1.0, source_id="excerpt-source", reason="",
            hits=1, ratio=0.1, text="Precise saffron evidence.",
        ),
        diagnostics={"query_snippet_unique_term_hits": 2},
    )
    # An unsupported match must not activate rarity ordering for an unmatched query.
    unsupported = _item(
        "unsupported", score=1.0, source_id="unsupported-source", reason="",
        hits=1, ratio=0.1, text="Unmatched unrelated evidence.",
    )
    state = _source_head_state()
    assert reserve_ranked_source_heads(
        state, items=[producer, excerpt, unsupported], query=query,
        budget=32, char_budget=18000,
    ) == 1
    assert [item.item_id for item in state.selected] == [expected]


def _head_item(item_id: str, source_id: str, *, score: float = 1.0) -> ContextItem:
    item = _item(
        item_id, score=score, source_id=source_id, reason="", hits=1, ratio=0.1,
        text="Whole source evidence.",
    )
    diagnostics = dict(item.diagnostics)
    diagnostics["score_signals"] = {
        **diagnostics["score_signals"], "application_evidence_contract_tier": 1,
    }
    return replace(item, diagnostics=diagnostics)


def _source_head_state() -> _SelectionState:
    return _SelectionState(
        selected=[], selected_keys=set(), selected_answer_support_families=set(),
        selected_chunks_by_source={}, selected_source_capped_items_by_source={},
        selected_art_style_items_by_source_group={},
    )
