from __future__ import annotations

from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_packer_selection import (
    _SelectionState,
    reserve_paired_evidence_items,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.normalize import estimate_tokens
from infinity_context_core.domain.entities import SourceRef

_INTERVAL_QUERY = (
    "How many days passed between the day Morgan started watering a herb garden "
    "and the day Morgan harvested fresh herbs?"
)
_INTERVAL_SLOT_1 = "decomposition_temporal_interval_endpoint_1"
_INTERVAL_SLOT_2 = "decomposition_temporal_interval_endpoint_2"
_STATE_QUERY = (
    "For my blend-to-water ratio, did I switch to more water per spoon of blend, "
    "or less?"
)


def test_interval_endpoints_are_admitted_before_ranked_noise() -> None:
    noise = tuple(
        _item(
            f"noise-{index}",
            f"Morgan discussed an unrelated garden project number {index}.",
            f"benchmark:session:{index + 10}:pair:1",
            score=1.0 - index * 0.01,
        )
        for index in range(8)
    )
    started = _item(
        "started",
        "Morgan started watering a herb garden every morning.",
        "benchmark:session:1:pair:1",
        score=0.05,
        slot=_INTERVAL_SLOT_1,
    )
    harvested = _item(
        "harvested",
        "Morgan harvested fresh herbs from the garden several days later.",
        "benchmark:session:2:pair:1",
        score=0.04,
        slot=_INTERVAL_SLOT_2,
    )

    result = _pack((*noise, started, harvested), query=_INTERVAL_QUERY)

    assert {"started", "harvested"}.issubset(_selected_ids(result))
    assert result.bundle.diagnostics["paired_evidence_requirement_kind"] == (
        "temporal_interval"
    )
    assert result.bundle.diagnostics["paired_evidence_reservations_planned"] == 2
    assert result.bundle.diagnostics["paired_evidence_reservations_selected"] == 2


def test_state_transition_keeps_historical_and_current_measurements() -> None:
    historical = _item(
        "historical",
        "Previously I used four ounces of water per spoon of blend.",
        "benchmark:session:3:pair:1",
        score=0.03,
    )
    current = _item(
        "current",
        "I now use six ounces of water per spoon of blend.",
        "benchmark:session:4:pair:1",
        score=0.02,
    )
    noise = tuple(
        _item(
            f"ratio-noise-{index}",
            f"A different recipe note with no direct ratio {index}.",
            f"benchmark:session:{index + 20}:pair:1",
            score=1.0 - index * 0.01,
        )
        for index in range(8)
    )

    result = _pack((*noise, historical, current), query=_STATE_QUERY)

    assert {"historical", "current"}.issubset(_selected_ids(result))
    assert result.bundle.diagnostics["paired_evidence_requirement_kind"] == (
        "state_transition"
    )
    assert result.bundle.diagnostics["paired_evidence_reservations_selected"] == 2


def test_adapter_keeps_paired_sources_distinct() -> None:
    first = _typed_interval_item(
        "first",
        "benchmark:session:7:pair:1:message:1",
        slot=_INTERVAL_SLOT_1,
    )
    mirrored = _typed_interval_item(
        "mirrored",
        "benchmark:session:7:pair:1:message:2",
        slot=_INTERVAL_SLOT_2,
    )
    independent = _typed_interval_item(
        "independent",
        "benchmark:session:8:pair:1:message:1",
        slot=_INTERVAL_SLOT_2,
    )
    state = _empty_state()

    diagnostics = reserve_paired_evidence_items(
        state,
        items=[first, mirrored, independent],
        query=_INTERVAL_QUERY,
        budget=10_000,
        char_budget=18_000,
    )

    assert [item.item_id for item in state.selected] == ["first", "independent"]
    assert diagnostics.reservations_selected == 2


def test_adapter_never_reserves_unsafe_paired_candidates() -> None:
    safe = _typed_interval_item(
        "safe",
        "benchmark:session:1:pair:1",
        slot=_INTERVAL_SLOT_1,
    )
    instruction = _typed_interval_item(
        "instruction",
        "benchmark:session:2:pair:1",
        slot=_INTERVAL_SLOT_2,
        is_instruction=True,
    )
    review_only = _typed_interval_item(
        "review-only",
        "benchmark:session:3:pair:1",
        slot=_INTERVAL_SLOT_2,
        diagnostics={"review_only": True},
    )
    conflicting = _typed_interval_item(
        "conflicting",
        "benchmark:session:4:pair:1",
        slot=_INTERVAL_SLOT_2,
        diagnostics={"conflicting_fact_id": "current-fact"},
    )
    state = _empty_state()

    reserve_paired_evidence_items(
        state,
        items=[safe, instruction, review_only, conflicting],
        query=_INTERVAL_QUERY,
        budget=10_000,
        char_budget=18_000,
    )

    assert [item.item_id for item in state.selected] == ["safe"]


def test_packer_keeps_raw_conflicts_out_of_paired_reservations() -> None:
    started = _typed_interval_item(
        "safe-started",
        "benchmark:session:1:pair:1",
        slot=_INTERVAL_SLOT_1,
        text="Morgan started watering herbs.",
        score=0.90,
        diagnostics=_rich_safe_diagnostics("started"),
    )
    conflicting_duplicate = _typed_interval_item(
        "harvested-duplicate",
        "benchmark:session:2:pair:1",
        slot=_INTERVAL_SLOT_2,
        text="Morgan harvested fresh herbs.",
        score=0.99,
        diagnostics={
            "provenance": {
                "audit": {
                    "details": {
                        "trace": {"conflicting_fact_id": "fact-current"}
                    }
                }
            }
        },
    )
    safe_duplicate = _typed_interval_item(
        "harvested-duplicate",
        "benchmark:session:3:pair:1",
        slot=_INTERVAL_SLOT_2,
        text="Morgan harvested fresh herbs.",
        score=0.98,
        diagnostics=_rich_safe_diagnostics("duplicate"),
    )
    safe_harvested = _typed_interval_item(
        "safe-harvested",
        "benchmark:session:4:pair:1",
        slot=_INTERVAL_SLOT_2,
        text="Morgan harvested fresh herbs.",
        score=0.10,
        diagnostics=_rich_safe_diagnostics("harvested"),
    )

    result = _pack(
        (started, conflicting_duplicate, safe_duplicate, safe_harvested),
        query=_INTERVAL_QUERY,
        token_budget=64,
    )

    assert _selected_ids(result) == {"safe-started", "safe-harvested"}
    assert result.bundle.diagnostics["paired_evidence_reservations_planned"] == 2
    assert result.bundle.diagnostics["paired_evidence_reservations_selected"] == 2


def test_adapter_does_not_force_reservations_past_real_packer_budget() -> None:
    first = _typed_interval_item(
        "first",
        "benchmark:session:1:pair:1",
        slot=_INTERVAL_SLOT_1,
        text="Morgan started watering a herb garden every morning for many weeks.",
    )
    second = _typed_interval_item(
        "second",
        "benchmark:session:2:pair:1",
        slot=_INTERVAL_SLOT_2,
        text="Morgan harvested fresh herbs from the garden after many weeks.",
    )
    selector_budget = sum(estimate_tokens(f"{item.text}\n\n") for item in (first, second))
    state = _empty_state()

    diagnostics = reserve_paired_evidence_items(
        state,
        items=[first, second],
        query=_INTERVAL_QUERY,
        budget=selector_budget,
        char_budget=18_000,
    )

    assert diagnostics.reservations_planned == 2
    assert diagnostics.reservations_selected < diagnostics.reservations_planned
    assert state.used_tokens <= selector_budget


def test_adapter_is_a_noop_for_ordinary_queries() -> None:
    state = _empty_state()
    items = [
        _typed_interval_item(
            "first",
            "benchmark:session:1:pair:1",
            slot=_INTERVAL_SLOT_1,
        ),
        _typed_interval_item(
            "second",
            "benchmark:session:2:pair:1",
            slot=_INTERVAL_SLOT_2,
        ),
    ]

    diagnostics = reserve_paired_evidence_items(
        state,
        items=items,
        query="What did Morgan discuss?",
        budget=10_000,
        char_budget=18_000,
    )

    assert state.selected == []
    assert diagnostics.requirement_kind == ""
    assert diagnostics.reservations_planned == 0
    assert diagnostics.reservations_selected == 0


def _pack(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    token_budget: int = 2_000,
):
    return ContextPacker().pack(
        bundle_id="ctx-paired-reservation",
        items=items,
        token_budget=token_budget,
        query=query,
        max_rendered_chars=720,
    )


def _typed_interval_item(
    item_id: str,
    source_id: str,
    *,
    slot: str,
    text: str = "Direct evidence for one temporal endpoint.",
    is_instruction: bool = False,
    diagnostics: dict[str, object] | None = None,
    score: float = 0.1,
) -> ContextItem:
    return _item(
        item_id,
        text,
        source_id,
        score=score,
        slot=slot,
        is_instruction=is_instruction,
        diagnostics=diagnostics,
    )


def _item(
    item_id: str,
    text: str,
    source_id: str,
    *,
    score: float,
    slot: str | None = None,
    is_instruction: bool = False,
    diagnostics: dict[str, object] | None = None,
) -> ContextItem:
    item_diagnostics = dict(diagnostics or {})
    item_diagnostics["memory_scope_id"] = "scope-paired-test"
    if slot is not None:
        item_diagnostics["score_signals"] = {
            "query_expansion_reason": slot,
            "unique_term_hits": 4,
            "distinctive_term_hits": 3,
            "phrase_bigram_hits": 2,
            "hit_ratio": 0.75,
        }
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="episode", source_id=source_id),),
        is_instruction=is_instruction,
        diagnostics=item_diagnostics,
    )


def _selected_ids(result) -> set[str]:
    return {item.item_id for item in result.bundle.items}


def _rich_safe_diagnostics(label: str) -> dict[str, object]:
    return {"provenance": {"audit": {"details": {"trace": {"label": label}}}}}


def _empty_state() -> _SelectionState:
    return _SelectionState(
        selected=[],
        selected_keys=set(),
        selected_answer_support_families=set(),
        selected_chunks_by_source={},
        selected_source_capped_items_by_source={},
        selected_art_style_items_by_source_group={},
    )
