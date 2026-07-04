from __future__ import annotations

from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_current_query_prefers_not_x_but_y_correction_over_old_fact() -> None:
    query = "What is the current Atlas provider?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    old_fact = _item(
        "old_provider",
        score=0.74,
        text="D4:6 Sam: Atlas provider is LocalAI.",
    )
    correction = _item(
        "provider_correction",
        score=0.7,
        text="D20:8 Sam: Atlas provider is not LocalAI but OpenAI after the review.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (old_fact, correction),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["provider_correction"].score > by_id["old_provider"].score
    assert (
        "current_state_correction_evidence"
        in by_id["provider_correction"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_past_state_query_keeps_no_longer_side_of_contrastive_correction() -> None:
    query = "Which Atlas provider is no longer current?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    active = _item(
        "active_provider",
        score=0.72,
        text="Atlas provider is OpenAI and remains valid.",
    )
    stale_side = _item(
        "stale_provider_correction",
        score=0.7,
        text=(
            "Atlas provider is not LocalAI but OpenAI after the review; "
            "LocalAI is no longer current."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (active, stale_side),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["stale_provider_correction"].score > by_id["active_provider"].score
    assert (
        "stale_state_exact_evidence"
        in by_id["stale_provider_correction"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_cancellation_query_prefers_reschedule_update_over_original_schedule() -> None:
    query = "Was the Atlas demo canceled or rescheduled?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    original_schedule = _item(
        "original_schedule",
        score=0.73,
        text="D8:2 Sam: The Atlas demo is scheduled for Friday.",
    )
    update = _item(
        "reschedule_update",
        score=0.7,
        text="D12:5 Sam: The Atlas demo was canceled and rescheduled for Monday.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (original_schedule, update),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["reschedule_update"].score > by_id["original_schedule"].score
    assert (
        "schedule_change_match"
        in by_id["reschedule_update"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "schedule_change_active_conflict"
        in by_id["original_schedule"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def _item(item_id: str, *, score: float, text: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"base_score": score},
            "provenance": {"retrieval_sources": ["keyword_chunks"]},
        },
    )
