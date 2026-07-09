from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _book_suggestion_item(
    *,
    item_id: str,
    source_id: str,
    text: str,
    score: float,
    distinctive_term_hits: int = 6,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id=source_id,
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {
                "query_expansion_reason": "book_suggestion_bridge",
                "distinctive_term_hits": distinctive_term_hits,
            },
        },
    )


def test_context_packer_keeps_implicit_book_recommendation_turns() -> None:
    filler_items = tuple(
        _book_suggestion_item(
            item_id=f"book_noise_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:4:turn",
            text=f"D{index}:4 Dana talked about books and reading in general.",
            score=0.99 - index * 0.001,
            distinctive_term_hits=8,
        )
        for index in range(1, 9)
    )
    must_see = _book_suggestion_item(
        item_id="must_see",
        source_id="locomo:conv-fixture:session_3:D3:17:turn",
        text=(
            'D3:17 Dana: I just watched "Moon Garden" and it was amazing. '
            "Definitely a must-see!"
        ),
        score=0.85,
    )
    followup = _book_suggestion_item(
        item_id="followup",
        source_id="locomo:conv-fixture:session_19:D19:16:turn",
        text="D19:16 Dana: That's a great one! Let me know what you think when finished.",
        score=0.84,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_implicit_book_suggestions",
        items=(*filler_items, must_see, followup),
        token_budget=2200,
        query="What book recommendations has Dana given Lee?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_3:D3:17:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_19:D19:16:turn" in selected_source_ids
