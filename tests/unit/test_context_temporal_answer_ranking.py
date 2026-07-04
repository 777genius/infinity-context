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


def test_deterministic_rerank_prefers_temporal_answer_evidence() -> None:
    query = "When did Caroline go to the LGBTQ support group?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    with_date = _item(
        "with_date",
        score=0.7,
        text=(
            "session_1 date: 7 May 2023\n"
            "D1:1 Caroline: I went to the LGBTQ support group today."
        ),
    )
    without_date = _item(
        "without_date",
        score=0.72,
        text="D1:1 Caroline: I went to the LGBTQ support group.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (without_date, with_date),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["with_date"].score > by_id["without_date"].score
    assert (
        "temporal_answer_evidence"
        in by_id["with_date"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "temporal_answer_evidence_missing"
        in by_id["without_date"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_does_not_boost_unrelated_nearby_dates() -> None:
    query = "When did Caroline go to the LGBTQ support group?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    grounded_date = _item(
        "grounded_date",
        score=0.69,
        text=(
            "D1:1 Caroline: Yesterday I went to the LGBTQ support group and "
            "met the organizers."
        ),
    )
    unrelated_nearby_date = _item(
        "unrelated_nearby_date",
        score=0.71,
        text=(
            "D1:1 Morgan: Yesterday I watched a documentary.\n"
            "D1:2 Caroline: I went to the LGBTQ support group and met the organizers."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (unrelated_nearby_date, grounded_date),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["grounded_date"].score > by_id["unrelated_nearby_date"].score
    assert (
        "temporal_answer_evidence"
        in by_id["grounded_date"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "temporal_answer_ungrounded_evidence"
        in by_id["unrelated_nearby_date"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_treats_exact_time_query_as_temporal_intent() -> None:
    query = "What exact time did Alex call about Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    with_time = _item(
        "with_time",
        score=0.7,
        text="D3:2 Alex called about Atlas at 9:30 am to confirm the launch plan.",
    )
    without_time = _item(
        "without_time",
        score=0.72,
        text="D3:2 Alex called about Atlas to confirm the launch plan.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (without_time, with_time),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["with_time"].score > by_id["without_time"].score
    assert (
        "temporal_answer_evidence"
        in by_id["with_time"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_uses_media_time_range_as_temporal_answer_evidence() -> None:
    query = "Когда был созвон с Алексом по Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    with_time_range = _item(
        "with_time_range",
        score=0.7,
        text="Созвон с Алексом по Atlas: договорились проверить retrieval.",
        source_refs=(
            SourceRef(
                source_type="audio",
                source_id="call-audio",
                time_start_ms=45_000,
                time_end_ms=75_000,
            ),
        ),
    )
    without_time_range = _item(
        "without_time_range",
        score=0.72,
        text="Созвон с Алексом по Atlas: договорились проверить retrieval.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (without_time_range, with_time_range),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["with_time_range"].score > by_id["without_time_range"].score
    assert (
        "temporal_answer_evidence"
        in by_id["with_time_range"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def _item(
    item_id: str,
    *,
    score: float,
    text: str,
    source_refs: tuple[SourceRef, ...] | None = None,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=source_refs or (SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"base_score": score},
            "provenance": {"retrieval_sources": ["keyword_chunks"]},
        },
    )
