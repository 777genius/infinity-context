from __future__ import annotations

from infinity_context_core.application.context_conflicting_evidence_rerank import (
    apply_conflicting_evidence_currentness_rerank,
)
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_conflicting_evidence_rerank_prefers_final_source_of_truth() -> None:
    earlier = _item(
        "earlier_provider",
        score=0.84,
        text="D3:2 Alex said the Atlas provider is LocalAI.",
    )
    final = _item(
        "final_provider",
        score=0.78,
        text=(
            "D4:8 Correction: the final source of truth for the Atlas provider "
            "is OpenAI."
        ),
    )

    reranked = apply_conflicting_evidence_currentness_rerank(
        (earlier, final),
        query="What is the current source of truth for the Atlas provider?",
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["final_provider"].score > by_id["earlier_provider"].score
    assert (
        "current_conflict_finality_evidence"
        in by_id["final_provider"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "current_conflict_earlier_assertion"
        in by_id["earlier_provider"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_conflicting_evidence_rerank_demotes_explicit_earlier_assertion() -> None:
    earlier = _item(
        "initial_provider",
        score=0.86,
        text="D2:4 Initially, Alex selected LocalAI as the Atlas provider.",
    )
    final = _item(
        "latest_provider",
        score=0.8,
        text="D5:1 Latest update: Alex switched to OpenAI for the Atlas provider.",
    )

    reranked = apply_conflicting_evidence_currentness_rerank(
        (earlier, final),
        query="Which provider is Alex using now?",
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["latest_provider"].score > by_id["initial_provider"].score
    signals = by_id["initial_provider"].diagnostics["score_signals"]
    assert signals["current_conflict_earlier_assertion_penalty"] > 0.045


def test_conflicting_evidence_rerank_ignores_historical_queries() -> None:
    earlier = _item(
        "initial_provider",
        score=0.86,
        text="D2:4 Initially, Alex selected LocalAI as the Atlas provider.",
    )
    final = _item(
        "latest_provider",
        score=0.8,
        text="D5:1 Latest update: Alex switched to OpenAI for the Atlas provider.",
    )

    reranked = apply_conflicting_evidence_currentness_rerank(
        (earlier, final),
        query="Which provider did Alex initially select?",
    )

    assert reranked == (earlier, final)


def test_deterministic_rerank_applies_current_conflict_finality_signal() -> None:
    query = "What is Alex's final Atlas provider?"
    earlier = _item(
        "earlier_provider",
        score=0.84,
        text="D3:2 Alex said the Atlas provider is LocalAI.",
    )
    final = _item(
        "final_provider",
        score=0.78,
        text=(
            "D4:8 Correction: the final source of truth for the Atlas provider "
            "is OpenAI."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (earlier, final),
        query=query,
        plan=build_query_expansion_plan(query),
        query_anchor_intent=build_query_anchor_intent(query),
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["final_provider"].score > by_id["earlier_provider"].score
    assert (
        "current_conflict_finality_evidence"
        in by_id["final_provider"].diagnostics["provenance"][
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
