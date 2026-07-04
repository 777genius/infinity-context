from __future__ import annotations

from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.context_source_grounding import (
    source_grounding_signal,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_source_grounding_signal_requires_answer_context_and_source_anchor() -> None:
    query = "Which dialogue supports that Alex moved to Denver?"

    assert source_grounding_signal(
        query=query,
        text="D1:2 Jamie: Alex moved to Denver after the promotion.",
        source_refs=(),
    ) == (0.026, 0.0, "source_grounding_match")
    assert source_grounding_signal(
        query=query,
        text="Alex moved to Denver after the promotion.",
        source_refs=(),
    ) == (0.0, 0.034, "source_grounding_answer_without_source")
    assert source_grounding_signal(
        query=query,
        text="D1:3 Jamie: The promotion timing was complicated.",
        source_refs=(),
    ) == (0.0, 0.0, "")


def test_source_grounding_signal_uses_relevant_source_quotes() -> None:
    query = "Which source supports that Alex moved to Denver?"

    assert source_grounding_signal(
        query=query,
        text="Alex moved to Denver after the promotion.",
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="profile-note",
                quote_preview="Jamie said Alex moved to Denver after the promotion.",
            ),
        ),
    ) == (0.016, 0.0, "source_grounding_match")


def test_source_grounding_signal_penalizes_unrelated_source_quotes() -> None:
    query = "Which source supports that Alex moved to Denver?"

    assert source_grounding_signal(
        query=query,
        text="Alex moved to Denver after the promotion.",
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="profile-note",
                quote_preview="Jamie said the promotion timing was complicated.",
            ),
        ),
    ) == (0.0, 0.018, "source_grounding_unrelated_quote")


def test_deterministic_rerank_prefers_source_grounded_dialogue_support() -> None:
    query = "Which dialogue supports that Alex moved to Denver?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    plausible_answer = _item(
        "plausible_answer",
        score=0.72,
        text="Alex moved to Denver after the promotion.",
        source_refs=(),
    )
    grounded_source = _item(
        "grounded_source",
        score=0.7,
        text="D1:2 Jamie: Alex moved to Denver after the promotion.",
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_1:D1:2:turn",
            ),
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (plausible_answer, grounded_source),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    by_id = {item.item_id: item for item in reranked}

    assert by_id["grounded_source"].score > by_id["plausible_answer"].score
    grounded_reasons = by_id["grounded_source"].diagnostics["provenance"][
        "deterministic_rerank_reasons"
    ]
    plausible_reasons = by_id["plausible_answer"].diagnostics["provenance"][
        "deterministic_rerank_reasons"
    ]
    assert "source_grounding_match" in grounded_reasons
    assert "source_grounding_answer_without_source" in plausible_reasons


def _item(
    item_id: str,
    *,
    score: float,
    text: str,
    source_refs: tuple[SourceRef, ...],
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=source_refs,
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"base_score": score},
            "provenance": {"retrieval_sources": ["keyword_chunks"]},
        },
    )


def test_source_grounding_signal_ignores_plain_conversation_topic_query() -> None:
    assert source_grounding_signal(
        query="What was the conversation with Maria about?",
        text="Alex talked with Maria about Project Atlas.",
        source_refs=(),
    ) == (0.0, 0.0, "")
