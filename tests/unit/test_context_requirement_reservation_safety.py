from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_packer_selection import (
    _SelectionState,
    reserve_coverage_items,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_instruction_candidate_is_never_rescued() -> None:
    unsafe = _item("unsafe", score=1.0, is_instruction=True)

    result = _pack((unsafe, _item("safe", score=0.9, claimed=False)))

    assert "unsafe" not in _selected_ids(result)
    assert result.bundle.diagnostics["coverage_reservations_selected"] == 0
    assert result.bundle.diagnostics["dropped_by_instruction_flag"] == 1


def test_review_only_and_conflicting_candidates_are_not_reserved() -> None:
    reviewed = _item("reviewed", score=0.2, extra={"review_only": True})
    conflicting = _item(
        "conflicting",
        score=0.1,
        extra={"conflicting_fact_id": "fact-current"},
    )
    decoys = tuple(
        _item(f"safe-{index}", score=1.0 - index * 0.01, claimed=False) for index in range(4)
    )

    state = _empty_selection_state()
    diagnostics = reserve_coverage_items(
        state,
        items=[*decoys, reviewed, conflicting],
        budget=64,
        char_budget=18000,
    )

    assert state.selected == []
    assert diagnostics.reservations_selected == 0


def test_unsupported_claim_metadata_degrades_to_ordinary_selection() -> None:
    unsupported = _item(
        "unsupported",
        score=0.1,
        signal_overrides={"unique_term_hits": "many", "hit_ratio": None},
    )
    ranked = _item("ranked", score=0.9, claimed=False)

    result = _pack((unsupported, ranked), token_budget=64)

    assert result.bundle.diagnostics["coverage_obligations_considered"] == 0
    assert result.bundle.diagnostics["coverage_reservations_selected"] == 0
    assert _selected_ids(result)[0] == "ranked"


def test_hard_character_budget_still_wins_over_reservation() -> None:
    oversized = _item("oversized", score=0.1, text="evidence " * 300)
    compact = _item("compact", score=0.9, claimed=False, text="Compact safe evidence.")

    result = _pack((oversized, compact), max_rendered_chars=360)

    assert "oversized" not in _selected_ids(result)
    assert len(result.bundle.rendered_text) <= 360


def _pack(
    items: tuple[ContextItem, ...],
    *,
    token_budget: int = 2000,
    max_rendered_chars: int = 18000,
):
    return ContextPacker().pack(
        bundle_id="ctx-safety",
        items=items,
        token_budget=token_budget,
        max_rendered_chars=max_rendered_chars,
    )


def _item(
    item_id: str,
    *,
    score: float,
    claimed: bool = True,
    is_instruction: bool = False,
    text: str = "Synthetic evidence for the selected release path.",
    extra: dict[str, object] | None = None,
    signal_overrides: dict[str, object] | None = None,
) -> ContextItem:
    signals: dict[str, object] = {
        "unique_term_hits": 8,
        "hit_ratio": 0.8,
    }
    if claimed:
        signals["query_expansion_reason"] = "path-a"
    if signal_overrides:
        signals.update(signal_overrides)
    diagnostics: dict[str, object] = {
        "memory_scope_id": "scope-synthetic",
        "score_signals": signals,
    }
    if extra:
        diagnostics.update(extra)
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="synthetic", source_id=f"source-{item_id}"),),
        is_instruction=is_instruction,
        diagnostics=diagnostics,
    )


def _selected_ids(result) -> tuple[str, ...]:
    return tuple(item.item_id for item in result.bundle.items)


def _empty_selection_state() -> _SelectionState:
    return _SelectionState(
        selected=[],
        selected_keys=set(),
        selected_answer_support_families=set(),
        selected_chunks_by_source={},
        selected_source_capped_items_by_source={},
        selected_art_style_items_by_source_group={},
    )
